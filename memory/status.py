from __future__ import annotations

from datetime import datetime, timezone

from memory.db import MemoryDatabase, parse_utc, utc_now
from memory.models import MemoryStatus
from memory.schema import SCHEMA_VERSION


def build_memory_status(db: MemoryDatabase, *, active_worker_count: int) -> MemoryStatus:
    with db.connection() as conn:
        source_count = int(
            conn.execute("SELECT COUNT(*) AS c FROM memory_sources").fetchone()["c"]
        )
        active_version_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM memory_source_versions WHERE status = ?",
                ("active",),
            ).fetchone()["c"]
        )
        jobs_by_status = _count_group(conn, "memory_jobs", "status")
        jobs_by_stage = _count_group(conn, "memory_jobs", "stage")
        dead_job_count = int(jobs_by_status.get("dead", 0))
        active_mention_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM memory_mentions WHERE status = 'active'"
            ).fetchone()["c"]
        )
        candidates_by_status = _count_group(conn, "memory_claim_candidates", "status")
        active_verdict_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM memory_candidate_verdicts WHERE status = 'active'"
            ).fetchone()["c"]
        )
        active_candidate_score_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM memory_candidate_scores WHERE status = 'active'"
            ).fetchone()["c"]
        )
        assertion_count = _safe_count(conn, "memory_assertions")
        belief_head_count = _safe_count(conn, "memory_belief_heads")
        active_graph_edge_count = _safe_count(
            conn,
            "graph_edges",
            where="status = 'active'",
        )
        summary_dirty_backlog = _safe_count(conn, "graph_summary_dirty")
        summary_counts = _count_group(conn, "graph_summaries", "status")
        active_community_count = _safe_count(
            conn,
            "graph_communities",
            where="status = 'active'",
        )
        attachment_dirty_backlog = _safe_count(conn, "memory_attachment_dirty")
        attachment_events_active = _safe_count(
            conn,
            "memory_attachment_events",
            where="status = 'active'",
        )
        oldest_pending = conn.execute(
            """
            SELECT MIN(created_at) AS oldest
            FROM memory_jobs
            WHERE status = ?
            """,
            ("pending",),
        ).fetchone()["oldest"]

    oldest_pending_age_seconds = None
    if oldest_pending:
        created = parse_utc(oldest_pending)
        if created is not None:
            oldest_pending_age_seconds = max(
                0.0,
                (utc_now() - created).total_seconds(),
            )

    return MemoryStatus(
        schema_version=SCHEMA_VERSION,
        source_count=source_count,
        active_version_count=active_version_count,
        jobs_by_status=jobs_by_status,
        jobs_by_stage=jobs_by_stage,
        oldest_pending_age_seconds=oldest_pending_age_seconds,
        active_worker_count=active_worker_count,
        dead_job_count=dead_job_count,
        active_mention_count=active_mention_count,
        candidates_by_status=candidates_by_status,
        active_verdict_count=active_verdict_count,
        active_candidate_score_count=active_candidate_score_count,
        assertion_count=assertion_count,
        belief_head_count=belief_head_count,
        active_graph_edge_count=active_graph_edge_count,
        summary_dirty_backlog=summary_dirty_backlog,
        summaries_by_status=summary_counts,
        active_community_count=active_community_count,
        attachment_dirty_backlog=attachment_dirty_backlog,
        attachment_events_active=attachment_events_active,
    )


def _safe_count(conn, table: str, *, where: str | None = None) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if exists is None:
        return 0
    sql = f"SELECT COUNT(*) AS c FROM {table}"
    if where:
        sql = f"{sql} WHERE {where}"
    return int(conn.execute(sql).fetchone()["c"])


def _count_group(conn, table: str, column: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {column} AS key, COUNT(*) AS c FROM {table} GROUP BY {column}"
    ).fetchall()
    return {str(row["key"]): int(row["c"]) for row in rows}
