from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from memory.db import MemoryDatabase, utc_now, utc_now_iso
from memory.ids import make_attachment_dirty_id


@dataclass(frozen=True, slots=True)
class AttachmentDirtyRow:
    dirty_id: str
    user_id: int
    belief_id: str
    not_before: str
    reason: str | None


class AttachmentDirtyStore:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    def mark_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        belief_id: str,
        debounce_seconds: float,
        reason: str | None = None,
    ) -> str:
        dirty_id = make_attachment_dirty_id(user_id=user_id, belief_id=belief_id)
        now = utc_now()
        not_before = (now + timedelta(seconds=max(0.0, debounce_seconds))).isoformat()
        ts = now.isoformat()
        conn.execute(
            """
            INSERT INTO memory_attachment_dirty(
                dirty_id, user_id, belief_id, not_before, lease_until,
                reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(user_id, belief_id) DO UPDATE SET
                not_before = CASE
                    WHEN excluded.not_before > memory_attachment_dirty.not_before
                    THEN excluded.not_before
                    ELSE memory_attachment_dirty.not_before
                END,
                reason = COALESCE(excluded.reason, memory_attachment_dirty.reason),
                lease_until = NULL,
                updated_at = excluded.updated_at
            """,
            (dirty_id, user_id, belief_id, not_before, reason, ts, ts),
        )
        return dirty_id

    def claim(self, *, limit: int, lease_seconds: int = 60) -> list[AttachmentDirtyRow]:
        if limit < 1:
            return []
        claimed: list[AttachmentDirtyRow] = []
        with self._db.transaction(immediate=True) as conn:
            now = utc_now()
            now_iso = now.isoformat()
            lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
            conn.execute(
                """
                UPDATE memory_attachment_dirty
                SET lease_until = NULL
                WHERE lease_until IS NOT NULL AND lease_until < ?
                """,
                (now_iso,),
            )
            rows = conn.execute(
                """
                SELECT dirty_id, user_id, belief_id, not_before, reason
                FROM memory_attachment_dirty
                WHERE not_before <= ?
                  AND (lease_until IS NULL OR lease_until < ?)
                ORDER BY not_before, updated_at, dirty_id
                LIMIT ?
                """,
                (now_iso, now_iso, limit),
            ).fetchall()
            for row in rows:
                dirty_id = str(row["dirty_id"])
                conn.execute(
                    """
                    UPDATE memory_attachment_dirty
                    SET lease_until = ?, updated_at = ?
                    WHERE dirty_id = ?
                    """,
                    (lease_until, now_iso, dirty_id),
                )
                claimed.append(
                    AttachmentDirtyRow(
                        dirty_id=dirty_id,
                        user_id=int(row["user_id"]),
                        belief_id=str(row["belief_id"]),
                        not_before=str(row["not_before"]),
                        reason=str(row["reason"]) if row["reason"] else None,
                    )
                )
        return claimed

    def clear(self, dirty_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM memory_attachment_dirty WHERE dirty_id = ?",
                (dirty_id,),
            )

    def backlog_count(self, *, user_id: int | None = None) -> int:
        with self._db.connection() as conn:
            if user_id is None:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM memory_attachment_dirty"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM memory_attachment_dirty WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
        return int(row["c"]) if row else 0
