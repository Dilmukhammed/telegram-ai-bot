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
    )


def _count_group(conn, table: str, column: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {column} AS key, COUNT(*) AS c FROM {table} GROUP BY {column}"
    ).fetchall()
    return {str(row["key"]): int(row["c"]) for row in rows}
