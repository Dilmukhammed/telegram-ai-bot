from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from memory.db import MemoryDatabase, utc_now, utc_now_iso

logger = logging.getLogger(__name__)

_STATUS_PENDING = "pending"
_STATUS_RESOLVED = "resolved"
_STATUS_EXHAUSTED = "exhausted"

_DEFAULT_MAX_ATTEMPTS = 10


class IngestionFailureStore:
    def __init__(self, db: MemoryDatabase, *, max_attempts: int = _DEFAULT_MAX_ATTEMPTS) -> None:
        self._db = db
        self._max_attempts = max_attempts

    def record_failure(
        self,
        stream_name: str,
        item_key: str,
        cursor: dict[str, Any],
        *,
        user_id: int | None = None,
        error: BaseException,
        not_before: str | None = None,
    ) -> None:
        now = utc_now_iso()
        cursor_json = json.dumps(cursor, sort_keys=True, separators=(",", ":"))
        error_class = type(error).__name__
        error_message = str(error)[:2000]
        with self._db.transaction() as conn:
            existing = conn.execute(
                "SELECT attempts FROM memory_ingestion_failures WHERE stream_name = ? AND item_key = ?",
                (stream_name, item_key),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO memory_ingestion_failures(
                        stream_name, item_key, user_id, cursor_json, status,
                        attempts, max_attempts, not_before, error_class, error_message,
                        first_failed_at, last_failed_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stream_name, item_key, user_id, cursor_json, _STATUS_PENDING,
                        self._max_attempts, not_before, error_class, error_message,
                        now, now,
                    ),
                )
            else:
                attempts = int(existing["attempts"]) + 1
                status = _STATUS_EXHAUSTED if attempts >= self._max_attempts else _STATUS_PENDING
                conn.execute(
                    """
                    UPDATE memory_ingestion_failures
                    SET attempts = ?, status = ?, cursor_json = ?, not_before = ?,
                        error_class = ?, error_message = ?, last_failed_at = ?
                    WHERE stream_name = ? AND item_key = ?
                    """,
                    (
                        attempts, status, cursor_json, not_before,
                        error_class, error_message, now,
                        stream_name, item_key,
                    ),
                )

    def resolve(self, stream_name: str, item_key: str) -> None:
        now = utc_now_iso()
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE memory_ingestion_failures
                SET status = ?, resolved_at = ?
                WHERE stream_name = ? AND item_key = ?
                  AND status != ?
                """,
                (_STATUS_RESOLVED, now, stream_name, item_key, _STATUS_RESOLVED),
            )

    def load_due(
        self,
        stream_name: str,
        *,
        limit: int,
        now: str | None = None,
    ) -> list[dict[str, Any]]:
        cutoff = now or utc_now_iso()
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT stream_name, item_key, user_id, cursor_json, attempts, max_attempts
                FROM memory_ingestion_failures
                WHERE stream_name = ? AND status = ?
                  AND (not_before IS NULL OR not_before <= ?)
                ORDER BY last_failed_at ASC
                LIMIT ?
                """,
                (stream_name, _STATUS_PENDING, cutoff, limit),
            ).fetchall()
        return [
            {
                "stream_name": str(row["stream_name"]),
                "item_key": str(row["item_key"]),
                "user_id": row["user_id"],
                "cursor": json.loads(str(row["cursor_json"])),
                "attempts": int(row["attempts"]),
                "max_attempts": int(row["max_attempts"]),
            }
            for row in rows
        ]

    def compute_not_before(self, attempts: int, *, base_seconds: float, max_seconds: float) -> str:
        delay = min(base_seconds * (2 ** max(0, attempts - 1)), max_seconds)
        return (utc_now() + timedelta(seconds=delay)).isoformat()
