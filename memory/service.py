from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from typing import Any

from memory.config import MemoryConfig, memory_config_from_settings, validate_memory_config
from memory.db import MemoryDatabase, dumps_json, parse_utc, utc_now, utc_now_iso
from memory.jobs import MemoryJobQueue, MemoryLeaseError
from memory.lineage import MemoryLineageStore
from memory.extraction.candidates import MemoryCandidateStore
from memory.extraction.mentions import MemoryMentionStore
from memory.models import (
    IngestResult,
    JobRequest,
    MemoryJob,
    MemorySource,
    MemorySourceVersion,
    ProcessorContext,
    ProcessorOutput,
    ProcessorRunOutcome,
    SourceInput,
)
from memory.processors import ProcessorRegistry, default_registry
from memory.segments import MemorySegmentStore
from memory.sources import MemorySourceStore
from memory.status import build_memory_status
from memory.verification.verdicts import MemoryVerificationStore
from memory.worker import MemoryWorker

logger = logging.getLogger(__name__)

_service: "MemoryService | None" = None


class MemoryService:
    def __init__(
        self,
        *,
        db_path: str | None = None,
        config: MemoryConfig | None = None,
        registry: ProcessorRegistry | None = None,
    ) -> None:
        self._config = config or memory_config_from_settings()
        validate_memory_config(self._config)
        self._db = MemoryDatabase(db_path or self._config.db_path)
        self._lineage = MemoryLineageStore(self._db)
        self._jobs = MemoryJobQueue(self._db, self._config)
        self._segments = MemorySegmentStore(self._db)
        self._mentions = MemoryMentionStore(self._db)
        self._candidates = MemoryCandidateStore(self._db)
        self._verification = MemoryVerificationStore(self._db)
        self._sources = MemorySourceStore(self._db, jobs=self._jobs, lineage=self._lineage)
        self._registry = registry or default_registry()
        self._worker: MemoryWorker | None = None

    @property
    def db(self) -> MemoryDatabase:
        return self._db

    @property
    def jobs(self) -> MemoryJobQueue:
        return self._jobs

    @property
    def sources(self) -> MemorySourceStore:
        return self._sources

    @property
    def lineage(self) -> MemoryLineageStore:
        return self._lineage

    @property
    def segments(self) -> MemorySegmentStore:
        return self._segments

    @property
    def mentions(self) -> MemoryMentionStore:
        return self._mentions

    @property
    def candidates(self) -> MemoryCandidateStore:
        return self._candidates

    @property
    def verification(self) -> MemoryVerificationStore:
        return self._verification

    @property
    def registry(self) -> ProcessorRegistry:
        return self._registry

    def register_source(
        self,
        source: SourceInput,
        *,
        initial_jobs: Sequence[JobRequest] = (),
    ) -> IngestResult:
        return self._sources.register(source, initial_jobs=initial_jobs)

    def status(self):
        active_workers = 0
        if self._worker is not None and self._worker.started:
            active_workers = 1
        return build_memory_status(self._db, active_worker_count=active_workers)

    async def start_worker(self) -> None:
        if not self._config.worker_enabled:
            logger.info(
                "memory worker disabled by configuration",
                extra={"event": "memory_worker_disabled"},
            )
            return
        if self._worker is None:
            self._worker = MemoryWorker(
                service=self,
                config=self._config,
                registry=self._registry,
            )
        await self._worker.start()

    async def stop_worker(self, *, grace_seconds: float = 30.0) -> None:
        if self._worker is not None:
            await self._worker.stop(grace_seconds=grace_seconds)

    def wake_worker(self) -> None:
        if self._worker is not None:
            self._worker.wake()

    @staticmethod
    def build_processor_context(
        *,
        job: MemoryJob,
        source: MemorySource,
        source_version: MemorySourceVersion,
        worker_id: str,
    ) -> ProcessorContext:
        return ProcessorContext(
            job=job,
            source=source,
            source_version=source_version,
            worker_id=worker_id,
        )

    def record_processor_run_start(self, *, run_id: str, job: MemoryJob) -> None:
        if job.lease_token is None:
            raise MemoryLeaseError("cannot start processor run without a lease token")
        with self._db.transaction(immediate=True) as conn:
            now = utc_now_iso()
            owned = conn.execute(
                """
                SELECT 1
                FROM memory_jobs
                WHERE job_id = ? AND user_id = ? AND status = ?
                  AND lease_owner = ? AND lease_token = ?
                  AND attempts = ? AND input_hash = ?
                  AND processor_name = ? AND processor_version = ?
                  AND lease_until IS NOT NULL AND lease_until > ?
                """,
                (
                    job.job_id,
                    job.user_id,
                    "running",
                    job.lease_owner,
                    job.lease_token,
                    job.attempts,
                    job.input_hash,
                    job.processor_name,
                    job.processor_version,
                    now,
                ),
            ).fetchone()
            if owned is None:
                raise MemoryLeaseError("processor run job lease is no longer valid")
            conn.execute(
                """
                INSERT INTO memory_processor_runs(
                    run_id, job_id, user_id, processor_name, processor_version,
                    prompt_version, model_profile, started_at, input_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    job.job_id,
                    job.user_id,
                    job.processor_name,
                    job.processor_version,
                    job.prompt_version,
                    job.model_profile,
                    now,
                    job.input_hash,
                ),
            )

    def record_processor_run_failure(
        self,
        *,
        run_id: str,
        job: MemoryJob,
        error: BaseException,
    ) -> None:
        with self._db.transaction() as conn:
            updated = conn.execute(
                """
                UPDATE memory_processor_runs
                SET completed_at = ?, outcome = ?, error_class = ?, error_message = ?
                WHERE run_id = ? AND job_id = ? AND user_id = ?
                """,
                (
                    utc_now_iso(),
                    ProcessorRunOutcome.FAILED.value,
                    type(error).__name__,
                    str(error),
                    run_id,
                    job.job_id,
                    job.user_id,
                ),
            )
            if updated.rowcount != 1:
                raise ValueError("processor run does not belong to job")

    def commit_processor_output(
        self,
        *,
        run_id: str,
        job: MemoryJob,
        worker_id: str,
        output: ProcessorOutput,
    ) -> bool:
        if job.lease_token is None:
            return False
        check_now = utc_now_iso()
        duration_seconds: float | None = None
        enqueued_jobs_to_log: list[tuple[str, JobRequest]] = []
        with self._db.transaction(immediate=True) as conn:
            row = conn.execute(
                """
                SELECT j.lease_owner, j.lease_token, j.lease_until, j.attempts,
                       j.input_hash, j.status, j.user_id,
                       s.status AS source_status, v.status AS version_status,
                       s.user_id AS source_user_id
                FROM memory_jobs j
                JOIN memory_source_versions v
                  ON v.source_version_id = j.source_version_id
                JOIN memory_sources s ON s.source_id = v.source_id
                WHERE j.job_id = ?
                """,
                (job.job_id,),
            ).fetchone()
            if (
                row is None
                or row["lease_owner"] != worker_id
                or row["lease_token"] != job.lease_token
                or row["status"] != "running"
                or int(row["attempts"]) != job.attempts
                or row["input_hash"] != job.input_hash
                or row["lease_until"] is None
                or str(row["lease_until"]) <= check_now
                or int(row["user_id"]) != job.user_id
                or int(row["source_user_id"]) != job.user_id
                or row["source_status"] != "active"
                or row["version_status"] != "active"
            ):
                return False
            run_row = conn.execute(
                """
                SELECT started_at
                FROM memory_processor_runs
                WHERE run_id = ? AND job_id = ? AND user_id = ?
                """,
                (run_id, job.job_id, job.user_id),
            ).fetchone()
            if run_row is None:
                raise ValueError("processor run does not belong to job")
            started_at = parse_utc(run_row["started_at"])

            if output.new_segments:
                if any(
                    segment.source_version_id != job.source_version_id
                    for segment in output.new_segments
                ):
                    raise ValueError(
                        "processor output segments must use the job source version"
                    )
                self._segments.insert_segments_in_txn(
                    conn,
                    output.new_segments,
                    user_id=job.user_id,
                    lineage_store=self._lineage,
                )
            if output.lineage:
                self._lineage.add_links(conn, user_id=job.user_id, links=output.lineage)
            mention_ids: dict[tuple[str, str], str] = {}
            if output.new_mentions:
                mention_ids = self._mentions.insert_in_txn(
                    conn,
                    output.new_mentions,
                    user_id=job.user_id,
                    lineage_store=self._lineage,
                )
            if output.new_candidates:
                self._candidates.insert_in_txn(
                    conn,
                    output.new_candidates,
                    user_id=job.user_id,
                    extraction_run_id=run_id,
                    mention_ids=mention_ids,
                    lineage_store=self._lineage,
                )
            if (
                output.new_verdicts
                or output.new_candidate_scores
                or output.candidate_updates
            ):
                if job.target_kind != "candidate" or not job.target_id:
                    raise ValueError(
                        "verification output requires a candidate-targeted job"
                    )
                self._verification.insert_outputs_in_txn(
                    conn,
                    user_id=job.user_id,
                    verification_run_id=run_id,
                    target_candidate_id=job.target_id,
                    verdicts=output.new_verdicts,
                    scores=output.new_candidate_scores,
                    updates=output.candidate_updates,
                    lineage_store=self._lineage,
                )
            for request in output.next_jobs:
                result = self._jobs.enqueue_in_txn(
                    conn,
                    user_id=job.user_id,
                    source_version_id=job.source_version_id,
                    request=request,
                )
                if result.created:
                    enqueued_jobs_to_log.append((result.job_id, request))

            completed_at = utc_now()
            commit_now = completed_at.isoformat()
            if started_at is not None:
                duration_seconds = max(
                    0.0,
                    (completed_at - started_at).total_seconds(),
                )
            updated = conn.execute(
                """
                UPDATE memory_jobs
                SET status = ?, output_json = ?, lease_owner = NULL,
                    lease_token = NULL, lease_until = NULL,
                    updated_at = ?
                WHERE job_id = ? AND lease_owner = ? AND lease_token = ?
                  AND attempts = ? AND input_hash = ? AND status = ?
                  AND lease_until IS NOT NULL AND lease_until > ?
                """,
                (
                    "done",
                    dumps_json(dict(output.output_json)),
                    commit_now,
                    job.job_id,
                    worker_id,
                    job.lease_token,
                    job.attempts,
                    job.input_hash,
                    "running",
                    commit_now,
                ),
            )
            if updated.rowcount != 1:
                raise MemoryLeaseError("lease changed while committing processor output")
            conn.execute(
                """
                UPDATE memory_processor_runs
                SET completed_at = ?, outcome = ?, output_hash = ?
                WHERE run_id = ?
                """,
                (
                    commit_now,
                    ProcessorRunOutcome.COMPLETED.value,
                    output.output_hash,
                    run_id,
                ),
            )
        for next_job_id, request in enqueued_jobs_to_log:
            self._jobs.log_enqueued(
                job_id=next_job_id,
                user_id=job.user_id,
                source_version_id=job.source_version_id,
                request=request,
            )
        logger.info(
            "memory_job_completed",
            extra={
                "event": "memory_job_completed",
                "job_id": job.job_id,
                "user_id": job.user_id,
                "source_version_id": job.source_version_id,
                "stage": job.stage,
                "processor_name": job.processor_name,
                "processor_version": job.processor_version,
                "attempts": job.attempts,
                "duration_seconds": duration_seconds,
                "status": "done",
                "worker_id": worker_id,
            },
        )
        return True


def get_memory_service() -> MemoryService:
    global _service
    if _service is None:
        _service = MemoryService()
    return _service


def reset_memory_service(service: MemoryService | None = None) -> None:
    global _service
    _service = service


def create_memory_runtime() -> MemoryService:
    return MemoryService()
