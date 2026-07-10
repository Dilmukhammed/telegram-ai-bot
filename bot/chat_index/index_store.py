from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from bot.chat_store.schema import utc_now_iso


@dataclass(frozen=True)
class ChatSearchChunk:
    chunk_id: int
    user_id: int
    session_id: str
    source_type: str
    source_key: str
    turn_number: int | None
    seq_start: int | None
    seq_end: int | None
    tool_ref: int | None
    chunk_index: int
    text: str
    session_started_at: str | None
    session_title: str | None
    session_summary: str | None
    embedding: list[float] | None


def _row_to_chunk(row: sqlite3.Row) -> ChatSearchChunk:
    embedding_raw = row["embedding_json"]
    embedding: list[float] | None = None
    if embedding_raw:
        try:
            parsed = json.loads(embedding_raw)
            if isinstance(parsed, list):
                embedding = [float(item) for item in parsed]
        except (json.JSONDecodeError, TypeError, ValueError):
            embedding = None
    return ChatSearchChunk(
        chunk_id=int(row["chunk_id"]),
        user_id=int(row["user_id"]),
        session_id=row["session_id"],
        source_type=row["source_type"],
        source_key=row["source_key"],
        turn_number=row["turn_number"],
        seq_start=row["seq_start"],
        seq_end=row["seq_end"],
        tool_ref=row["tool_ref"],
        chunk_index=int(row["chunk_index"]),
        text=row["text"],
        session_started_at=row["session_started_at"],
        session_title=row["session_title"],
        session_summary=row["session_summary"],
        embedding=embedding,
    )


def upsert_chunks(conn: sqlite3.Connection, chunks: list[dict[str, Any]]) -> int:
    if not chunks:
        return 0
    indexed_at = utc_now_iso()
    inserted = 0
    for chunk in chunks:
        conn.execute(
            """
            INSERT INTO chat_search_chunks (
                user_id, session_id, source_type, source_key, turn_number,
                seq_start, seq_end, tool_ref, chunk_index, text,
                session_started_at, session_title, session_summary,
                embedding_json, indexed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            ON CONFLICT(user_id, source_type, source_key, chunk_index) DO UPDATE SET
                session_id = excluded.session_id,
                turn_number = excluded.turn_number,
                seq_start = excluded.seq_start,
                seq_end = excluded.seq_end,
                tool_ref = excluded.tool_ref,
                text = excluded.text,
                session_started_at = excluded.session_started_at,
                session_title = excluded.session_title,
                session_summary = excluded.session_summary,
                indexed_at = excluded.indexed_at
            """,
            (
                chunk["user_id"],
                chunk["session_id"],
                chunk["source_type"],
                chunk["source_key"],
                chunk.get("turn_number"),
                chunk.get("seq_start"),
                chunk.get("seq_end"),
                chunk.get("tool_ref"),
                chunk.get("chunk_index", 0),
                chunk["text"],
                chunk.get("session_started_at"),
                chunk.get("session_title"),
                chunk.get("session_summary"),
                indexed_at,
            ),
        )
        inserted += 1
    return inserted


def list_indexed_message_ids(conn: sqlite3.Connection, session_id: str) -> set[int]:
    rows = conn.execute(
        """
        SELECT source_key FROM chat_search_chunks
        WHERE session_id = ? AND source_type = 'message'
        """,
        (session_id,),
    ).fetchall()
    indexed: set[int] = set()
    for row in rows:
        key = str(row["source_key"])
        if not key.startswith("msg:"):
            continue
        parts = key.split(":")
        if len(parts) >= 2 and parts[1].isdigit():
            indexed.add(int(parts[1]))
    return indexed


def load_chunks_for_search(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    session_id: str | None = None,
    date: str | None = None,
) -> list[ChatSearchChunk]:
    query = "SELECT * FROM chat_search_chunks WHERE user_id = ?"
    params: list[Any] = [user_id]
    if session_id:
        query += " AND session_id = ?"
        params.append(session_id)
    if date:
        query += " AND session_started_at IS NOT NULL AND substr(session_started_at, 1, 10) = ?"
        params.append(date.strip()[:10])
    query += " ORDER BY session_started_at DESC, chunk_id DESC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_chunk(row) for row in rows]


def update_chunk_embeddings(
    conn: sqlite3.Connection,
    embeddings: dict[int, list[float]],
) -> None:
    for chunk_id, vector in embeddings.items():
        conn.execute(
            "UPDATE chat_search_chunks SET embedding_json = ? WHERE chunk_id = ?",
            (json.dumps(vector), chunk_id),
        )


def clear_user_search_chunks(conn: sqlite3.Connection, user_id: int) -> int:
    cursor = conn.execute(
        "DELETE FROM chat_search_chunks WHERE user_id = ?",
        (user_id,),
    )
    return cursor.rowcount


def delete_tool_result_chunks_for_user(conn: sqlite3.Connection, user_id: int) -> int:
    cursor = conn.execute(
        """
        DELETE FROM chat_search_chunks
        WHERE user_id = ? AND source_type = 'tool_result'
        """,
        (user_id,),
    )
    return cursor.rowcount
