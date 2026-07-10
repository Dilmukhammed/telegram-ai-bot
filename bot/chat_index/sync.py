from __future__ import annotations

import asyncio
import logging
from typing import Any

from bot.chat_index import chunking
from bot.chat_index.index_store import list_indexed_message_ids, upsert_chunks
from bot.chat_index.turns import group_messages_by_turn
from bot.chat_store import sessions as session_ops
from bot.chat_store.models import ChatSession
from bot.chat_store import messages as message_ops

logger = logging.getLogger(__name__)


def _active_session(conn, user_id: int) -> ChatSession | None:
    return session_ops.get_active_session(conn, user_id)


def index_session_messages(store, session_id: str) -> int:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return 0
        session = session_ops.row_to_session(row)
        indexed_ids = list_indexed_message_ids(conn, session_id)
        messages = message_ops.read_all_messages(conn, session_id)
        turns = group_messages_by_turn(messages)
        seq_by_turn = {
            turn: (items[0].seq, items[-1].seq)
            for turn, items in turns.items()
            if items
        }
        turn_by_message_id = {
            message.message_id: turn
            for turn, items in turns.items()
            for message in items
        }

        chunks: list[dict[str, Any]] = []
        for message in messages:
            if message.message_id in indexed_ids:
                continue
            turn_number = turn_by_message_id.get(message.message_id)
            seq_start, seq_end = seq_by_turn.get(turn_number, (message.seq, message.seq))
            chunks.extend(
                chunking.chunk_message(
                    message,
                    session,
                    turn_number=turn_number,
                    seq_start=seq_start,
                    seq_end=seq_end,
                )
            )
        count = upsert_chunks(conn, chunks)
        if count:
            conn.commit()
        return count


def index_session_summary(store, session_id: str) -> int:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return 0
        session = session_ops.row_to_session(row)
        chunks = chunking.chunk_session_summary(session)
        count = upsert_chunks(conn, chunks)
        if count:
            conn.commit()
        return count


def index_tool_result_record(
    store,
    *,
    user_id: int,
    display_ref: int,
    tool_name: str,
    summary: str | None,
    payload_json: str,
    run_id: str | None,
) -> int:
    with store._connect() as conn:
        session = _active_session(conn, user_id)
        session_id = session.session_id if session is not None else "unknown"
        chunks = chunking.chunks_for_tool_result(
            user_id=user_id,
            session_id=session_id,
            session=session,
            display_ref=display_ref,
            tool_name=tool_name,
            summary=summary,
            payload_json=payload_json,
        )
        count = upsert_chunks(conn, chunks)
        if count:
            conn.commit()
        return count


def index_tool_result_summary(
    store,
    *,
    user_id: int,
    display_ref: int,
    tool_name: str,
    summary: str,
    run_id: str | None,
) -> int:
    from tools.tool_results.store import get_tool_result_store

    record = get_tool_result_store().get(display_ref, user_id=user_id)
    payload_json = record.payload_json if record is not None else "{}"
    return index_tool_result_record(
        store,
        user_id=user_id,
        display_ref=display_ref,
        tool_name=tool_name,
        summary=summary,
        payload_json=payload_json,
        run_id=run_id,
    )


def rebuild_user_index(store, user_id: int, *, clear_existing: bool = False) -> int:
    from bot.chat_index.index_store import clear_user_search_chunks
    from tools.tool_results.store import get_tool_result_store

    if clear_existing:
        with store._connect() as conn:
            clear_user_search_chunks(conn, user_id)
            conn.commit()

    total = 0
    sessions = store.list_sessions(user_id, limit=500)
    for session in sessions:
        total += index_session_messages(store, session.session_id)
        if session.summary:
            total += index_session_summary(store, session.session_id)
    for record in get_tool_result_store().list_all_for_user(user_id):
        total += index_tool_result_record(
            store,
            user_id=record.user_id,
            display_ref=record.display_ref,
            tool_name=record.tool_name,
            summary=record.summary,
            payload_json=record.payload_json,
            run_id=record.run_id,
        )
    return total


def rebuild_all_users_index() -> tuple[int, int]:
    from bot.chat_store import get_chat_store

    store = get_chat_store()
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM chat_sessions ORDER BY user_id"
        ).fetchall()
    user_ids = [int(row["user_id"]) for row in rows]
    total_chunks = 0
    for user_id in user_ids:
        total_chunks += rebuild_user_index(store, user_id, clear_existing=True)
    return len(user_ids), total_chunks


def delete_tool_result_chunks_for_user(store, user_id: int) -> int:
    from bot.chat_index.index_store import delete_tool_result_chunks_for_user as _delete

    with store._connect() as conn:
        deleted = _delete(conn, user_id)
        conn.commit()
        return deleted


def enqueue_index_session(store, session_id: str) -> asyncio.Task[None] | None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    async def _run() -> None:
        try:
            count = index_session_messages(store, session_id)
            if count:
                logger.info("chat_index session messages session_id=%s chunks=%s", session_id, count)
        except Exception:
            logger.exception("chat_index session failed session_id=%s", session_id)

    return loop.create_task(_run())


def enqueue_index_tool_result(
    store,
    *,
    user_id: int,
    display_ref: int,
    tool_name: str,
    summary: str | None,
    payload_json: str,
    run_id: str | None,
) -> asyncio.Task[None] | None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    async def _run() -> None:
        try:
            count = index_tool_result_record(
                store,
                user_id=user_id,
                display_ref=display_ref,
                tool_name=tool_name,
                summary=summary,
                payload_json=payload_json,
                run_id=run_id,
            )
            if count:
                logger.info(
                    "chat_index tool_result user_id=%s ref=%s chunks=%s",
                    user_id,
                    display_ref,
                    count,
                )
        except Exception:
            logger.exception("chat_index tool_result failed user_id=%s ref=%s", user_id, display_ref)

    return loop.create_task(_run())
