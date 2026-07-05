from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import get_settings


@dataclass(frozen=True)
class StoredYandexToken:
    telegram_user_id: int
    access_token: str
    refresh_token: str | None
    token_expiry: datetime | None
    login: str | None
    uid: int | None


class YandexTokenStore:
    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        raw_path = db_path or settings.yandex_token_db_path
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
                CREATE TABLE IF NOT EXISTS yandex_tokens (
                    telegram_user_id INTEGER PRIMARY KEY,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    token_expiry TEXT,
                    login TEXT,
                    uid INTEGER,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS yandex_device_pending (
                    telegram_user_id INTEGER PRIMARY KEY,
                    device_code TEXT NOT NULL,
                    user_code TEXT NOT NULL,
                    verification_url TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def get(self, telegram_user_id: int) -> StoredYandexToken | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM yandex_tokens WHERE telegram_user_id = ?",
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
        return StoredYandexToken(
            telegram_user_id=telegram_user_id,
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            token_expiry=expiry,
            login=row["login"],
            uid=row["uid"],
        )

    def save(
        self,
        *,
        telegram_user_id: int,
        access_token: str,
        refresh_token: str | None,
        token_expiry: datetime | None,
        login: str | None,
        uid: int | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        expiry = token_expiry.isoformat() if token_expiry else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO yandex_tokens (
                    telegram_user_id, access_token, refresh_token,
                    token_expiry, login, uid, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    token_expiry = excluded.token_expiry,
                    login = excluded.login,
                    uid = excluded.uid,
                    updated_at = excluded.updated_at
                """,
                (
                    telegram_user_id,
                    access_token,
                    refresh_token,
                    expiry,
                    login,
                    uid,
                    now,
                ),
            )

    def delete(self, telegram_user_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM yandex_tokens WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            conn.execute(
                "DELETE FROM yandex_device_pending WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            return cursor.rowcount > 0

    def save_device_pending(
        self,
        *,
        telegram_user_id: int,
        device_code: str,
        user_code: str,
        verification_url: str,
        expires_in: int,
    ) -> None:
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=max(expires_in, 60))).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO yandex_device_pending (
                    telegram_user_id, device_code, user_code,
                    verification_url, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    device_code = excluded.device_code,
                    user_code = excluded.user_code,
                    verification_url = excluded.verification_url,
                    expires_at = excluded.expires_at,
                    created_at = excluded.created_at
                """,
                (
                    telegram_user_id,
                    device_code,
                    user_code,
                    verification_url,
                    expires_at,
                    now.isoformat(),
                ),
            )

    def get_device_pending(self, telegram_user_id: int) -> dict[str, str] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM yandex_device_pending WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
        if row is None:
            return None
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at:
            return None
        return {
            "device_code": row["device_code"],
            "user_code": row["user_code"],
            "verification_url": row["verification_url"],
        }

    def clear_device_pending(self, telegram_user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM yandex_device_pending WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )


_default_store: YandexTokenStore | None = None


def get_token_store() -> YandexTokenStore:
    global _default_store
    if _default_store is None:
        _default_store = YandexTokenStore()
    return _default_store
