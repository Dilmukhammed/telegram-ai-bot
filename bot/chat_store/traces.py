from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from agent.run_trace import RunTrace
from bot.chat_store.models import ChatSessionTrace
from bot.chat_store.schema import parse_dt, utc_now_iso


def _normalize_source_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _next_turn_seq(conn: sqlite3.Connection, session_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(turn_seq), 0) AS max_seq FROM chat_session_traces WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["max_seq"]) + 1


def append_session_trace(
    conn: sqlite3.Connection,
    session_id: str,
    user_id: int,
    *,
    trace: RunTrace,
    assistant_reply: str,
    source_at: datetime | None = None,
) -> int:
    turn_seq = _next_turn_seq(conn, session_id)
    created_at = utc_now_iso()
    event_at = _normalize_source_at(source_at)
    cursor = conn.execute(
        """
        INSERT INTO chat_session_traces (
            session_id, user_id, turn_seq, user_message, assistant_reply,
            trace_json, source_at, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            user_id,
            turn_seq,
            trace.user_message,
            assistant_reply,
            json.dumps(trace.to_dict(), ensure_ascii=False),
            event_at.isoformat(),
            created_at,
        ),
    )
    return int(cursor.lastrowid)


def _row_to_trace(row: sqlite3.Row) -> ChatSessionTrace:
    return ChatSessionTrace(
        trace_row_id=int(row["trace_row_id"]),
        session_id=row["session_id"],
        user_id=int(row["user_id"]),
        turn_seq=int(row["turn_seq"]),
        user_message=row["user_message"],
        assistant_reply=row["assistant_reply"],
        trace=json.loads(row["trace_json"]),
        source_at=parse_dt(row["source_at"]) or datetime.now(timezone.utc),
        created_at=parse_dt(row["created_at"]) or datetime.now(timezone.utc),
    )


def list_session_traces(conn: sqlite3.Connection, session_id: str) -> list[ChatSessionTrace]:
    rows = conn.execute(
        """
        SELECT * FROM chat_session_traces
        WHERE session_id = ?
        ORDER BY turn_seq ASC
        """,
        (session_id,),
    ).fetchall()
    return [_row_to_trace(row) for row in rows]


def count_session_traces(conn: sqlite3.Connection, session_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM chat_session_traces WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["count"])
