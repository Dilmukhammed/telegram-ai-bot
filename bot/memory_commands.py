from __future__ import annotations

from typing import TYPE_CHECKING

from memory.ingestion.cursors import (
    STREAM_CHAT_MESSAGES,
    STREAM_TOOL_RECONCILE,
    STREAM_TOOL_RESULTS,
    IngestionCursorStore,
)
from memory.ingestion.failures import IngestionFailureStore

if TYPE_CHECKING:
    from memory.ingestion.runtime import TextIngestionRuntime
    from memory.service import MemoryService


def format_memory_status(
    *,
    service: MemoryService,
    ingest_runtime: TextIngestionRuntime | None,
    ingest_enabled: bool,
    worker_enabled: bool,
    extraction_enabled: bool = False,
    verification_enabled: bool = False,
    resolution_enabled: bool = False,
    graph_enabled: bool = False,
    shadow_retrieval_enabled: bool = False,
    summaries_enabled: bool = False,
) -> str:
    base = service.status()
    lines = [
        "Graph memory (shadow)",
        f"ingest_enabled={int(ingest_enabled)} worker_enabled={int(worker_enabled)} "
        f"extraction_enabled={int(extraction_enabled)} "
        f"verification_enabled={int(verification_enabled)} "
        f"resolution_enabled={int(resolution_enabled)} "
        f"graph_enabled={int(graph_enabled)} "
        f"shadow_retrieval_enabled={int(shadow_retrieval_enabled)} "
        f"summaries_enabled={int(summaries_enabled)}",
        f"schema_version={base.schema_version}",
        f"sources={base.source_count} active_versions={base.active_version_count}",
        f"dead_jobs={base.dead_job_count} active_workers={base.active_worker_count}",
        f"jobs_by_status={_fmt_counts(base.jobs_by_status)}",
        f"jobs_by_stage={_fmt_counts(base.jobs_by_stage)}",
        f"active_mentions={base.active_mention_count}",
        f"candidates_by_status={_fmt_counts(base.candidates_by_status)}",
        f"active_verdicts={base.active_verdict_count} "
        f"active_candidate_scores={base.active_candidate_score_count}",
        f"assertions={base.assertion_count} belief_heads={base.belief_head_count} "
        f"active_graph_edges={base.active_graph_edge_count} "
        f"summary_dirty_backlog={base.summary_dirty_backlog} "
        f"summaries_by_status={_fmt_counts(base.summaries_by_status)} "
        f"active_communities={base.active_community_count}",
    ]
    if base.oldest_pending_age_seconds is not None:
        lines.append(f"oldest_pending_age_s={base.oldest_pending_age_seconds:.1f}")

    if ingest_runtime is not None:
        runtime_status = ingest_runtime.status()
        lines.append(
            f"ingest_runtime={runtime_status.status.value} "
            f"queue={runtime_status.queue_size}/{runtime_status.queue_maxsize}"
        )
        cursors = IngestionCursorStore(service.db)
        for stream in (STREAM_CHAT_MESSAGES, STREAM_TOOL_RESULTS, STREAM_TOOL_RECONCILE):
            cursor = _load_cursor_row(service, stream)
            if cursor is None:
                continue
            lines.append(
                f"cursor[{stream}]={cursor['cursor_json']} "
                f"seen={cursor['records_seen']} reg={cursor['registered_count']} "
                f"dup={cursor['duplicate_count']} fail={cursor['failed_count']}"
            )
        failures = IngestionFailureStore(service.db)
        for stream in (STREAM_CHAT_MESSAGES, STREAM_TOOL_RESULTS):
            pending = failures.load_due(stream, limit=1000)
            dead = _count_failures(service, stream, status="exhausted")
            lines.append(f"failures[{stream}] pending={len(pending)} dead={dead}")
    return "\n".join(lines)


def _fmt_counts(values: dict[str, int]) -> str:
    if not values:
        return "{}"
    return "{" + ", ".join(f"{key}={value}" for key, value in sorted(values.items())) + "}"


def _load_cursor_row(service: MemoryService, stream: str) -> dict | None:
    with service.db.connection() as conn:
        row = conn.execute(
            """
            SELECT cursor_json, records_seen, registered_count, duplicate_count, failed_count
            FROM memory_ingestion_cursors
            WHERE stream_name = ?
            """,
            (stream,),
        ).fetchone()
    if row is None:
        return None
    return {
        "cursor_json": str(row["cursor_json"]),
        "records_seen": int(row["records_seen"]),
        "registered_count": int(row["registered_count"]),
        "duplicate_count": int(row["duplicate_count"]),
        "failed_count": int(row["failed_count"]),
    }


def _count_failures(service: MemoryService, stream: str, *, status: str) -> int:
    with service.db.connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM memory_ingestion_failures
            WHERE stream_name = ? AND status = ?
            """,
            (stream, status),
        ).fetchone()
    return int(row["c"])
