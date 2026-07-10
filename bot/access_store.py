from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from config import get_settings

AccessStatus = Literal["pending", "approved", "denied"]


@dataclass(frozen=True)
class AccessUserRecord:
    user_id: int
    status: AccessStatus
    username: str | None
    display_name: str | None
    google_email: str | None
    google_email_pending: bool
    google_test_user_verified: bool
    google_test_user_verified_at: datetime | None
    approved_by: int | None
    created_at: datetime
    updated_at: datetime


class AccessStore:
    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        raw_path = db_path or settings.access_db_path
        if raw_path == ":memory:":
            self._db_path: Path | None = None
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
                CREATE TABLE IF NOT EXISTS access_users (
                    user_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL,
                    username TEXT,
                    display_name TEXT,
                    google_email TEXT,
                    google_email_pending INTEGER NOT NULL DEFAULT 0,
                    google_test_user_verified INTEGER NOT NULL DEFAULT 0,
                    google_test_user_verified_at TEXT,
                    approved_by INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "google_test_user_verified", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "google_test_user_verified_at", "TEXT")
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, name: str, ddl: str) -> None:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(access_users)").fetchall()
        }
        if name not in columns:
            conn.execute(f"ALTER TABLE access_users ADD COLUMN {name} {ddl}")

    @staticmethod
    def _parse_dt(raw: str) -> datetime:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _row_to_record(self, row: sqlite3.Row) -> AccessUserRecord:
        return AccessUserRecord(
            user_id=int(row["user_id"]),
            status=row["status"],
            username=row["username"],
            display_name=row["display_name"],
            google_email=row["google_email"],
            google_email_pending=bool(row["google_email_pending"]),
            google_test_user_verified=bool(row["google_test_user_verified"]),
            google_test_user_verified_at=(
                self._parse_dt(row["google_test_user_verified_at"])
                if row["google_test_user_verified_at"]
                else None
            ),
            approved_by=row["approved_by"],
            created_at=self._parse_dt(row["created_at"]),
            updated_at=self._parse_dt(row["updated_at"]),
        )

    def get(self, user_id: int) -> AccessUserRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM access_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def upsert_pending(
        self,
        user_id: int,
        *,
        username: str | None,
        display_name: str | None,
    ) -> AccessUserRecord:
        existing = self.get(user_id)
        if existing and existing.status in ("approved", "denied"):
            return existing

        now = self._now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO access_users (
                    user_id, status, username, display_name, google_email,
                    google_email_pending, google_test_user_verified,
                    google_test_user_verified_at, approved_by, created_at, updated_at
                )
                VALUES (?, 'pending', ?, ?, NULL, 0, 0, NULL, NULL, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    status = 'pending',
                    username = excluded.username,
                    display_name = excluded.display_name,
                    updated_at = excluded.updated_at
                """,
                (user_id, username, display_name, now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM access_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    def set_status(
        self,
        user_id: int,
        status: AccessStatus,
        *,
        approved_by: int | None = None,
    ) -> AccessUserRecord | None:
        now = self._now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM access_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE access_users
                SET status = ?, approved_by = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (status, approved_by, now, user_id),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM access_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if updated is None:
            return None
        return self._row_to_record(updated)

    def set_google_email_pending(self, user_id: int, pending: bool) -> None:
        now = self._now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT user_id FROM access_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO access_users (
                        user_id, status, username, display_name, google_email,
                        google_email_pending, google_test_user_verified,
                        google_test_user_verified_at, approved_by, created_at, updated_at
                    )
                    VALUES (?, 'approved', NULL, NULL, NULL, ?, 0, NULL, NULL, ?, ?)
                    """,
                    (user_id, int(pending), now, now),
                )
            else:
                conn.execute(
                    """
                    UPDATE access_users
                    SET google_email_pending = ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (int(pending), now, user_id),
                )
            conn.commit()

    def save_google_email(self, user_id: int, email: str) -> AccessUserRecord:
        now = self._now_iso()
        normalized = email.strip().lower()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT user_id FROM access_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO access_users (
                        user_id, status, username, display_name, google_email,
                        google_email_pending, google_test_user_verified,
                        google_test_user_verified_at, approved_by, created_at, updated_at
                    )
                    VALUES (?, 'approved', NULL, NULL, ?, 0, 0, NULL, NULL, ?, ?)
                    """,
                    (user_id, normalized, now, now),
                )
            else:
                conn.execute(
                    """
                    UPDATE access_users
                    SET google_email = ?, google_email_pending = 0,
                        google_test_user_verified = 0, google_test_user_verified_at = NULL,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (normalized, now, user_id),
                )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM access_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    def set_google_test_user_verified(self, user_id: int, *, verified: bool) -> AccessUserRecord | None:
        now = self._now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM access_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE access_users
                SET google_test_user_verified = ?,
                    google_test_user_verified_at = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (int(verified), now if verified else None, now, user_id),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM access_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if updated is None:
            return None
        return self._row_to_record(updated)


_store: AccessStore | None = None


def get_access_store() -> AccessStore:
    global _store
    if _store is None:
        _store = AccessStore()
    return _store


def reset_access_store(store: AccessStore | None = None) -> None:
    global _store
    _store = store
