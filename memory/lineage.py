from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from memory.db import MemoryDatabase, utc_now_iso
from memory.ids import make_lineage_id
from memory.models import LineageInput, LineageRecord, LineageRelation


class MemoryLineageStore:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    def add(self, links: Sequence[LineageInput], *, user_id: int) -> int:
        with self._db.transaction() as conn:
            return self.add_links(conn, user_id=user_id, links=links)

    def add_links(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        links: Sequence[LineageInput],
    ) -> int:
        created = 0
        now = utc_now_iso()
        for link in links:
            _assert_endpoint_owner(
                conn,
                kind=link.parent_kind,
                record_id=link.parent_id,
                user_id=user_id,
            )
            _assert_endpoint_owner(
                conn,
                kind=link.child_kind,
                record_id=link.child_id,
                user_id=user_id,
            )
            lineage_id = make_lineage_id(
                user_id=user_id,
                parent_kind=link.parent_kind,
                parent_id=link.parent_id,
                child_kind=link.child_kind,
                child_id=link.child_id,
                relation=link.relation.value,
            )
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO memory_lineage(
                    lineage_id, user_id, parent_kind, parent_id,
                    child_kind, child_id, relation, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lineage_id,
                    user_id,
                    link.parent_kind,
                    link.parent_id,
                    link.child_kind,
                    link.child_id,
                    link.relation.value,
                    now,
                ),
            )
            created += int(cursor.rowcount)
        return created

    def descendants(
        self,
        parent_kind: str,
        parent_id: str,
        *,
        user_id: int,
    ) -> list[LineageRecord]:
        with self._db.connection() as conn:
            return self.descendants_in_txn(
                conn,
                parent_kind=parent_kind,
                parent_id=parent_id,
                user_id=user_id,
            )

    def descendants_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        parent_kind: str,
        parent_id: str,
        user_id: int,
    ) -> list[LineageRecord]:
        rows = conn.execute(
            """
            WITH RECURSIVE tree AS (
                SELECT lineage_id, user_id, parent_kind, parent_id,
                       child_kind, child_id, relation, created_at
                FROM memory_lineage
                WHERE user_id = ? AND parent_kind = ? AND parent_id = ?
                UNION
                SELECT l.lineage_id, l.user_id, l.parent_kind, l.parent_id,
                       l.child_kind, l.child_id, l.relation, l.created_at
                FROM memory_lineage l
                JOIN tree t
                  ON l.user_id = t.user_id
                 AND l.parent_kind = t.child_kind
                 AND l.parent_id = t.child_id
            )
            SELECT DISTINCT lineage_id, user_id, parent_kind, parent_id,
                            child_kind, child_id, relation, created_at
            FROM tree
            """,
            (user_id, parent_kind, parent_id),
        ).fetchall()
        return [_row_to_record(row) for row in rows]


def _assert_endpoint_owner(
    conn: sqlite3.Connection,
    *,
    kind: str,
    record_id: str,
    user_id: int,
) -> None:
    queries = {
        "source": ("SELECT user_id FROM memory_sources WHERE source_id = ?", record_id),
        "source_version": (
            """
            SELECT s.user_id
            FROM memory_source_versions v
            JOIN memory_sources s ON s.source_id = v.source_id
            WHERE v.source_version_id = ?
            """,
            record_id,
        ),
        "segment": (
            """
            SELECT s.user_id
            FROM memory_segments seg
            JOIN memory_source_versions v ON v.source_version_id = seg.source_version_id
            JOIN memory_sources s ON s.source_id = v.source_id
            WHERE seg.segment_id = ?
            """,
            record_id,
        ),
        "job": ("SELECT user_id FROM memory_jobs WHERE job_id = ?", record_id),
        "processor_run": (
            "SELECT user_id FROM memory_processor_runs WHERE run_id = ?",
            record_id,
        ),
        "mention": (
            "SELECT user_id FROM memory_mentions WHERE mention_id = ?",
            record_id,
        ),
        "candidate": (
            "SELECT user_id FROM memory_claim_candidates WHERE candidate_id = ?",
            record_id,
        ),
    }
    query_and_value = queries.get(kind)
    if query_and_value is None:
        raise ValueError(f"unsupported lineage endpoint kind: {kind!r}")
    query, value = query_and_value
    row = conn.execute(query, (value,)).fetchone()
    if row is None:
        raise ValueError(f"unknown lineage {kind}: {record_id}")
    if int(row["user_id"]) != user_id:
        raise PermissionError(f"lineage {kind} belongs to another user")


def _row_to_record(row: sqlite3.Row) -> LineageRecord:
    from memory.db import parse_utc

    return LineageRecord(
        lineage_id=str(row["lineage_id"]),
        user_id=int(row["user_id"]),
        parent_kind=str(row["parent_kind"]),
        parent_id=str(row["parent_id"]),
        child_kind=str(row["child_kind"]),
        child_id=str(row["child_id"]),
        relation=LineageRelation(str(row["relation"])),
        created_at=parse_utc(row["created_at"]) or parse_utc(utc_now_iso()),  # type: ignore[arg-type]
    )
