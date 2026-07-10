from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = 5

_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id              TEXT PRIMARY KEY,
    user_id                 INTEGER NOT NULL,
    status                  TEXT NOT NULL,
    summary                 TEXT,
    summary_status          TEXT,
    title                   TEXT,
    message_count           INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT NOT NULL,
    started_at              TEXT,
    last_message_at         TEXT,
    updated_at              TEXT NOT NULL,
    archived_at             TEXT,
    summary_started_at      TEXT,
    summary_completed_at    TEXT,
    metadata_json           TEXT
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_status
    ON chat_sessions(user_id, status, last_message_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_started
    ON chat_sessions(user_id, started_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_sessions_one_active_per_user
    ON chat_sessions(user_id)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL REFERENCES chat_sessions(session_id),
    user_id             INTEGER NOT NULL,
    seq                 INTEGER NOT NULL,
    role                TEXT NOT NULL,
    content             TEXT,
    content_type        TEXT NOT NULL DEFAULT 'text',
    tool_call_id        TEXT,
    tool_name           TEXT,
    source_at           TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    metadata_json       TEXT,
    UNIQUE(session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_seq
    ON chat_messages(session_id, seq);

CREATE INDEX IF NOT EXISTS idx_chat_messages_user
    ON chat_messages(user_id, session_id);

CREATE INDEX IF NOT EXISTS idx_chat_messages_source_at
    ON chat_messages(user_id, source_at DESC);

CREATE TABLE IF NOT EXISTS chat_session_traces (
    trace_row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL REFERENCES chat_sessions(session_id),
    user_id             INTEGER NOT NULL,
    turn_seq            INTEGER NOT NULL,
    user_message        TEXT NOT NULL,
    assistant_reply     TEXT NOT NULL,
    trace_json          TEXT NOT NULL,
    source_at           TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE(session_id, turn_seq)
);

CREATE INDEX IF NOT EXISTS idx_chat_session_traces_session
    ON chat_session_traces(session_id, turn_seq);

CREATE TABLE IF NOT EXISTS chat_store_meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_search_chunks (
    chunk_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL,
    session_id          TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    source_key          TEXT NOT NULL,
    turn_number         INTEGER,
    seq_start           INTEGER,
    seq_end             INTEGER,
    tool_ref            INTEGER,
    chunk_index         INTEGER NOT NULL DEFAULT 0,
    text                TEXT NOT NULL,
    session_started_at  TEXT,
    session_title       TEXT,
    session_summary     TEXT,
    embedding_json      TEXT,
    indexed_at          TEXT NOT NULL,
    UNIQUE(user_id, source_type, source_key, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chat_search_chunks_user_session
    ON chat_search_chunks(user_id, session_id);

CREATE INDEX IF NOT EXISTS idx_chat_search_chunks_user_started
    ON chat_search_chunks(user_id, session_started_at DESC);

CREATE TABLE IF NOT EXISTS chat_period_summaries (
    period_id               TEXT PRIMARY KEY,
    user_id                 INTEGER NOT NULL,
    period_type             TEXT NOT NULL,
    period_key              TEXT NOT NULL,
    title                   TEXT,
    summary                 TEXT,
    summary_status          TEXT,
    session_count           INTEGER NOT NULL DEFAULT 0,
    source_session_ids_json TEXT,
    coverage_start          TEXT,
    coverage_end            TEXT,
    summary_started_at      TEXT,
    summary_completed_at    TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    metadata_json           TEXT,
    UNIQUE(user_id, period_type, period_key)
);

CREATE INDEX IF NOT EXISTS idx_chat_period_summaries_user_type
    ON chat_period_summaries(user_id, period_type, period_key DESC);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    row = conn.execute(
        "SELECT MAX(version) AS version FROM schema_migrations"
    ).fetchone()
    current = int(row["version"]) if row and row["version"] is not None else 0
    if current >= SCHEMA_VERSION:
        return
    for version in range(current + 1, SCHEMA_VERSION + 1):
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, utc_now_iso()),
        )
