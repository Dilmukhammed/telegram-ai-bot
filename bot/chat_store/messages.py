from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from bot.chat_store.encode import message_to_row_fields, row_to_message_dict
from bot.chat_store.models import ChatMessage
from bot.chat_store.schema import parse_dt, utc_now_iso


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def row_to_message(row: sqlite3.Row) -> ChatMessage:
    return ChatMessage(
        message_id=int(row["message_id"]),
        session_id=row["session_id"],
        user_id=int(row["user_id"]),
        seq=int(row["seq"]),
        role=row["role"],
        content=row["content"],
        content_type=row["content_type"],
        tool_call_id=row["tool_call_id"],
        tool_name=row["tool_name"],
        source_at=parse_dt(row["source_at"]) or datetime.now(timezone.utc),
        created_at=parse_dt(row["created_at"]) or datetime.now(timezone.utc),
        metadata=_parse_metadata(row["metadata_json"]),
    )


def _next_seq(conn: sqlite3.Connection, session_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM chat_messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["max_seq"]) + 1


def _normalize_source_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def append_messages(
    conn: sqlite3.Connection,
    session_id: str,
    user_id: int,
    messages: list[dict[str, Any]],
    *,
    default_source_at: datetime | None = None,
    source_at_for_message: list[datetime | None] | None = None,
    metadata_for_message: list[dict[str, Any] | None] | None = None,
) -> list[int]:
    if not messages:
        return []

    seq = _next_seq(conn, session_id)
    created_at = utc_now_iso()
    default_source = _normalize_source_at(default_source_at)
    inserted_ids: list[int] = []
    last_source_at: datetime | None = None
    first_user_source_at: datetime | None = None

    for index, message in enumerate(messages):
        per_source = None
        if source_at_for_message and index < len(source_at_for_message):
            per_source = source_at_for_message[index]
        source_at = _normalize_source_at(per_source or default_source)
        last_source_at = source_at
        if message.get("role") == "user" and first_user_source_at is None:
            first_user_source_at = source_at

        extra_meta = None
        if metadata_for_message and index < len(metadata_for_message):
            extra_meta = metadata_for_message[index]
        fields = message_to_row_fields(message, metadata_extra=extra_meta)

        cursor = conn.execute(
            """
            INSERT INTO chat_messages (
                session_id, user_id, seq, role, content, content_type,
                tool_call_id, tool_name, source_at, created_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id,
                seq,
                fields["role"],
                fields["content"],
                fields["content_type"],
                fields["tool_call_id"],
                fields["tool_name"],
                source_at.isoformat(),
                created_at,
                fields["metadata_json"],
            ),
        )
        inserted_ids.append(int(cursor.lastrowid))
        seq += 1

    session_row = conn.execute(
        "SELECT started_at, message_count FROM chat_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    assert session_row is not None

    started_at = session_row["started_at"]
    if started_at is None and first_user_source_at is not None:
        started_at = first_user_source_at.isoformat()

    conn.execute(
        """
        UPDATE chat_sessions
        SET message_count = message_count + ?,
            started_at = COALESCE(?, started_at),
            last_message_at = ?,
            updated_at = ?
        WHERE session_id = ?
        """,
        (
            len(messages),
            started_at,
            last_source_at.isoformat() if last_source_at else None,
            created_at,
            session_id,
        ),
    )
    return inserted_ids


def read_range(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    from_seq: int = 1,
    limit: int | None = None,
) -> list[ChatMessage]:
    if limit is None:
        rows = conn.execute(
            """
            SELECT * FROM chat_messages
            WHERE session_id = ? AND seq >= ?
            ORDER BY seq ASC
            """,
            (session_id, from_seq),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM chat_messages
            WHERE session_id = ? AND seq >= ?
            ORDER BY seq ASC
            LIMIT ?
            """,
            (session_id, from_seq, limit),
        ).fetchall()
    return [row_to_message(row) for row in rows]


