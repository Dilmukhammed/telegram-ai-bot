from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from memory.db import MemoryDatabase, dumps_json, loads_json_object, parse_utc, utc_now_iso
from memory.ids import make_source_id, make_source_version_id, normalize_source_ref
from memory.jobs import MemoryJobQueue
from memory.lineage import MemoryLineageStore
from memory.models import (
    IngestResult,
    InvalidationResult,
    JobRequest,
    LineageInput,
    LineageRelation,
    MemorySource,
    MemorySourceVersion,
    SourceInput,
    SourceStatus,
    SourceVersionStatus,
)
from memory.pointers import pointer_from_mapping, pointer_to_mapping, replace_pointer_source_version

logger = logging.getLogger(__name__)


class MemoryOwnershipError(PermissionError):
    pass


class MemorySourceStore:
    def __init__(self, db: MemoryDatabase, *, jobs: MemoryJobQueue, lineage: MemoryLineageStore) -> None:
        self._db = db
        self._jobs = jobs
        self._lineage = lineage

    def register(
        self,
        source: SourceInput,
        *,
        initial_jobs: Sequence[JobRequest] = (),
    ) -> IngestResult:
        normalized_ref = normalize_source_ref(source.source_ref)
        source_id = make_source_id(
            user_id=source.user_id,
            source_type=source.source_type,
            source_ref=normalized_ref,
        )
        version_id = make_source_version_id(
            source_id=source_id,
            content_hash=source.content_hash,
        )
        pointer = replace_pointer_source_version(source.pointer, version_id)
        now = utc_now_iso()
        pointer_json = dumps_json(pointer_to_mapping(pointer))
        source_created = False
        version_created = False
        superseded_version_id: str | None = None
        enqueued_job_ids: list[str] = []
        enqueued_jobs_to_log: list[tuple[str, JobRequest]] = []

        with self._db.transaction() as conn:
            existing = conn.execute(
                "SELECT user_id, status FROM memory_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO memory_sources(
                        source_id, user_id, session_id, source_type, source_ref,
                        ingested_at, status, authority_class, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        source.user_id,
                        source.session_id,
                        source.source_type,
                        normalized_ref,
                        now,
                        SourceStatus.ACTIVE.value,
                        source.authority_class,
                        dumps_json(dict(source.source_metadata)),
                    ),
                )
                source_created = True
            else:
                if int(existing["user_id"]) != source.user_id:
                    raise MemoryOwnershipError("source identity belongs to another user")
                if existing["status"] != SourceStatus.ACTIVE.value:
                    raise RuntimeError("cannot register a version for an inactive source")

            version_row = conn.execute(
                "SELECT source_version_id, status FROM memory_source_versions WHERE source_version_id = ?",
                (version_id,),
            ).fetchone()
            if version_row is None:
                active_version = conn.execute(
                    """
                    SELECT source_version_id
                    FROM memory_source_versions
                    WHERE source_id = ? AND status = ?
                    ORDER BY ingested_at DESC
                    LIMIT 1
                    """,
                    (source_id, SourceVersionStatus.ACTIVE.value),
                ).fetchone()
                if active_version is not None:
                    superseded_version_id = str(active_version["source_version_id"])
                    conn.execute(
                        "UPDATE memory_source_versions SET status = ? WHERE source_version_id = ?",
                        (SourceVersionStatus.SUPERSEDED.value, superseded_version_id),
                    )
                    self._jobs.cancel_for_source_version_in_txn(
                        conn,
                        source_version_id=superseded_version_id,
                        user_id=source.user_id,
                        reason=f"superseded by {version_id}",
                    )
                conn.execute(
                    """
                    INSERT INTO memory_source_versions(
                        source_version_id, source_id, content_hash, mime_type,
                        occurred_at, ingested_at, pointer_json, metadata_json,
                        status, supersedes_version_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        source_id,
                        source.content_hash,
                        source.mime_type,
                        source.occurred_at.isoformat() if source.occurred_at else None,
                        now,
                        pointer_json,
                        dumps_json(dict(source.version_metadata)),
                        SourceVersionStatus.ACTIVE.value,
                        superseded_version_id,
                    ),
                )
                version_created = True
                lineage_links = [
                    LineageInput(
                        parent_kind="source",
                        parent_id=source_id,
                        child_kind="source_version",
                        child_id=version_id,
                        relation=LineageRelation.DERIVED_FROM,
                    )
                ]
                if superseded_version_id is not None:
                    lineage_links.append(
                        _supersedes_lineage(
                            old_version_id=superseded_version_id,
                            new_version_id=version_id,
                            user_id=source.user_id,
                        )
                    )
                self._lineage.add_links(
                    conn,
                    user_id=source.user_id,
                    links=lineage_links,
                )
            version_is_active = (
                version_row is None or version_row["status"] == SourceVersionStatus.ACTIVE.value
            )
            if version_is_active:
                for request in initial_jobs:
                    result = self._jobs.enqueue_in_txn(
                        conn,
                        user_id=source.user_id,
                        source_version_id=version_id,
                        request=request,
                    )
                    if result.created:
                        enqueued_job_ids.append(result.job_id)
                        enqueued_jobs_to_log.append((result.job_id, request))

        for job_id, request in enqueued_jobs_to_log:
            self._jobs.log_enqueued(
                job_id=job_id,
                user_id=source.user_id,
                source_version_id=version_id,
                request=request,
            )
        if source_created:
            logger.info(
                "memory_source_registered",
                extra={
                    "event": "memory_source_registered",
                    "source_id": source_id,
                    "user_id": source.user_id,
                    "source_type": source.source_type,
                },
            )
        if version_created:
            logger.info(
                "memory_source_version_created",
                extra={
                    "event": "memory_source_version_created",
                    "source_id": source_id,
                    "source_version_id": version_id,
                    "user_id": source.user_id,
                },
            )
        if superseded_version_id is not None:
            logger.info(
                "memory_source_version_superseded",
                extra={
                    "event": "memory_source_version_superseded",
                    "source_id": source_id,
                    "source_version_id": version_id,
                    "superseded_version_id": superseded_version_id,
                    "user_id": source.user_id,
                },
            )

        return IngestResult(
            source_id=source_id,
            source_version_id=version_id,
            source_created=source_created,
            version_created=version_created,
            superseded_version_id=superseded_version_id,
            enqueued_job_ids=tuple(enqueued_job_ids),
        )

    def get_source(self, source_id: str, *, user_id: int) -> MemorySource | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM memory_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                return None
            if int(row["user_id"]) != user_id:
                raise MemoryOwnershipError("source belongs to another user")
            return _row_to_source(row)

    def get_version(self, source_version_id: str, *, user_id: int) -> MemorySourceVersion | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT v.*, s.user_id AS owner_user_id
                FROM memory_source_versions v
                JOIN memory_sources s ON s.source_id = v.source_id
                WHERE v.source_version_id = ?
                """,
                (source_version_id,),
            ).fetchone()
            if row is None:
                return None
            if int(row["owner_user_id"]) != user_id:
                raise MemoryOwnershipError("source version belongs to another user")
            return _row_to_version(row)

    def list_active_tool_result_after(
        self,
        last_source_id: str,
        *,
        limit: int,
    ) -> list[MemorySource]:
        """Return active tool_result sources with source_id > last_source_id, ordered by source_id."""
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM memory_sources
                WHERE source_type = 'tool_result'
                  AND status = 'active'
                  AND source_id > ?
                ORDER BY source_id ASC
                LIMIT ?
                """,
                (last_source_id, limit),
            ).fetchall()
        return [_row_to_source(row) for row in rows]

    def invalidate(self, source_id: str, *, user_id: int, reason: str) -> InvalidationResult:
        invalidated_version_ids: list[str] = []
        cancelled_job_count = 0
        inactive_descendant_count = 0
        now = utc_now_iso()

        with self._db.transaction() as conn:
            source_row = conn.execute(
                "SELECT * FROM memory_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if source_row is None:
                raise ValueError(f"unknown source_id: {source_id}")
            if int(source_row["user_id"]) != user_id:
                raise MemoryOwnershipError("source belongs to another user")

            existing_metadata = loads_json_object(source_row["metadata_json"])
            metadata_patch = {
                "invalidation_reason": reason,
                "invalidated_at": existing_metadata.get("invalidated_at", now),
            }
            conn.execute(
                """
                UPDATE memory_sources
                SET status = ?, metadata_json = ?
                WHERE source_id = ?
                """,
                (
                    SourceStatus.INVALIDATED.value,
                    dumps_json({**existing_metadata, **metadata_patch}),
                    source_id,
                ),
            )

            version_rows = conn.execute(
                """
                SELECT source_version_id, status
                FROM memory_source_versions
                WHERE source_id = ?
                """,
                (source_id,),
            ).fetchall()
            for version_row in version_rows:
                version_id = str(version_row["source_version_id"])
                if version_row["status"] != SourceVersionStatus.INVALIDATED.value:
                    conn.execute(
                        "UPDATE memory_source_versions SET status = ? WHERE source_version_id = ?",
                        (SourceVersionStatus.INVALIDATED.value, version_id),
                    )
                    invalidated_version_ids.append(version_id)
                cancelled_job_count += self._jobs.cancel_for_source_version_in_txn(
                    conn,
                    source_version_id=version_id,
                    user_id=user_id,
                    reason=reason,
                )

            descendants = self._lineage.descendants_in_txn(
                conn,
                parent_kind="source",
                parent_id=source_id,
                user_id=user_id,
            )
            for record in descendants:
                if record.child_kind == "segment":
                    updated = conn.execute(
                        """
                        UPDATE memory_segments
                        SET status = ?
                        WHERE segment_id = ? AND status != ?
                          AND EXISTS (
                              SELECT 1
                              FROM memory_source_versions v
                              JOIN memory_sources s ON s.source_id = v.source_id
                              WHERE v.source_version_id = memory_segments.source_version_id
                                AND s.user_id = ?
                          )
                        """,
                        (
                            SourceVersionStatus.INVALIDATED.value,
                            record.child_id,
                            SourceVersionStatus.INVALIDATED.value,
                            user_id,
                        ),
                    )
                    inactive_descendant_count += int(updated.rowcount)
                elif record.child_kind == "mention":
                    updated = conn.execute(
                        """
                        UPDATE memory_mentions
                        SET status = 'invalidated'
                        WHERE mention_id = ? AND user_id = ? AND status != 'invalidated'
                        """,
                        (record.child_id, user_id),
                    )
                    inactive_descendant_count += int(updated.rowcount)
                elif record.child_kind == "candidate":
                    updated = conn.execute(
                        """
                        UPDATE memory_claim_candidates
                        SET status = 'invalidated', updated_at = ?
                        WHERE candidate_id = ? AND user_id = ? AND status != 'invalidated'
                        """,
                        (now, record.child_id, user_id),
                    )
                    inactive_descendant_count += int(updated.rowcount)
                elif record.child_kind == "candidate_verdict":
                    updated = conn.execute(
                        """
                        UPDATE memory_candidate_verdicts
                        SET status = 'invalidated'
                        WHERE verdict_id = ? AND user_id = ? AND status != 'invalidated'
                        """,
                        (record.child_id, user_id),
                    )
                    inactive_descendant_count += int(updated.rowcount)
                elif record.child_kind == "candidate_score":
                    updated = conn.execute(
                        """
                        UPDATE memory_candidate_scores
                        SET status = 'invalidated'
                        WHERE score_id = ? AND user_id = ? AND status != 'invalidated'
                        """,
                        (record.child_id, user_id),
                    )
                    inactive_descendant_count += int(updated.rowcount)
                elif record.child_kind == "source_version":
                    conn.execute(
                        """
                        UPDATE memory_source_versions
                        SET status = ?
                        WHERE source_version_id = ?
                          AND EXISTS (
                              SELECT 1
                              FROM memory_sources s
                              WHERE s.source_id = memory_source_versions.source_id
                                AND s.user_id = ?
                          )
                        """,
                        (
                            SourceVersionStatus.INVALIDATED.value,
                            record.child_id,
                            user_id,
                        ),
                    )

        logger.info(
            "memory_source_invalidated",
            extra={
                "event": "memory_source_invalidated",
                "source_id": source_id,
                "user_id": user_id,
                "reason": reason,
                "invalidated_version_ids": invalidated_version_ids,
                "cancelled_job_count": cancelled_job_count,
                "inactive_descendant_count": inactive_descendant_count,
                "status": SourceStatus.INVALIDATED.value,
            },
        )
        return InvalidationResult(
            source_id=source_id,
            invalidated_version_ids=tuple(invalidated_version_ids),
            cancelled_job_count=cancelled_job_count,
            inactive_descendant_count=inactive_descendant_count,
        )


def _supersedes_lineage(*, old_version_id: str, new_version_id: str, user_id: int) -> LineageInput:
    return LineageInput(
        parent_kind="source_version",
        parent_id=old_version_id,
        child_kind="source_version",
        child_id=new_version_id,
        relation=LineageRelation.SUPERSEDES,
    )


def _row_to_source(row: Any) -> MemorySource:
    return MemorySource(
        source_id=str(row["source_id"]),
        user_id=int(row["user_id"]),
        session_id=row["session_id"],
        source_type=str(row["source_type"]),
        source_ref=str(row["source_ref"]),
        ingested_at=parse_utc(row["ingested_at"]) or parse_utc(utc_now_iso()),  # type: ignore[arg-type]
        status=SourceStatus(str(row["status"])),
        authority_class=str(row["authority_class"]),
        metadata=loads_json_object(row["metadata_json"]),
    )


def _row_to_version(row: Any) -> MemorySourceVersion:
    pointer = pointer_from_mapping(loads_json_object(row["pointer_json"]))
    return MemorySourceVersion(
        source_version_id=str(row["source_version_id"]),
        source_id=str(row["source_id"]),
        content_hash=str(row["content_hash"]),
        mime_type=row["mime_type"],
        occurred_at=parse_utc(row["occurred_at"]),
        ingested_at=parse_utc(row["ingested_at"]) or parse_utc(utc_now_iso()),  # type: ignore[arg-type]
        pointer=pointer,
        metadata=loads_json_object(row["metadata_json"]),
        status=SourceVersionStatus(str(row["status"])),
        supersedes_version_id=row["supersedes_version_id"],
    )
