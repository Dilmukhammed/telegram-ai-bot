"""Key/value helpers for chat_store_meta."""

from __future__ import annotations

import sqlite3

from bot.chat_store.schema import utc_now_iso


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM chat_store_meta WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    return str(row["value"])


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO chat_store_meta (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value, now),
    )