def read_all_messages(conn: sqlite3.Connection, session_id: str) -> list[ChatMessage]:
    return read_range(conn, session_id, from_seq=1)


def read_message_dicts(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    from_seq: int = 1,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    return [
        row_to_message_dict(message)
        for message in read_range(conn, session_id, from_seq=from_seq, limit=limit)
    ]


def get_message_by_id(conn: sqlite3.Connection, message_id: int) -> ChatMessage | None:
    row = conn.execute(
        "SELECT * FROM chat_messages WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    if row is None:
        return None
    return row_to_message(row)


def find_message_by_telegram_id(
    conn: sqlite3.Connection,
    user_id: int,
    telegram_message_id: int,
) -> ChatMessage | None:
    row = conn.execute(
        """
        SELECT * FROM chat_messages
        WHERE user_id = ?
          AND CAST(json_extract(metadata_json, '$.telegram_message_id') AS INTEGER) = ?
        ORDER BY message_id DESC
        LIMIT 1
        """,
        (user_id, int(telegram_message_id)),
    ).fetchone()
    if row is None:
        return None
    return row_to_message(row)


def get_message_for_user(
    conn: sqlite3.Connection,
    message_id: int,
    user_id: int,
) -> ChatMessage | None:
    row = conn.execute(
        """
        SELECT * FROM chat_messages
        WHERE message_id = ? AND user_id = ?
        """,
        (message_id, user_id),
    ).fetchone()
    if row is None:
        return None
    return row_to_message(row)


def max_message_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(message_id), 0) AS max_id FROM chat_messages").fetchone()
    return int(row["max_id"])


def read_messages_after_id(
    conn: sqlite3.Connection,
    message_id: int,
    *,
    limit: int,
) -> list[ChatMessage]:
    capped = max(1, min(int(limit), 1000))
    rows = conn.execute(
        """
        SELECT * FROM chat_messages
        WHERE message_id > ?
        ORDER BY message_id ASC
        LIMIT ?
        """,
        (message_id, capped),
    ).fetchall()
    return [row_to_message(row) for row in rows]


def search_messages(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    query: str,
    session_id: str | None = None,
    limit: int = 20,
    use_regex: bool = False,
    scan_limit: int = 2000,
) -> list[ChatMessage]:
    text = query.strip()
    if not text:
        return []

    capped_limit = max(1, min(int(limit), 100))
    capped_scan = max(capped_limit, min(int(scan_limit), 5000))

    if session_id is not None:
        rows = conn.execute(
            """
            SELECT * FROM chat_messages
            WHERE user_id = ? AND session_id = ?
            ORDER BY seq DESC
            LIMIT ?
            """,
            (user_id, session_id, capped_scan),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM chat_messages
            WHERE user_id = ?
            ORDER BY source_at DESC, message_id DESC
            LIMIT ?
            """,
            (user_id, capped_scan),
        ).fetchall()

    pattern: re.Pattern[str] | None = None
    if use_regex:
        try:
            pattern = re.compile(text, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"Invalid regex: {exc}") from exc
    else:
        needle = text.casefold()

    matches: list[ChatMessage] = []
    for row in rows:
        message = row_to_message(row)
        haystack = message.content or ""
        if use_regex:
            assert pattern is not None
            if not pattern.search(haystack):
                continue
        elif needle not in haystack.casefold():
            continue
        matches.append(message)
        if len(matches) >= capped_limit:
            break

    if session_id is not None:
        matches.sort(key=lambda item: item.seq)
    else:
        matches.sort(key=lambda item: (item.source_at, item.message_id), reverse=True)
    return matches


def get_last_user_source_at(conn: sqlite3.Connection, session_id: str) -> datetime | None:
    row = conn.execute(
        """
        SELECT source_at FROM chat_messages
        WHERE session_id = ? AND role = 'user'
        ORDER BY seq DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return parse_dt(row["source_at"])
