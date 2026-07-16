from __future__ import annotations

import hashlib
import sqlite3
from typing import Any, Mapping

from memory.db import dumps_json, utc_now_iso
from memory.ids import canonical_json


NEGATIVE_PREFERENCE = "negative_preference"


def apply_negative_preference_constraint_in_txn(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    target_entity_id: str,
    source_belief_id: str,
    subject_entity_id: str | None = None,
    scope: str = "category",
    reason: Mapping[str, Any] | None = None,
) -> tuple[str, int]:
    """Persist an explicit negative and invalidate weaker derived preferences."""
    identity = {
        "user_id": user_id,
        "type": NEGATIVE_PREFERENCE,
        "subject": subject_entity_id,
        "target": target_entity_id,
        "belief": source_belief_id,
    }
    constraint_id = "mac_" + hashlib.sha256(
        canonical_json(identity).encode("utf-8")
    ).hexdigest()[:32]
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO memory_attachment_constraints(
            constraint_id,user_id,constraint_type,subject_entity_id,target_entity_id,
            scope,source_belief_id,status,reason_json,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,'active',?,?,?)
        ON CONFLICT(constraint_id) DO UPDATE SET
            status='active', scope=excluded.scope,
            reason_json=excluded.reason_json, updated_at=excluded.updated_at
        """,
        (
            constraint_id,
            user_id,
            NEGATIVE_PREFERENCE,
            subject_entity_id,
            target_entity_id,
            scope,
            source_belief_id,
            dumps_json(dict(reason or {})),
            now,
            now,
        ),
    )
    reverted = conn.execute(
        """
        UPDATE memory_attachment_events
        SET status='reverted'
        WHERE user_id=? AND op='inferred_preference'
          AND target_entity_id=? AND status IN ('active','possible')
        """,
        (user_id, target_entity_id),
    )
    return constraint_id, int(reverted.rowcount)


def blocks_inferred_preference(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    target_entity_id: str,
    subject_entity_id: str | None = None,
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM memory_attachment_constraints
        WHERE user_id=? AND constraint_type=? AND target_entity_id=?
          AND status='active'
          AND (subject_entity_id IS NULL OR subject_entity_id=?)
        LIMIT 1
        """,
        (user_id, NEGATIVE_PREFERENCE, target_entity_id, subject_entity_id),
    ).fetchone()
    return row is not None


def release_negative_preference_constraints_in_txn(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    target_entity_id: str,
) -> int:
    """A newer explicit positive may supersede an earlier negative constraint."""
    now = utc_now_iso()
    changed = conn.execute(
        """
        UPDATE memory_attachment_constraints
        SET status='released', updated_at=?
        WHERE user_id=? AND constraint_type=? AND target_entity_id=?
          AND status='active'
        """,
        (now, user_id, NEGATIVE_PREFERENCE, target_entity_id),
    )
    return int(changed.rowcount)
