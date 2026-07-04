from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import get_settings


@dataclass(frozen=True)
class StoredGoogleToken:
    telegram_user_id: int
    email: str | None
    refresh_token: str
    access_token: str | None
    token_expiry: datetime | None
    scopes: tuple[str, ...]


class GoogleTokenStore:
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
        owns_connection = connection is None and self._db_path is not None
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS google_tokens (
                    telegram_user_id INTEGER PRIMARY KEY,
                    email TEXT,
                    refresh_token TEXT NOT NULL,
                    access_token TEXT,
                    token_expiry TEXT,
                    scopes TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def get(self, telegram_user_id: int) -> StoredGoogleToken | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM google_tokens WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
        if row is None:
            return None
        expiry = None
        if row["token_expiry"]:
            parsed = datetime.fromisoformat(row["token_expiry"])
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            expiry = parsed
        scopes = tuple(scope for scope in row["scopes"].split(" ") if scope)
        return StoredGoogleToken(
            telegram_user_id=telegram_user_id,
            email=row["email"],
            refresh_token=row["refresh_token"],
            access_token=row["access_token"],
            token_expiry=expiry,
            scopes=scopes,
        )

    def save(
        self,
        *,
        telegram_user_id: int,
        email: str | None,
        refresh_token: str,
        access_token: str | None,
        token_expiry: datetime | None,
        scopes: tuple[str, ...],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        expiry = token_expiry.isoformat() if token_expiry else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO google_tokens (
                    telegram_user_id, email, refresh_token, access_token,
                    token_expiry, scopes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    email = excluded.email,
                    refresh_token = excluded.refresh_token,
                    access_token = excluded.access_token,
                    token_expiry = excluded.token_expiry,
                    scopes = excluded.scopes,
                    updated_at = excluded.updated_at
                """,
                (
                    telegram_user_id,
                    email,
                    refresh_token,
                    access_token,
                    expiry,
                    " ".join(scopes),
                    now,
                ),
            )

    def delete(self, telegram_user_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM google_tokens WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            return cursor.rowcount > 0


_default_store: GoogleTokenStore | None = None


def get_token_store() -> GoogleTokenStore:
    global _default_store
    if _default_store is None:
        _default_store = GoogleTokenStore()
    return _default_store
