from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from bot.chat_store import messages as message_ops
from bot.chat_store.schema import parse_dt, utc_now_iso
from bot.chat_store.store import ChatStore
from config import Settings, get_settings

logger = logging.getLogger(__name__)

META_KEY_V1_IMPORT = "history_v1_import"
MigrateTarget = Literal["active", "archived"]


@dataclass(frozen=True)
class V1MigrationResult:
    applied: bool
    users_seen: int = 0
    users_migrated: int = 0
    users_skipped: int = 0
    messages_migrated: int = 0
    backup_path: str | None = None
    reason: str = ""
    errors: tuple[str, ...] = field(default_factory=tuple)


def _meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM chat_store_meta WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    return row["value"]


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
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


def migration_already_applied(store: ChatStore) -> bool:
    with store._connect() as conn:
        return _meta_get(conn, META_KEY_V1_IMPORT) is not None


def seed_v1_history_db(
    db_path: str | Path,
    user_id: int,
    messages: list[dict[str, Any]],
    *,
    last_message_at: datetime | None = None,
) -> None:
    """Write one v1 `chat_history` row (migration source fixture / legacy import only)."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = utc_now_iso()
    last_at = None
    if last_message_at is not None:
        if last_message_at.tzinfo is None:
            last_message_at = last_message_at.replace(tzinfo=timezone.utc)
        last_at = last_message_at.astimezone(timezone.utc).isoformat()
    payload = json.dumps(messages, ensure_ascii=False, default=str)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                user_id INTEGER PRIMARY KEY,
                messages_json TEXT NOT NULL,
                last_message_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO chat_history (user_id, messages_json, last_message_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                messages_json = excluded.messages_json,
                last_message_at = excluded.last_message_at,
                updated_at = excluded.updated_at
            """,
            (user_id, payload, last_at, now),
        )
        conn.commit()
    finally:
        conn.close()


def _load_v1_rows(source_path: Path) -> list[sqlite3.Row]:
    if not source_path.is_file():
        return []
    conn = sqlite3.connect(source_path)
    conn.row_factory = sqlite3.Row
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_history'"
        ).fetchone()
        if table is None:
            return []
        return conn.execute(
            "SELECT user_id, messages_json, last_message_at, updated_at FROM chat_history"
        ).fetchall()
    finally:
        conn.close()


def _user_has_v2_sessions(conn: sqlite3.Connection, user_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM chat_sessions WHERE user_id = ? LIMIT 1",
        (user_id,),
    ).fetchone()
    return row is not None


def _parse_messages(raw_json: str) -> list[dict[str, Any]] | None:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    return [item for item in payload if isinstance(item, dict)]


def _anchor_time(
    *,
    last_message_at: str | None,
    updated_at: str | None,
) -> datetime:
    for raw in (last_message_at, updated_at):
        parsed = parse_dt(raw)
        if parsed is not None:
            return parsed
    return datetime.now(timezone.utc)


def _synthetic_message_times(count: int, *, anchor: datetime) -> list[datetime]:
    if count <= 0:
        return []
    if count == 1:
        return [anchor]
    start = anchor - timedelta(seconds=max(1, count - 1))
    span = (anchor - start).total_seconds()
    step_seconds = span / max(1, count - 1)
    return [start + timedelta(seconds=step_seconds * index) for index in range(count)]


def _insert_imported_session(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    status: MigrateTarget,
    created_at: datetime,
    started_at: datetime | None,
    last_message_at: datetime | None,
    updated_at: datetime,
    archived_at: datetime | None,
    metadata: dict[str, Any],
) -> str:
    session_id = uuid.uuid4().hex
    summary_status = None
    conn.execute(
        """
        INSERT INTO chat_sessions (
            session_id, user_id, status, summary, summary_status, title,
            message_count, created_at, started_at, last_message_at, updated_at,
            archived_at, summary_started_at, summary_completed_at, metadata_json
        )
        VALUES (?, ?, ?, NULL, ?, NULL, 0, ?, ?, ?, ?, ?, NULL, NULL, ?)
        """,
        (
            session_id,
            user_id,
            status,
            summary_status,
            created_at.isoformat(),
            started_at.isoformat() if started_at else None,
            last_message_at.isoformat() if last_message_at else None,
            updated_at.isoformat(),
            archived_at.isoformat() if archived_at else None,
            json.dumps(metadata, ensure_ascii=False),
        ),
    )
    return session_id


def _migrate_user_row(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    messages: list[dict[str, Any]],
    last_message_at: str | None,
    updated_at: str | None,
    target: MigrateTarget,
) -> int:
    anchor = _anchor_time(last_message_at=last_message_at, updated_at=updated_at)
    times = _synthetic_message_times(len(messages), anchor=anchor)
    meta = {
        "opened_by": "v1_migration",
        "migrated_from": "chat_history_v1",
        "v1_updated_at": updated_at,
    }
    created_at = parse_dt(updated_at) or anchor
    started_at = times[0] if times else None
    last_at = times[-1] if times else anchor

    if target == "active":
        session_id = _insert_imported_session(
            conn,
            user_id=user_id,
            status="active",
            created_at=created_at,
            started_at=started_at,
            last_message_at=last_at,
            updated_at=created_at,
            archived_at=None,
            metadata=meta,
        )
    else:
        session_id = _insert_imported_session(
            conn,
            user_id=user_id,
            status="archived",
            created_at=created_at,
            started_at=started_at,
            last_message_at=last_at,
            updated_at=created_at,
            archived_at=created_at,
            metadata={**meta, "closed_by": "migration"},
        )

    per_message_meta = [{"migrated_from": "chat_history_v1"} for _ in messages]
    message_ops.append_messages(
        conn,
        session_id,
        user_id,
        messages,
        source_at_for_message=times,
        metadata_for_message=per_message_meta,
    )

    if target == "archived":
        from bot.chat_store import sessions as session_ops

        session_ops.create_active_session(
            conn,
            user_id,
            opened_by="v1_migration",
            metadata={"opened_by": "v1_migration", "after_v1_import": True},
        )

    return len(messages)


