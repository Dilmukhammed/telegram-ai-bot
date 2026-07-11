from __future__ import annotations

import logging
import random
import secrets
import sqlite3
from collections.abc import Collection, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from memory.config import MemoryConfig
from memory.db import MemoryDatabase, dumps_json, parse_utc, utc_now, utc_now_iso
from memory.ids import make_job_id
from memory.models import EnqueueResult, JobRequest, JobStatus, MemoryJob

logger = logging.getLogger(__name__)


class MemoryLeaseError(RuntimeError):
    pass


class MemoryJobOwnershipError(PermissionError):
    pass


class MemorySourceInactiveError(RuntimeError):
    pass


class MemoryJobQueue:
    def __init__(self, db: MemoryDatabase, config: MemoryConfig) -> None:
        self._db = db
        self._config = config

    def enqueue(
        self,
        user_id: int,
        source_version_id: str,
        request: JobRequest,
    ) -> EnqueueResult:
        with self._db.transaction() as conn:
            result = self.enqueue_in_txn(conn, user_id, source_version_id, request)
        if result.created:
            self.log_enqueued(
                job_id=result.job_id,
                user_id=user_id,
                source_version_id=source_version_id,
                request=request,
            )
        return result

    def enqueue_in_txn(
        self,
        conn: sqlite3.Connection,
        user_id: int,
        source_version_id: str,
        request: JobRequest,
    ) -> EnqueueResult:
        _validate_job_request(request)
        owner = conn.execute(
            """
            SELECT s.user_id, s.status AS source_status, v.status AS version_status
            FROM memory_source_versions v
            JOIN memory_sources s ON s.source_id = v.source_id
            WHERE v.source_version_id = ?
            """,
            (source_version_id,),
        ).fetchone()
        if owner is None:
            raise ValueError(f"unknown source_version_id: {source_version_id}")
        if int(owner["user_id"]) != user_id:
            raise MemoryJobOwnershipError("source version belongs to another user")
        if owner["source_status"] != "active" or owner["version_status"] != "active":
            raise MemorySourceInactiveError("cannot enqueue work for inactive source version")
        if request.target_kind == "candidate":
            target = conn.execute(
                """
                SELECT c.user_id, extraction_job.source_version_id
                FROM memory_claim_candidates c
                JOIN memory_processor_runs extraction_run
                  ON extraction_run.run_id = c.extraction_run_id
                JOIN memory_jobs extraction_job
                  ON extraction_job.job_id = extraction_run.job_id
                WHERE c.candidate_id = ?
                """,
                (request.target_id,),
            ).fetchone()
            if target is None:
                raise ValueError(f"unknown candidate target: {request.target_id!r}")
            if int(target["user_id"]) != user_id:
                raise MemoryJobOwnershipError("candidate target belongs to another user")
            if str(target["source_version_id"]) != source_version_id:
                raise ValueError("candidate target does not belong to the job source version")

        job_id = make_job_id(
            source_version_id=source_version_id,
            stage=request.stage,
            processor_name=request.processor_name,
            processor_version=request.processor_version,
            prompt_version=request.prompt_version,
            input_hash=request.input_hash,
            config_hash=request.config_hash,
            target_kind=request.target_kind,
            target_id=request.target_id,
        )
        now = utc_now_iso()
        existing = conn.execute(
            "SELECT job_id FROM memory_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if existing is not None:
            return EnqueueResult(job_id=job_id, created=False)

        conn.execute(
            """
            INSERT INTO memory_jobs(
                job_id, user_id, source_version_id, target_kind, target_id,
                stage, status, priority,
                attempts, max_attempts, model_profile, input_hash,
                processor_name, processor_version, prompt_version,
                not_before, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                user_id,
                source_version_id,
                request.target_kind,
                request.target_id,
                request.stage,
                JobStatus.PENDING.value,
                request.priority,
                (
                    request.max_attempts
                    if request.max_attempts is not None
                    else self._config.job_max_attempts
                ),
                request.model_profile,
                request.input_hash,
                request.processor_name,
                request.processor_version,
                request.prompt_version,
                now,
                now,
                now,
            ),
        )
        return EnqueueResult(job_id=job_id, created=True)

    @staticmethod
    def log_enqueued(
        *,
        job_id: str,
        user_id: int,
        source_version_id: str,
        request: JobRequest,
    ) -> None:
        logger.info(
            "memory_job_enqueued",
            extra={
                "event": "memory_job_enqueued",
                "job_id": job_id,
                "user_id": user_id,
                "source_version_id": source_version_id,
                "stage": request.stage,
                "processor_name": request.processor_name,
                "processor_version": request.processor_version,
                "attempts": 0,
                "status": JobStatus.PENDING.value,
            },
        )

    def claim(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
        stages: Collection[str] | None = None,
    ) -> list[MemoryJob]:
        if not worker_id.strip():
            raise ValueError("worker_id must be non-empty")
        if limit < 1:
            return []
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be >= 1")
        claimed: list[MemoryJob] = []

        with self._db.transaction(immediate=True) as conn:
            now = utc_now()
            now_iso = now.isoformat()
            lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
            conn.execute(
                """
                UPDATE memory_jobs
                SET status = ?, lease_owner = NULL, lease_token = NULL,
                    lease_until = NULL, last_error = ?, updated_at = ?
                WHERE status IN (?, ?)
                  AND NOT EXISTS (
                    SELECT 1
                    FROM memory_source_versions v
                    JOIN memory_sources s ON s.source_id = v.source_id
                    WHERE v.source_version_id = memory_jobs.source_version_id
                      AND v.status = 'active'
                      AND s.status = 'active'
                      AND s.user_id = memory_jobs.user_id
                  )
                """,
                (
                    JobStatus.CANCELLED.value,
                    "source version is inactive or ownership is invalid",
                    now_iso,
                    JobStatus.PENDING.value,
                    JobStatus.RUNNING.value,
                ),
            )
            conn.execute(
                """
                UPDATE memory_jobs
                SET status = ?, lease_owner = NULL, lease_token = NULL,
                    lease_until = NULL, last_error = ?, updated_at = ?
                WHERE attempts >= max_attempts
                  AND (
                    status = ?
                    OR (status = ? AND lease_until IS NOT NULL AND lease_until <= ?)
                  )
                """,
                (
                    JobStatus.DEAD.value,
                    "maximum attempts exhausted",
                    now_iso,
                    JobStatus.PENDING.value,
                    JobStatus.RUNNING.value,
                    now_iso,
                ),
            )
            params: list[Any] = [JobStatus.PENDING.value, now_iso, JobStatus.RUNNING.value, now_iso]
            stage_filter = ""
            if stages is not None:
                if not stages:
                    return []
                placeholders = ", ".join("?" for _ in stages)
                stage_filter = f" AND stage IN ({placeholders})"
                params.extend(stages)

            rows = conn.execute(
                f"""
                SELECT job_id
                FROM memory_jobs
                WHERE (
                    (status = ? AND (not_before IS NULL OR not_before <= ?))
                    OR (status = ? AND lease_until IS NOT NULL AND lease_until <= ?)
                )
                AND attempts < max_attempts
                AND EXISTS (
                    SELECT 1
                    FROM memory_source_versions v
                    JOIN memory_sources s ON s.source_id = v.source_id
                    WHERE v.source_version_id = memory_jobs.source_version_id
                      AND v.status = 'active'
                      AND s.status = 'active'
                      AND s.user_id = memory_jobs.user_id
                )
                {stage_filter}
                ORDER BY priority DESC, created_at ASC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()

            for row in rows:
                job_id = str(row["job_id"])
                lease_token = secrets.token_hex(24)
                updated = conn.execute(
                    """
                    UPDATE memory_jobs
                    SET status = ?, lease_owner = ?, lease_token = ?, lease_until = ?,
                        attempts = attempts + 1, updated_at = ?
                    WHERE job_id = ? AND (
                        (status = ? AND (not_before IS NULL OR not_before <= ?))
                        OR (status = ? AND lease_until IS NOT NULL AND lease_until <= ?)
                    )
                    AND attempts < max_attempts
                    """,
                    (
                        JobStatus.RUNNING.value,
                        worker_id,
                        lease_token,
                        lease_until,
                        now_iso,
                        job_id,
                        JobStatus.PENDING.value,
                        now_iso,
                        JobStatus.RUNNING.value,
                        now_iso,
                    ),
                )
                if updated.rowcount != 1:
                    continue
                job_row = conn.execute(
                    "SELECT * FROM memory_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if job_row is not None:
                    claimed.append(_row_to_job(job_row))
                    logger.info(
                        "memory_job_claimed",
                        extra={
                            "event": "memory_job_claimed",
                            "job_id": job_id,
                            "worker_id": worker_id,
                            "source_version_id": job_row["source_version_id"],
                            "stage": job_row["stage"],
                            "processor_name": job_row["processor_name"],
                            "processor_version": job_row["processor_version"],
                            "attempts": job_row["attempts"],
                            "status": JobStatus.RUNNING.value,
                            "lease_until": lease_until,
                        },
                    )
        return claimed

    def heartbeat(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        attempt: int,
        input_hash: str,
        lease_seconds: int,
    ) -> bool:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be >= 1")
        with self._db.transaction(immediate=True) as conn:
            now = utc_now()
            lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
            updated = conn.execute(
                """
                UPDATE memory_jobs
                SET lease_until = ?, updated_at = ?
                WHERE job_id = ? AND lease_owner = ? AND lease_token = ?
                  AND attempts = ? AND input_hash = ? AND status = ?
                  AND lease_until IS NOT NULL AND lease_until > ?
                  AND EXISTS (
                    SELECT 1
                    FROM memory_source_versions v
                    JOIN memory_sources s ON s.source_id = v.source_id
                    WHERE v.source_version_id = memory_jobs.source_version_id
                      AND v.status = 'active' AND s.status = 'active'
                      AND s.user_id = memory_jobs.user_id
                  )
                """,
                (
                    lease_until,
                    now.isoformat(),
                    job_id,
                    worker_id,
                    lease_token,
                    attempt,
                    input_hash,
                    JobStatus.RUNNING.value,
                    now.isoformat(),
                ),
            )
            return updated.rowcount == 1

    def complete(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        attempt: int,
        input_hash: str,
        output_hash: str | None,
        output_json: dict[str, Any] | None,
    ) -> bool:
        with self._db.transaction(immediate=True) as conn:
            now = utc_now_iso()
            updated = conn.execute(
                """
                UPDATE memory_jobs
                SET status = ?, output_json = ?, lease_owner = NULL,
                    lease_token = NULL, lease_until = NULL,
                    updated_at = ?
                WHERE job_id = ? AND lease_owner = ? AND lease_token = ?
                  AND attempts = ? AND input_hash = ? AND status = ?
                  AND lease_until IS NOT NULL AND lease_until > ?
                  AND EXISTS (
                    SELECT 1
                    FROM memory_source_versions v
                    JOIN memory_sources s ON s.source_id = v.source_id
                    WHERE v.source_version_id = memory_jobs.source_version_id
                      AND v.status = 'active' AND s.status = 'active'
                      AND s.user_id = memory_jobs.user_id
                  )
                """,
                (
                    JobStatus.DONE.value,
                    dumps_json(output_json) if output_json is not None else None,
                    now,
                    job_id,
                    worker_id,
                    lease_token,
                    attempt,
                    input_hash,
                    JobStatus.RUNNING.value,
                    now,
                ),
            )
            if updated.rowcount != 1:
                return False
            row = conn.execute(
                """
                SELECT user_id, source_version_id, stage, processor_name,
                       processor_version, attempts
                FROM memory_jobs WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            logger.info(
                "memory_job_completed",
                extra={
                    "event": "memory_job_completed",
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "user_id": row["user_id"] if row is not None else None,
                    "source_version_id": (
                        row["source_version_id"] if row is not None else None
                    ),
                    "stage": row["stage"] if row is not None else None,
                    "processor_name": (
                        row["processor_name"] if row is not None else None
                    ),
                    "processor_version": (
                        row["processor_version"] if row is not None else None
                    ),
                    "attempts": row["attempts"] if row is not None else attempt,
                    "status": JobStatus.DONE.value,
                },
            )
            return True

    def fail(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        attempt: int,
        input_hash: str,
        error: BaseException,
        retryable: bool,
    ) -> JobStatus:
        with self._db.transaction(immediate=True) as conn:
            now = utc_now()
            now_iso = now.isoformat()
            row = conn.execute(
                "SELECT * FROM memory_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] != JobStatus.RUNNING.value
                or row["lease_owner"] != worker_id
                or row["lease_token"] != lease_token
                or int(row["attempts"]) != attempt
                or row["input_hash"] != input_hash
                or row["lease_until"] is None
                or str(row["lease_until"]) <= now_iso
            ):
                raise MemoryLeaseError("job is not owned by worker")
            attempts = int(row["attempts"])
            max_attempts = int(row["max_attempts"])
            if retryable and attempts < max_attempts:
                delay = _retry_delay_seconds(
                    attempts=attempts,
                    base=self._config.job_retry_base_seconds,
                    maximum=self._config.job_retry_max_seconds,
                )
                not_before = (now + timedelta(seconds=delay)).isoformat()
                conn.execute(
                    """
                    UPDATE memory_jobs
                    SET status = ?, not_before = ?, lease_owner = NULL,
                        lease_token = NULL, lease_until = NULL,
                        last_error = ?, updated_at = ?
                    WHERE job_id = ? AND lease_token = ? AND attempts = ?
                    """,
                    (
                        JobStatus.PENDING.value,
                        not_before,
                        str(error),
                        now_iso,
                        job_id,
                        lease_token,
                        attempt,
                    ),
                )
                logger.info(
                    "memory_job_retried",
                    extra={
                        "event": "memory_job_retried",
                        "job_id": job_id,
                        "worker_id": worker_id,
                        "source_version_id": row["source_version_id"],
                        "stage": row["stage"],
                        "processor_name": row["processor_name"],
                        "processor_version": row["processor_version"],
                        "attempts": attempts,
                        "retry_delay_seconds": delay,
                        "status": JobStatus.PENDING.value,
                    },
                )
                return JobStatus.PENDING

            final_status = JobStatus.DEAD if retryable else JobStatus.FAILED
            conn.execute(
                """
                UPDATE memory_jobs
                SET status = ?, lease_owner = NULL, lease_token = NULL, lease_until = NULL,
                    last_error = ?, updated_at = ?
                WHERE job_id = ? AND lease_token = ? AND attempts = ?
                """,
                (
                    final_status.value,
                    str(error),
                    now_iso,
                    job_id,
                    lease_token,
                    attempt,
                ),
            )
            if final_status is JobStatus.DEAD:
                logger.info(
                    "memory_job_dead",
                    extra={
                        "event": "memory_job_dead",
                        "job_id": job_id,
                        "worker_id": worker_id,
                        "source_version_id": row["source_version_id"],
                        "stage": row["stage"],
                        "processor_name": row["processor_name"],
                        "processor_version": row["processor_version"],
                        "attempts": attempts,
                        "status": JobStatus.DEAD.value,
                    },
                )
            return final_status

    def cancel_for_source_version(
        self,
        source_version_id: str,
        *,
        user_id: int,
        reason: str,
    ) -> int:
        with self._db.transaction() as conn:
            return self.cancel_for_source_version_in_txn(
                conn,
                source_version_id=source_version_id,
                user_id=user_id,
                reason=reason,
            )

    def release_worker_leases(self, *, worker_id: str, reason: str) -> int:
        with self._db.transaction(immediate=True) as conn:
            now = utc_now_iso()
            updated = conn.execute(
                """
                UPDATE memory_jobs
                SET status = ?, not_before = ?, lease_owner = NULL,
                    lease_token = NULL, lease_until = NULL,
                    last_error = ?, updated_at = ?
                WHERE lease_owner = ? AND status = ?
                """,
                (
                    JobStatus.PENDING.value,
                    now,
                    f"lease released: {reason}",
                    now,
                    worker_id,
                    JobStatus.RUNNING.value,
                ),
            )
            return int(updated.rowcount)

    def cancel_for_source_version_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        source_version_id: str,
        user_id: int,
        reason: str,
    ) -> int:
        now = utc_now_iso()
        updated = conn.execute(
            """
            UPDATE memory_jobs
            SET status = ?, last_error = ?, lease_owner = NULL,
                lease_token = NULL, lease_until = NULL, updated_at = ?
            WHERE source_version_id = ? AND user_id = ?
              AND status IN (?, ?)
            """,
            (
                JobStatus.CANCELLED.value,
                f"cancelled: {reason}",
                now,
                source_version_id,
                user_id,
                JobStatus.PENDING.value,
                JobStatus.RUNNING.value,
            ),
        )
        return int(updated.rowcount)

    def get_job(self, job_id: str) -> MemoryJob | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM memory_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            return _row_to_job(row)


def _retry_delay_seconds(*, attempts: int, base: float, maximum: float) -> float:
    exponent = max(0, attempts - 1)
    delay = min(maximum, base * (2**exponent))
    jitter = random.uniform(0, min(1.0, delay * 0.1))
    return min(maximum, delay + jitter)


def _validate_job_request(request: JobRequest) -> None:
    for field_name, value in (
        ("stage", request.stage),
        ("processor_name", request.processor_name),
        ("processor_version", request.processor_version),
        ("input_hash", request.input_hash),
    ):
        if not str(value).strip():
            raise ValueError(f"{field_name} must be non-empty")
    if request.max_attempts is not None and request.max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if (request.target_kind is None) != (request.target_id is None):
        raise ValueError("target_kind and target_id must be provided together")
    if request.target_kind is not None:
        if request.target_kind != "candidate":
            raise ValueError(f"unsupported job target kind: {request.target_kind!r}")
        if not str(request.target_id).strip():
            raise ValueError("target_id must be non-empty")


def _row_to_job(row: Any) -> MemoryJob:
    return MemoryJob(
        job_id=str(row["job_id"]),
        user_id=int(row["user_id"]),
        source_version_id=str(row["source_version_id"]),
        stage=str(row["stage"]),
        status=JobStatus(str(row["status"])),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        processor_name=str(row["processor_name"]),
        processor_version=str(row["processor_version"]),
        prompt_version=row["prompt_version"],
        input_hash=str(row["input_hash"]),
        priority=int(row["priority"]),
        not_before=parse_utc(row["not_before"]),
        lease_owner=row["lease_owner"],
        lease_token=row["lease_token"],
        lease_until=parse_utc(row["lease_until"]),
        model_profile=row["model_profile"],
        target_kind=row["target_kind"],
        target_id=row["target_id"],
    )
