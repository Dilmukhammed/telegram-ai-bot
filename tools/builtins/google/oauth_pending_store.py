from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import get_settings

_PENDING_TTL = timedelta(minutes=30)


class OAuthPendingStore:
    """Stores PKCE code_verifier between auth URL generation and callback."""

    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        raw_path = db_path or settings.google_token_db_path
        if raw_path == ":memory:":
            self._db_path = None
        else:
            self._db_path = Path(raw_path)
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._memory_conn: sqlite3.Connection | None = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._db_path is None:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:")
                self._memory_conn.row_factory = sqlite3.Row
                self._init_db(connection=self._memory_conn)
            return self._memory_conn

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self, connection: sqlite3.Connection | None = None) -> None:
        conn = connection or self._connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_pending (
                telegram_user_id INTEGER PRIMARY KEY,
                code_verifier TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        if connection is None and self._db_path is not None:
            conn.close()

    def save_verifier(self, telegram_user_id: int, code_verifier: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO oauth_pending (telegram_user_id, code_verifier, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    code_verifier = excluded.code_verifier,
                    created_at = excluded.created_at
                """,
                (telegram_user_id, code_verifier, now),
            )
            conn.commit()
        finally:
            if self._db_path is not None:
                conn.close()

    def pop_verifier(self, telegram_user_id: int) -> str | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT code_verifier, created_at FROM oauth_pending WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "DELETE FROM oauth_pending WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            conn.commit()
            created_at = datetime.fromisoformat(row["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created_at > _PENDING_TTL:
                return None
            return row["code_verifier"]
        finally:
            if self._db_path is not None:
                conn.close()


_oauth_pending_store: OAuthPendingStore | None = None


def get_oauth_pending_store() -> OAuthPendingStore:
    global _oauth_pending_store
    if _oauth_pending_store is None:
        _oauth_pending_store = OAuthPendingStore()
    return _oauth_pending_store
