from __future__ import annotations

import sqlite3
from datetime import datetime

from memory.db import parse_utc, utc_now


def is_negative_blocked(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    source_entity_id: str,
    op: str,
    target_entity_id: str,
) -> bool:
    row = conn.execute(
        """
        SELECT status, expires_at
        FROM memory_attachment_negatives
        WHERE user_id = ? AND source_entity_id = ? AND op = ? AND target_entity_id = ?
        """,
        (user_id, source_entity_id, op, target_entity_id),
    ).fetchone()
    if row is None or str(row["status"]) != "active":
        return False
    expires = row["expires_at"]
    if expires:
        exp = parse_utc(str(expires))
        if exp is not None and exp <= utc_now():
            return False
    return True
