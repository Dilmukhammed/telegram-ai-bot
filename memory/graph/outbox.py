from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta

from memory.db import MemoryDatabase, utc_now, utc_now_iso
from memory.graph.schemas import (
    OUTBOX_DONE,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_PROCESSING,
    OUTBOX_REMOVE,
    OUTBOX_UPSERT,
    is_materializable,
)
from memory.ids import make_graph_outbox_event_id


@dataclass(frozen=True, slots=True)
class GraphOutboxEvent:
    event_id: str
    user_id: int
    belief_id: str
    operation: str
    payload_hash: str
    attempts: int


def enqueue_belief_head_change(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    belief_id: str,
    belief_status: str,
    utility_class: str,
    revision_id: str,
) -> str:
    operation = (
        OUTBOX_UPSERT
        if is_materializable(
            belief_status=belief_status, utility_class=utility_class
        )
        else OUTBOX_REMOVE
    )
    return enqueue_outbox_in_txn(
        conn,
        user_id=user_id,
        belief_id=belief_id,
        operation=operation,
        payload_hash=revision_id,
    )


class MemoryGraphOutbox:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    def enqueue_belief_head_change_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        belief_id: str,
        belief_status: str,
        utility_class: str,
        revision_id: str,
    ) -> str:
        return enqueue_belief_head_change(
            conn,
            user_id=user_id,
            belief_id=belief_id,
            belief_status=belief_status,
            utility_class=utility_class,
            revision_id=revision_id,
        )

    def claim(
        self,
        *,
        limit: int,
        lease_seconds: int = 30,
    ) -> list[GraphOutboxEvent]:
        if limit < 1:
            return []
        claimed: list[GraphOutboxEvent] = []
        with self._db.transaction(immediate=True) as conn:
            now = utc_now()
            now_iso = now.isoformat()
            lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
            # Reclaim expired leases.
            conn.execute(
                """
                UPDATE graph_outbox
                SET status = ?, lease_until = NULL
                WHERE status = ? AND lease_until IS NOT NULL AND lease_until < ?
                """,
                (OUTBOX_PENDING, OUTBOX_PROCESSING, now_iso),
            )
            rows = conn.execute(
                """
                SELECT event_id, user_id, belief_id, operation, payload_hash, attempts
                FROM graph_outbox
                WHERE status = ?
                ORDER BY created_at, event_id
                LIMIT ?
                """,
                (OUTBOX_PENDING, limit),
            ).fetchall()
            for row in rows:
                event_id = str(row["event_id"])
                conn.execute(
                    """
                    UPDATE graph_outbox
                    SET status = ?, lease_until = ?, attempts = attempts + 1
                    WHERE event_id = ? AND status = ?
                    """,
                    (OUTBOX_PROCESSING, lease_until, event_id, OUTBOX_PENDING),
                )
                claimed.append(
                    GraphOutboxEvent(
                        event_id=event_id,
                        user_id=int(row["user_id"]),
                        belief_id=str(row["belief_id"]),
                        operation=str(row["operation"]),
                        payload_hash=str(row["payload_hash"]),
                        attempts=int(row["attempts"]) + 1,
                    )
                )
        return claimed

    def mark_done(self, event_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE graph_outbox
                SET status = ?, processed_at = ?, lease_until = NULL, last_error = NULL
                WHERE event_id = ?
                """,
                (OUTBOX_DONE, utc_now_iso(), event_id),
            )

    def mark_failed(self, event_id: str, *, error: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE graph_outbox
                SET status = ?, last_error = ?, lease_until = NULL, processed_at = ?
                WHERE event_id = ?
                """,
                (OUTBOX_FAILED, error[:2000], utc_now_iso(), event_id),
            )


def enqueue_outbox_in_txn(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    belief_id: str,
    operation: str,
    payload_hash: str,
) -> str:
    event_id = make_graph_outbox_event_id(
        user_id=user_id,
        belief_id=belief_id,
        operation=operation,
        payload_hash=payload_hash,
    )
    now = utc_now_iso()
    existing = conn.execute(
        "SELECT event_id, status FROM graph_outbox WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    if existing is not None:
        if str(existing["status"]) in {OUTBOX_DONE, OUTBOX_FAILED}:
            conn.execute(
                """
                UPDATE graph_outbox
                SET status = ?, attempts = 0, lease_until = NULL,
                    last_error = NULL, processed_at = NULL, created_at = ?
                WHERE event_id = ?
                """,
                (OUTBOX_PENDING, now, event_id),
            )
        return event_id
    conn.execute(
        """
        INSERT INTO graph_outbox(
            event_id, user_id, belief_id, operation, payload_hash,
            status, attempts, lease_until, last_error, created_at, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?, NULL)
        """,
        (
            event_id,
            user_id,
            belief_id,
            operation,
            payload_hash,
            OUTBOX_PENDING,
            now,
        ),
    )
    return event_id


def enqueue_rebuild_user_in_txn(
    conn: sqlite3.Connection,
    *,
    user_id: int,
) -> str:
    from memory.graph.schemas import OUTBOX_REBUILD_USER

    return enqueue_outbox_in_txn(
        conn,
        user_id=user_id,
        belief_id=f"user:{user_id}",
        operation=OUTBOX_REBUILD_USER,
        payload_hash=f"rebuild:{user_id}",
    )
