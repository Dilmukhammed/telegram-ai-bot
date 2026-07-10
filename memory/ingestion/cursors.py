from __future__ import annotations

import json
import logging
from typing import Any

from memory.db import MemoryDatabase, utc_now_iso

logger = logging.getLogger(__name__)

STREAM_CHAT_MESSAGES = "chat_messages"
STREAM_TOOL_RESULTS = "tool_results"
STREAM_TOOL_RECONCILE = "tool_reconcile"

ALL_STREAMS = (STREAM_CHAT_MESSAGES, STREAM_TOOL_RESULTS, STREAM_TOOL_RECONCILE)


def _dumps(cursor: dict[str, Any]) -> str:
    return json.dumps(cursor, sort_keys=True, separators=(",", ":"))


class IngestionCursorStore:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    def load(self, stream_name: str) -> dict[str, Any] | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT cursor_json FROM memory_ingestion_cursors WHERE stream_name = ?",
                (stream_name,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["cursor_json"]))

    def initialize(self, stream_name: str, cursor: dict[str, Any]) -> None:
        now = utc_now_iso()
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO memory_ingestion_cursors(
                    stream_name, cursor_json, initialized_at, updated_at,
                    records_seen, registered_count, duplicate_count, failed_count
                ) VALUES (?, ?, ?, ?, 0, 0, 0, 0)
                ON CONFLICT(stream_name) DO NOTHING
                """,
                (stream_name, _dumps(cursor), now, now),
            )

    def advance(
        self,
        stream_name: str,
        cursor: dict[str, Any],
        *,
        records_seen_delta: int = 0,
        registered_delta: int = 0,
        duplicate_delta: int = 0,
        failed_delta: int = 0,
        scan_completed: bool = False,
    ) -> None:
        now = utc_now_iso()
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE memory_ingestion_cursors
                SET cursor_json = ?,
                    updated_at = ?,
                    last_scan_completed_at = CASE WHEN ? THEN ? ELSE last_scan_completed_at END,
                    records_seen = records_seen + ?,
                    registered_count = registered_count + ?,
                    duplicate_count = duplicate_count + ?,
                    failed_count = failed_count + ?
                WHERE stream_name = ?
                """,
                (
                    _dumps(cursor),
                    now,
                    1 if scan_completed else 0,
                    now,
                    records_seen_delta,
                    registered_delta,
                    duplicate_delta,
                    failed_delta,
                    stream_name,
                ),
            )

    def mark_scan_started(self, stream_name: str) -> None:
        now = utc_now_iso()
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE memory_ingestion_cursors
                SET last_scan_started_at = ?, last_error = NULL
                WHERE stream_name = ?
                """,
                (now, stream_name),
            )

    def record_error(self, stream_name: str, error: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE memory_ingestion_cursors SET last_error = ? WHERE stream_name = ?",
                (error[:2000], stream_name),
            )
