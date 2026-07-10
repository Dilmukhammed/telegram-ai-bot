from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Literal

from bot.chat_store.models import ChatSession, SessionStatus, SummaryStatus
from bot.chat_store.schema import parse_dt, utc_now_iso

ArchiveReason = Literal["reset", "start", "new_chat", "migration"]


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def row_to_session(row: sqlite3.Row) -> ChatSession:
    return ChatSession(
        session_id=row["session_id"],
        user_id=int(row["user_id"]),
        status=row["status"],
        summary=row["summary"],
        summary_status=row["summary_status"],
        title=row["title"],
        message_count=int(row["message_count"]),
        created_at=parse_dt(row["created_at"]) or datetime.fromisoformat(row["created_at"]),
        started_at=parse_dt(row["started_at"]),
        last_message_at=parse_dt(row["last_message_at"]),
        updated_at=parse_dt(row["updated_at"]) or datetime.fromisoformat(row["updated_at"]),
        archived_at=parse_dt(row["archived_at"]),
        summary_started_at=parse_dt(row["summary_started_at"]),
        summary_completed_at=parse_dt(row["summary_completed_at"]),
        metadata=_parse_metadata(row["metadata_json"]),
    )


def get_active_session(conn: sqlite3.Connection, user_id: int) -> ChatSession | None:
    row = conn.execute(
        """
        SELECT * FROM chat_sessions
        WHERE user_id = ? AND status = 'active'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return row_to_session(row)


def create_active_session(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    opened_by: str = "first_message",
    metadata: dict[str, Any] | None = None,
) -> ChatSession:
    now = utc_now_iso()
    session_id = uuid.uuid4().hex
    meta = {"opened_by": opened_by}
    if metadata:
        meta.update(metadata)
    conn.execute(
        """
        INSERT INTO chat_sessions (
            session_id, user_id, status, summary, summary_status, title,
            message_count, created_at, started_at, last_message_at, updated_at,
            archived_at, summary_started_at, summary_completed_at, metadata_json
        )
        VALUES (?, ?, 'active', NULL, NULL, NULL, 0, ?, NULL, NULL, ?, NULL, NULL, NULL, ?)
        """,
        (session_id, user_id, now, now, json.dumps(meta, ensure_ascii=False)),
    )
    row = conn.execute(
        "SELECT * FROM chat_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    assert row is not None
    return row_to_session(row)


def get_or_create_active_session(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    opened_by: str = "first_message",
    metadata: dict[str, Any] | None = None,
) -> ChatSession:
    existing = get_active_session(conn, user_id)
    if existing is not None:
        return existing
    return create_active_session(
        conn,
        user_id,
        opened_by=opened_by,
        metadata=metadata,
    )


def archive_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    closed_by: ArchiveReason,
    metadata_patch: dict[str, Any] | None = None,
) -> ChatSession | None:
    row = conn.execute(
        "SELECT * FROM chat_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    if row["status"] == "archived":
        return row_to_session(row)

    now = utc_now_iso()
    metadata = _parse_metadata(row["metadata_json"])
    metadata["closed_by"] = closed_by
    if metadata_patch:
        metadata.update(metadata_patch)

    conn.execute(
        """
        UPDATE chat_sessions
        SET status = 'archived',
            archived_at = ?,
            updated_at = ?,
            summary_status = COALESCE(summary_status, 'pending'),
            metadata_json = ?
        WHERE session_id = ?
        """,
        (now, now, json.dumps(metadata, ensure_ascii=False), session_id),
    )
    updated = conn.execute(
        "SELECT * FROM chat_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    assert updated is not None
    return row_to_session(updated)


def archive_active_session(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    closed_by: ArchiveReason,
    metadata_patch: dict[str, Any] | None = None,
) -> ChatSession | None:
    active = get_active_session(conn, user_id)
    if active is None:
        return None
    return archive_session(
        conn,
        active.session_id,
        closed_by=closed_by,
        metadata_patch=metadata_patch,
    )


def archive_and_create_active(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    closed_by: ArchiveReason,
    metadata_patch: dict[str, Any] | None = None,
    opened_by: str = "archive_reset",
) -> tuple[ChatSession | None, ChatSession]:
    archived = archive_active_session(
        conn,
        user_id,
        closed_by=closed_by,
        metadata_patch=metadata_patch,
    )
    created = create_active_session(conn, user_id, opened_by=opened_by)
    return archived, created


def get_session_for_user(
    conn: sqlite3.Connection,
    session_id: str,
    user_id: int,
) -> ChatSession | None:
    row = conn.execute(
        """
        SELECT * FROM chat_sessions
        WHERE session_id = ? AND user_id = ?
        """,
        (session_id, user_id),
    ).fetchone()
    if row is None:
        return None
    return row_to_session(row)


def list_sessions(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    status: SessionStatus | None = None,
    limit: int = 50,
) -> list[ChatSession]:
    if status is None:
        rows = conn.execute(
            """
            SELECT * FROM chat_sessions
            WHERE user_id = ?
            ORDER BY COALESCE(last_message_at, created_at) DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM chat_sessions
            WHERE user_id = ? AND status = ?
            ORDER BY COALESCE(last_message_at, created_at) DESC
            LIMIT ?
            """,
            (user_id, status, limit),
        ).fetchall()
    return [row_to_session(row) for row in rows]


def update_session_summary_status(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    summary_status: SummaryStatus,
    summary_started_at: datetime | None = None,
    summary_completed_at: datetime | None = None,
) -> ChatSession | None:
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE chat_sessions
        SET title = COALESCE(?, title),
            summary = COALESCE(?, summary),
            summary_status = ?,
            summary_started_at = COALESCE(?, summary_started_at),
            summary_completed_at = COALESCE(?, summary_completed_at),
            updated_at = ?
        WHERE session_id = ?
        """,
        (
            title,
            summary,
            summary_status,
            summary_started_at.isoformat() if summary_started_at else None,
            summary_completed_at.isoformat() if summary_completed_at else None,
            now,
            session_id,
        ),
    )
    row = conn.execute(
        "SELECT * FROM chat_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return row_to_session(row)
