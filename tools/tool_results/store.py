from __future__ import annotations

import logging
import secrets
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from config import get_settings

if TYPE_CHECKING:
    from memory.ingestion.models import ToolCursor
    from memory.ingestion.protocols import ToolResultLifecycleObserver

logger = logging.getLogger(__name__)
_FAR_FUTURE = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def tool_result_expires_at(*, now: datetime | None = None) -> datetime:
    settings = get_settings()
    if settings.tool_result_ttl_hours <= 0:
        return _FAR_FUTURE
    base = now or datetime.now(timezone.utc)
    return base + timedelta(hours=settings.tool_result_ttl_hours)


def tool_results_expire_enabled() -> bool:
    return get_settings().tool_result_ttl_hours > 0


@dataclass(frozen=True)
class StoredToolResult:
    ref: str
    display_ref: int
    user_id: int
    run_id: str | None
    tool_name: str
    turn: int
    payload_kind: str
    args_json: str | None
    payload_json: str
    char_count: int
    summary: str | None
    summarize_status: str
    summarize_attempts: int
    ok: bool
    cached: bool
    created_at: datetime
    expires_at: datetime

_store: "ToolResultStore | None" = None


class ToolResultStore:
    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        raw_path = db_path or settings.tool_result_db_path
        if raw_path == ":memory:":
            self._db_path: Path | None = None
            self._memory_conn: sqlite3.Connection | None = None
        else:
            self._db_path = Path(raw_path)
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._memory_conn = None
        self._lifecycle_observer: ToolResultLifecycleObserver | None = None
        self._init_db()

    def set_lifecycle_observer(self, observer: ToolResultLifecycleObserver | None) -> None:
        self._lifecycle_observer = observer

    def _notify_inserted(self, *, user_id: int, ref: str) -> None:
        observer = self._lifecycle_observer
        if observer is None:
            return
        try:
            observer.inserted(user_id=user_id, ref=ref)
        except Exception:
            logger.exception(
                "tool_result_lifecycle_insert_failed",
                extra={"event": "tool_result_lifecycle_insert_failed", "user_id": user_id},
            )

    def _notify_deleted(self, deleted: Sequence[tuple[int, str]], *, reason: str) -> None:
        observer = self._lifecycle_observer
        if observer is None or not deleted:
            return
        for user_id, ref in deleted:
            try:
                observer.deleted(user_id=user_id, ref=ref, reason=reason)
            except Exception:
                logger.exception(
                    "tool_result_lifecycle_delete_failed",
                    extra={"event": "tool_result_lifecycle_delete_failed", "user_id": user_id},
                )
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
                CREATE TABLE IF NOT EXISTS tool_results (
                    ref TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    run_id TEXT,
                    tool_name TEXT NOT NULL,
                    turn INTEGER NOT NULL,
                    args_json TEXT,
                    payload_json TEXT NOT NULL,
                    char_count INTEGER NOT NULL,
                    summary TEXT,
                    summarize_status TEXT NOT NULL,
                    summarize_attempts INTEGER NOT NULL DEFAULT 0,
                    ok INTEGER NOT NULL,
                    cached INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    display_ref INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tool_results_user_created "
                "ON tool_results(user_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tool_results_expires "
                "ON tool_results(expires_at)"
            )
            self._migrate_display_ref(conn)
            self._migrate_payload_kind(conn)
            if owns_connection:                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    @staticmethod
    def new_ref() -> str:
        return f"tr_{secrets.token_hex(8)}"

    @staticmethod
    def _parse_ref_key(ref: str | int) -> tuple[str, str | int]:
        if isinstance(ref, bool):
            raise ValueError("invalid ref")
        if isinstance(ref, int):
            return ("display", ref)
        text = str(ref).strip()
        if not text:
            raise ValueError("empty ref")
        if text.startswith("tr_"):
            return ("hex", text)
        if text.isdigit():
            return ("display", int(text))
        return ("hex", text)

    def _migrate_display_ref(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(tool_results)")}
        if "display_ref" not in cols:
            conn.execute("ALTER TABLE tool_results ADD COLUMN display_ref INTEGER")
        self._backfill_display_refs(conn)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_results_user_display_ref "
            "ON tool_results(user_id, display_ref)"
        )

    @staticmethod
    def _migrate_payload_kind(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(tool_results)")}
        if "payload_kind" not in cols:
            conn.execute(
                "ALTER TABLE tool_results ADD COLUMN payload_kind TEXT NOT NULL DEFAULT 'unknown_legacy'"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_results_created_ref "
            "ON tool_results(created_at, ref)"
        )
    @staticmethod
    def _backfill_display_refs(conn: sqlite3.Connection) -> None:
        users = conn.execute("SELECT DISTINCT user_id FROM tool_results").fetchall()
        for row in users:
            user_id = row["user_id"]
            max_row = conn.execute(
                "SELECT COALESCE(MAX(display_ref), 0) AS max_ref "
                "FROM tool_results WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            next_ref = int(max_row["max_ref"]) + 1
            pending = conn.execute(
                """
                SELECT ref FROM tool_results
                WHERE user_id = ? AND display_ref IS NULL
                ORDER BY created_at ASC, ref ASC
                """,
                (user_id,),
            ).fetchall()
            for pending_row in pending:
                conn.execute(
                    "UPDATE tool_results SET display_ref = ? WHERE ref = ?",
                    (next_ref, pending_row["ref"]),
                )
                next_ref += 1

    def insert(
        self,
        *,
        user_id: int,
        run_id: str | None,
        tool_name: str,
        turn: int,
        args_json: str | None,
        payload_json: str,
        ok: bool,
        cached: bool,
        payload_kind: str = "result",
    ) -> str:
        ref = self.new_ref()
        now = datetime.now(timezone.utc)
        expires_at = tool_result_expires_at(now=now)
        with self._connect() as conn:
            next_row = conn.execute(
                "SELECT COALESCE(MAX(display_ref), 0) + 1 AS next "
                "FROM tool_results WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            display_ref = int(next_row["next"])
            conn.execute(
                """
                INSERT INTO tool_results (
                    ref, user_id, run_id, tool_name, turn, args_json, payload_json,
                    char_count, summary, summarize_status, summarize_attempts,
                    ok, cached, created_at, expires_at, display_ref, payload_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'pending', 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ref,
                    user_id,
                    run_id,
                    tool_name,
                    turn,
                    args_json,
                    payload_json,
                    len(payload_json),
                    int(ok),
                    int(cached),
                    now.isoformat(),
                    expires_at.isoformat(),
                    display_ref,
                    payload_kind,
                ),
            )
            conn.commit()
        self._notify_inserted(user_id=user_id, ref=ref)
        return ref
    def get_by_ref(self, ref: str) -> StoredToolResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tool_results WHERE ref = ?",
                (ref,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get(self, ref: str | int, *, user_id: int) -> StoredToolResult | None:
        kind, key = self._parse_ref_key(ref)
        with self._connect() as conn:
            if kind == "display":
                row = conn.execute(
                    "SELECT * FROM tool_results WHERE user_id = ? AND display_ref = ?",
                    (user_id, key),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM tool_results WHERE ref = ? AND user_id = ?",
                    (key, user_id),
                ).fetchone()
        if row is None:
            return None
        record = self._row_to_record(row)
        if tool_results_expire_enabled() and record.expires_at <= datetime.now(timezone.utc):
            self.delete_ref(record.ref)
            return None
        return record

    def get_by_ref_for_user(self, ref: str, *, user_id: int) -> StoredToolResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tool_results WHERE ref = ? AND user_id = ?",
                (ref, user_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def scan_head(self) -> ToolCursor:
        from memory.ingestion.models import ToolCursor

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT created_at, ref
                FROM tool_results
                ORDER BY created_at DESC, ref DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return ToolCursor(created_at="", ref="")
        return ToolCursor(created_at=str(row["created_at"]), ref=str(row["ref"]))

    def read_after(self, cursor: ToolCursor, *, limit: int) -> list[StoredToolResult]:
        capped = max(1, min(int(limit), 1000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tool_results
                WHERE created_at > ?
                   OR (created_at = ? AND ref > ?)
                ORDER BY created_at ASC, ref ASC
                LIMIT ?
                """,
                (cursor.created_at, cursor.created_at, cursor.ref, capped),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def existing_refs(self, items: Sequence[tuple[int, str]]) -> set[tuple[int, str]]:
        if not items:
            return set()
        existing: set[tuple[int, str]] = set()
        with self._connect() as conn:
            for user_id, ref in items:
                row = conn.execute(
                    "SELECT 1 FROM tool_results WHERE user_id = ? AND ref = ?",
                    (user_id, ref),
                ).fetchone()
                if row is not None:
                    existing.add((user_id, ref))
        return existing

    def list_summarized(self, user_id: int) -> list[StoredToolResult]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tool_results
                WHERE user_id = ?
                  AND summarize_status = 'ok'
                  AND summary IS NOT NULL
                  AND summary != ''
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        now = datetime.now(timezone.utc)
        records: list[StoredToolResult] = []
        expire_enabled = tool_results_expire_enabled()
        for row in rows:
            record = self._row_to_record(row)
            if expire_enabled and record.expires_at <= now:
                continue
            records.append(record)
        return records

    def list_all_for_user(self, user_id: int) -> list[StoredToolResult]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tool_results
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def delete_ref(self, ref: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, ref FROM tool_results WHERE ref = ?",
                (ref,),
            ).fetchone()
            cursor = conn.execute("DELETE FROM tool_results WHERE ref = ?", (ref,))
            conn.commit()
            deleted = cursor.rowcount > 0
        if deleted and row is not None:
            self._notify_deleted([(int(row["user_id"]), str(row["ref"]))], reason="delete_ref")
        return deleted

    def purge_expired(self, *, now: datetime | None = None) -> int:
        if not tool_results_expire_enabled():
            return 0
        cutoff = (now or datetime.now(timezone.utc)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id, ref FROM tool_results WHERE expires_at <= ?",
                (cutoff,),
            ).fetchall()
            cursor = conn.execute(
                "DELETE FROM tool_results WHERE expires_at <= ?",
                (cutoff,),
            )
            conn.commit()
            deleted = cursor.rowcount
        self._notify_deleted(
            [(int(row["user_id"]), str(row["ref"])) for row in rows],
            reason="ttl_purge",
        )
        return deleted
    def enforce_user_row_caps(self, max_rows_per_user: int) -> int:
        if max_rows_per_user <= 0:
            return 0
        deleted = 0
        tombstones: list[tuple[int, str]] = []
        with self._connect() as conn:
            users = conn.execute(
                "SELECT user_id FROM tool_results GROUP BY user_id HAVING COUNT(*) > ?",
                (max_rows_per_user,),
            ).fetchall()
            for row in users:
                user_id = row["user_id"]
                overflow = conn.execute(
                    """
                    SELECT ref FROM tool_results
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT -1 OFFSET ?
                    """,
                    (user_id, max_rows_per_user),
                ).fetchall()
                refs = [item["ref"] for item in overflow]
                if not refs:
                    continue
                placeholders = ",".join("?" for _ in refs)
                cursor = conn.execute(
                    f"DELETE FROM tool_results WHERE ref IN ({placeholders})",
                    refs,
                )
                deleted += cursor.rowcount
                tombstones.extend((int(user_id), str(ref)) for ref in refs)
            conn.commit()
        self._notify_deleted(tombstones, reason="row_cap_eviction")
        return deleted
    def user_archive_stats(self, user_id: int) -> dict[str, int]:
        detailed = self.user_archive_stats_detailed(user_id, top_tools=0)
        return {
            "row_count": detailed["row_count"],
            "byte_count": detailed["byte_count"],
        }

    def user_archive_stats_detailed(
        self,
        user_id: int,
        *,
        top_tools: int = 5,
    ) -> dict[str, int | list[tuple[str, int]]]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            summary = conn.execute(
                """
                SELECT
                    COUNT(*) AS row_count,
                    COALESCE(SUM(char_count), 0) AS byte_count,
                    COALESCE(SUM(CASE WHEN summarize_status = 'ok' THEN 1 ELSE 0 END), 0)
                        AS summarize_ok,
                    COALESCE(SUM(CASE WHEN summarize_status = 'pending' THEN 1 ELSE 0 END), 0)
                        AS summarize_pending,
                    COALESCE(SUM(CASE WHEN summarize_status = 'failed' THEN 1 ELSE 0 END), 0)
                        AS summarize_failed,
                    COALESCE(SUM(CASE WHEN expires_at <= ? THEN 1 ELSE 0 END), 0)
                        AS expired_pending
                FROM tool_results
                WHERE user_id = ?
                """,
                (now, user_id),
            ).fetchone()
            top: list[tuple[str, int]] = []
            if top_tools > 0:
                rows = conn.execute(
                    """
                    SELECT tool_name, COUNT(*) AS cnt
                    FROM tool_results
                    WHERE user_id = ?
                    GROUP BY tool_name
                    ORDER BY cnt DESC, tool_name ASC
                    LIMIT ?
                    """,
                    (user_id, top_tools),
                ).fetchall()
                top = [(row["tool_name"], int(row["cnt"])) for row in rows]
        if summary is None:
            return {
                "row_count": 0,
                "byte_count": 0,
                "summarize_ok": 0,
                "summarize_pending": 0,
                "summarize_failed": 0,
                "expired_pending": 0,
                "top_tools": top,
            }
        return {
            "row_count": int(summary["row_count"]),
            "byte_count": int(summary["byte_count"]),
            "summarize_ok": int(summary["summarize_ok"]),
            "summarize_pending": int(summary["summarize_pending"]),
            "summarize_failed": int(summary["summarize_failed"]),
            "expired_pending": int(summary["expired_pending"]),
            "top_tools": top,
        }

    def global_archive_stats(self) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS row_count,
                    COALESCE(SUM(char_count), 0) AS byte_count,
                    COUNT(DISTINCT user_id) AS user_count,
                    COALESCE(SUM(CASE WHEN summarize_status = 'ok' THEN 1 ELSE 0 END), 0)
                        AS summarize_ok,
                    COALESCE(SUM(CASE WHEN summarize_status = 'pending' THEN 1 ELSE 0 END), 0)
                        AS summarize_pending,
                    COALESCE(SUM(CASE WHEN summarize_status = 'failed' THEN 1 ELSE 0 END), 0)
                        AS summarize_failed
                FROM tool_results
                """
            ).fetchone()
        if row is None:
            return {
                "row_count": 0,
                "byte_count": 0,
                "user_count": 0,
                "summarize_ok": 0,
                "summarize_pending": 0,
                "summarize_failed": 0,
            }
        return {
            "row_count": int(row["row_count"]),
            "byte_count": int(row["byte_count"]),
            "user_count": int(row["user_count"]),
            "summarize_ok": int(row["summarize_ok"]),
            "summarize_pending": int(row["summarize_pending"]),
            "summarize_failed": int(row["summarize_failed"]),
        }

    def update_summary(
        self,
        ref: str,
        *,
        summary: str | None,
        summarize_status: str,
        summarize_attempts: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tool_results
                SET summary = ?, summarize_status = ?, summarize_attempts = ?
                WHERE ref = ?
                """,
                (summary, summarize_status, summarize_attempts, ref),
            )
            conn.commit()

    def delete_for_user(self, user_id: int) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ref FROM tool_results WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            cursor = conn.execute(
                "DELETE FROM tool_results WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()
            deleted = cursor.rowcount
        self._notify_deleted(
            [(user_id, str(row["ref"])) for row in rows],
            reason="delete_for_user",
        )
        return deleted

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> StoredToolResult:
        display_ref = row["display_ref"]
        if display_ref is None:
            raise RuntimeError(f"tool result {row['ref']} missing display_ref")
        keys = row.keys()
        payload_kind = str(row["payload_kind"]) if "payload_kind" in keys else "unknown_legacy"
        return StoredToolResult(
            ref=row["ref"],
            display_ref=int(display_ref),
            user_id=row["user_id"],
            run_id=row["run_id"],
            tool_name=row["tool_name"],
            turn=row["turn"],
            payload_kind=payload_kind,
            args_json=row["args_json"],
            payload_json=row["payload_json"],
            char_count=row["char_count"],
            summary=row["summary"],
            summarize_status=row["summarize_status"],
            summarize_attempts=row["summarize_attempts"],
            ok=bool(row["ok"]),
            cached=bool(row["cached"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
        )

def get_tool_result_store() -> ToolResultStore:
    global _store
    if _store is None:
        _store = ToolResultStore()
    return _store


def reset_tool_result_store(store: ToolResultStore | None = None) -> None:
    global _store
    _store = store
