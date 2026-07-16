from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import get_settings

PROFILE_STATUS_NONE = "none"
PROFILE_STATUS_UPLOADING = "uploading"
PROFILE_STATUS_READY = "ready"
PROFILE_STATUS_ERROR = "error"
PROFILE_STATUS_REVOKED = "revoked"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


@dataclass(frozen=True)
class StoredBrowserProfile:
    telegram_user_id: int
    steel_profile_id: str
    status: str
    label: str | None
    created_at: str
    updated_at: str
    last_used_at: str
    last_snapshot_at: str | None
    snapshot_error: str | None


@dataclass(frozen=True)
class StoredViewerToken:
    token: str
    telegram_user_id: int
    steel_session_id: str
    debug_url: str
    created_at: str
    expires_at: str
    consumed_at: str | None
    revoked_at: str | None


@dataclass(frozen=True)
class SessionAuditRow:
    lease_id: str
    telegram_user_id: int
    run_id: str
    steel_session_id: str
    steel_profile_id: str | None
    purpose: str
    opened_at: str
    closed_at: str | None
    close_reason: str | None
    release_ok: int | None
    release_attempts: int
    error: str | None


class BrowserProfileStore:
    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        raw_path = db_path or settings.browser_profile_db_path
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
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS browser_profiles (
                    telegram_user_id INTEGER PRIMARY KEY,
                    steel_profile_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    label TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    last_snapshot_at TEXT,
                    snapshot_error TEXT
                );

                CREATE TABLE IF NOT EXISTS browser_viewer_tokens (
                    token TEXT PRIMARY KEY,
                    telegram_user_id INTEGER NOT NULL,
                    steel_session_id TEXT NOT NULL,
                    debug_url TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    revoked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS browser_session_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lease_id TEXT NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    run_id TEXT NOT NULL,
                    steel_session_id TEXT NOT NULL,
                    steel_profile_id TEXT,
                    purpose TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    close_reason TEXT,
                    release_ok INTEGER,
                    release_attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_browser_session_audit_open
                    ON browser_session_audit(closed_at, opened_at);
                """
            )
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def get_profile(self, telegram_user_id: int) -> StoredBrowserProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_profiles WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_profile(row)

    def upsert_profile(
        self,
        *,
        telegram_user_id: int,
        steel_profile_id: str,
        status: str,
        label: str | None = None,
        last_snapshot_at: str | None = None,
        snapshot_error: str | None = None,
        touch_used: bool = True,
    ) -> StoredBrowserProfile:
        now = _utc_now()
        existing = self.get_profile(telegram_user_id)
        created_at = existing.created_at if existing else now
        last_used_at = now if touch_used else (existing.last_used_at if existing else now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO browser_profiles (
                    telegram_user_id, steel_profile_id, status, label,
                    created_at, updated_at, last_used_at, last_snapshot_at, snapshot_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    steel_profile_id = excluded.steel_profile_id,
                    status = excluded.status,
                    label = COALESCE(excluded.label, browser_profiles.label),
                    updated_at = excluded.updated_at,
                    last_used_at = excluded.last_used_at,
                    last_snapshot_at = COALESCE(excluded.last_snapshot_at, browser_profiles.last_snapshot_at),
                    snapshot_error = excluded.snapshot_error
                """,
                (
                    telegram_user_id,
                    steel_profile_id,
                    status,
                    label,
                    created_at,
                    now,
                    last_used_at,
                    last_snapshot_at,
                    snapshot_error,
                ),
            )
        profile = self.get_profile(telegram_user_id)
        assert profile is not None
        return profile

    def update_profile_status(
        self,
        telegram_user_id: int,
        *,
        status: str,
        last_snapshot_at: str | None = None,
        snapshot_error: str | None = None,
    ) -> StoredBrowserProfile | None:
        profile = self.get_profile(telegram_user_id)
        if profile is None:
            return None
        return self.upsert_profile(
            telegram_user_id=telegram_user_id,
            steel_profile_id=profile.steel_profile_id,
            status=status,
            last_snapshot_at=last_snapshot_at,
            snapshot_error=snapshot_error,
            touch_used=False,
        )

    def delete_profile(self, telegram_user_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM browser_profiles WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            return cursor.rowcount > 0

    def mint_viewer_token(
        self,
        *,
        token: str,
        telegram_user_id: int,
        steel_session_id: str,
        debug_url: str,
        expires_at: str,
    ) -> StoredViewerToken:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO browser_viewer_tokens (
                    token, telegram_user_id, steel_session_id, debug_url,
                    created_at, expires_at, consumed_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (token, telegram_user_id, steel_session_id, debug_url, now, expires_at),
            )
        stored = self.get_viewer_token(token)
        assert stored is not None
        return stored

    def get_viewer_token(self, token: str) -> StoredViewerToken | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_viewer_tokens WHERE token = ?",
                (token,),
            ).fetchone()
        if row is None:
            return None
        return StoredViewerToken(
            token=row["token"],
            telegram_user_id=int(row["telegram_user_id"]),
            steel_session_id=row["steel_session_id"],
            debug_url=row["debug_url"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            consumed_at=row["consumed_at"],
            revoked_at=row["revoked_at"],
        )

    def consume_viewer_token(self, token: str) -> StoredViewerToken | None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE browser_viewer_tokens
                SET consumed_at = ?
                WHERE token = ? AND consumed_at IS NULL AND revoked_at IS NULL
                """,
                (now, token),
            )
        return self.get_viewer_token(token)

    def revoke_viewer_tokens_for_session(self, steel_session_id: str) -> int:
        now = _utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE browser_viewer_tokens
                SET revoked_at = ?
                WHERE steel_session_id = ? AND revoked_at IS NULL
                """,
                (now, steel_session_id),
            )
            return cursor.rowcount

    def open_session_audit(
        self,
        *,
        lease_id: str,
        telegram_user_id: int,
        run_id: str,
        steel_session_id: str,
        steel_profile_id: str | None,
        purpose: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO browser_session_audit (
                    lease_id, telegram_user_id, run_id, steel_session_id,
                    steel_profile_id, purpose, opened_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lease_id,
                    telegram_user_id,
                    run_id,
                    steel_session_id,
                    steel_profile_id,
                    purpose,
                    _utc_now(),
                ),
            )

    def close_session_audit(
        self,
        lease_id: str,
        *,
        close_reason: str,
        release_ok: bool,
        error: str | None = None,
        release_attempts: int = 1,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE browser_session_audit
                SET closed_at = ?, close_reason = ?, release_ok = ?,
                    release_attempts = ?, error = ?
                WHERE lease_id = ?
                """,
                (
                    _utc_now(),
                    close_reason,
                    1 if release_ok else 0,
                    release_attempts,
                    error,
                    lease_id,
                ),
            )

    def list_unreleased_audits(self) -> list[SessionAuditRow]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM browser_session_audit
                WHERE closed_at IS NULL OR release_ok = 0
                ORDER BY id ASC
                """
            ).fetchall()
        return [self._row_to_audit(row) for row in rows]

    @staticmethod
    def _row_to_profile(row: sqlite3.Row) -> StoredBrowserProfile:
        return StoredBrowserProfile(
            telegram_user_id=int(row["telegram_user_id"]),
            steel_profile_id=row["steel_profile_id"],
            status=row["status"],
            label=row["label"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_used_at=row["last_used_at"],
            last_snapshot_at=row["last_snapshot_at"],
            snapshot_error=row["snapshot_error"],
        )

    @staticmethod
    def _row_to_audit(row: sqlite3.Row) -> SessionAuditRow:
        return SessionAuditRow(
            lease_id=row["lease_id"],
            telegram_user_id=int(row["telegram_user_id"]),
            run_id=row["run_id"],
            steel_session_id=row["steel_session_id"],
            steel_profile_id=row["steel_profile_id"],
            purpose=row["purpose"],
            opened_at=row["opened_at"],
            closed_at=row["closed_at"],
            close_reason=row["close_reason"],
            release_ok=row["release_ok"],
            release_attempts=int(row["release_attempts"] or 0),
            error=row["error"],
        )


_default_store: BrowserProfileStore | None = None


def get_browser_profile_store() -> BrowserProfileStore:
    global _default_store
    if _default_store is None:
        _default_store = BrowserProfileStore()
    return _default_store


def reset_browser_profile_store_for_tests() -> None:
    global _default_store
    _default_store = None