def migrate_v1_history(
    store: ChatStore | None = None,
    *,
    settings: Settings | None = None,
    source_db_path: str | None = None,
    target: MigrateTarget | None = None,
    backup: bool | None = None,
    force: bool = False,
) -> V1MigrationResult:
    settings = settings or get_settings()
    store = store or ChatStore(db_path=settings.chat_db_path)
    target = target or settings.chat_migrate_v1_target  # type: ignore[assignment]
    if target not in {"active", "archived"}:
        return V1MigrationResult(
            applied=False,
            reason=f"invalid target: {target}",
        )

    source_path = Path(source_db_path or settings.chat_migrate_v1_source_path)
    if source_path == Path(":memory:"):
        return V1MigrationResult(applied=False, reason="v1 source is :memory:")

    with store._connect() as conn:
        if not force and _meta_get(conn, META_KEY_V1_IMPORT) is not None:
            return V1MigrationResult(applied=False, reason="already migrated")

    rows = _load_v1_rows(source_path)
    if not rows:
        with store._connect() as conn:
            _meta_set(
                conn,
                META_KEY_V1_IMPORT,
                json.dumps(
                    {
                        "applied_at": utc_now_iso(),
                        "users_seen": 0,
                        "users_migrated": 0,
                        "messages_migrated": 0,
                        "reason": "no v1 rows",
                    },
                    ensure_ascii=False,
                ),
            )
            conn.commit()
        return V1MigrationResult(applied=True, reason="no v1 rows")

    do_backup = settings.chat_migrate_v1_backup if backup is None else backup
    backup_path: str | None = None
    if do_backup and source_path.is_file():
        backup_file = source_path.with_suffix(source_path.suffix + ".bak")
        shutil.copy2(source_path, backup_file)
        backup_path = str(backup_file)
        logger.info("chat_v1_migration backup=%s", backup_path)

    users_seen = 0
    users_migrated = 0
    users_skipped = 0
    messages_migrated = 0
    errors: list[str] = []

    with store._connect() as conn:
        for row in rows:
            users_seen += 1
            user_id = int(row["user_id"])
            if _user_has_v2_sessions(conn, user_id):
                users_skipped += 1
                continue
            messages = _parse_messages(row["messages_json"])
            if messages is None:
                errors.append(f"user_id={user_id}: invalid messages_json")
                users_skipped += 1
                continue
            if not messages:
                users_skipped += 1
                continue
            try:
                count = _migrate_user_row(
                    conn,
                    user_id=user_id,
                    messages=messages,
                    last_message_at=row["last_message_at"],
                    updated_at=row["updated_at"],
                    target=target,
                )
            except Exception as exc:
                errors.append(f"user_id={user_id}: {exc}")
                users_skipped += 1
                continue
            users_migrated += 1
            messages_migrated += count

        _meta_set(
            conn,
            META_KEY_V1_IMPORT,
            json.dumps(
                {
                    "applied_at": utc_now_iso(),
                    "source_db": str(source_path),
                    "target": target,
                    "users_seen": users_seen,
                    "users_migrated": users_migrated,
                    "users_skipped": users_skipped,
                    "messages_migrated": messages_migrated,
                    "backup_path": backup_path,
                    "errors": errors,
                },
                ensure_ascii=False,
            ),
        )
        conn.commit()

    logger.info(
        "chat_v1_migration done users_migrated=%s messages_migrated=%s skipped=%s target=%s",
        users_migrated,
        messages_migrated,
        users_skipped,
        target,
    )
    return V1MigrationResult(
        applied=True,
        users_seen=users_seen,
        users_migrated=users_migrated,
        users_skipped=users_skipped,
        messages_migrated=messages_migrated,
        backup_path=backup_path,
        reason="ok",
        errors=tuple(errors),
    )


def run_v1_migration_if_needed(
    store: ChatStore | None = None,
    *,
    settings: Settings | None = None,
) -> V1MigrationResult:
    settings = settings or get_settings()
    if not settings.chat_migrate_v1_on_startup:
        return V1MigrationResult(applied=False, reason="disabled")
    store = store or ChatStore(db_path=settings.chat_db_path)
    if migration_already_applied(store):
        return V1MigrationResult(applied=False, reason="already migrated")
    return migrate_v1_history(store, settings=settings)


def verify_v1_migration(
    store: ChatStore,
    *,
    source_db_path: str,
) -> dict[str, Any]:
    source_rows = _load_v1_rows(Path(source_db_path))
    mismatches: list[str] = []
    checked = 0
    with store._connect() as conn:
        for row in source_rows:
            user_id = int(row["user_id"])
            messages = _parse_messages(row["messages_json"]) or []
            if not messages:
                continue
            session_row = conn.execute(
                """
                SELECT session_id, message_count FROM chat_sessions
                WHERE user_id = ? AND metadata_json LIKE '%chat_history_v1%'
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if session_row is None:
                mismatches.append(f"user_id={user_id}: missing imported session")
                continue
            db_count = conn.execute(
                "SELECT COUNT(*) AS count FROM chat_messages WHERE session_id = ?",
                (session_row["session_id"],),
            ).fetchone()
            checked += 1
            if int(db_count["count"]) != len(messages):
                mismatches.append(
                    f"user_id={user_id}: expected {len(messages)} messages, got {db_count['count']}"
                )
    return {
        "checked_users": checked,
        "mismatches": mismatches,
        "ok": not mismatches,
    }
