from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.run_trace import RunTrace

from bot.chat_store import messages as message_ops
from bot.chat_store import sessions as session_ops
from bot.chat_store import traces as trace_ops
from bot.chat_store.models import (
    ChatMessage,
    ChatPeriodSummary,
    ChatSession,
    ChatSessionTrace,
    PeriodType,
    SessionStatus,
    SummaryStatus,
)
from bot.chat_store.schema import ensure_schema
from bot.history_persist import trim_history_to_turns
from config import get_settings


class ChatStore:
    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        raw_path = db_path or settings.chat_db_path
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
            ensure_schema(conn)
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def get_active_session(self, user_id: int) -> ChatSession | None:
        with self._connect() as conn:
            return session_ops.get_active_session(conn, user_id)

    def get_or_create_active_session(
        self,
        user_id: int,
        *,
        opened_by: str = "first_message",
        metadata: dict[str, Any] | None = None,
    ) -> ChatSession:
        with self._connect() as conn:
            session = session_ops.get_or_create_active_session(
                conn,
                user_id,
                opened_by=opened_by,
                metadata=metadata,
            )
            conn.commit()
            return session

    def create_active_session(
        self,
        user_id: int,
        *,
        opened_by: str = "first_message",
        metadata: dict[str, Any] | None = None,
    ) -> ChatSession:
        with self._connect() as conn:
            session = session_ops.create_active_session(
                conn,
                user_id,
                opened_by=opened_by,
                metadata=metadata,
            )
            conn.commit()
            return session

    def archive_session(
        self,
        session_id: str,
        *,
        closed_by: session_ops.ArchiveReason,
        metadata_patch: dict[str, Any] | None = None,
    ) -> ChatSession | None:
        with self._connect() as conn:
            session = session_ops.archive_session(
                conn,
                session_id,
                closed_by=closed_by,
                metadata_patch=metadata_patch,
            )
            conn.commit()
            return session

    def archive_active_session(
        self,
        user_id: int,
        *,
        closed_by: session_ops.ArchiveReason,
        metadata_patch: dict[str, Any] | None = None,
    ) -> ChatSession | None:
        with self._connect() as conn:
            session = session_ops.archive_active_session(
                conn,
                user_id,
                closed_by=closed_by,
                metadata_patch=metadata_patch,
            )
            conn.commit()
            return session

    def archive_and_create_active(
        self,
        user_id: int,
        *,
        closed_by: session_ops.ArchiveReason,
        metadata_patch: dict[str, Any] | None = None,
        opened_by: str = "archive_reset",
    ) -> tuple[ChatSession | None, ChatSession]:
        with self._connect() as conn:
            archived, created = session_ops.archive_and_create_active(
                conn,
                user_id,
                closed_by=closed_by,
                metadata_patch=metadata_patch,
                opened_by=opened_by,
            )
            conn.commit()
            return archived, created

    def list_sessions(
        self,
        user_id: int,
        *,
        status: SessionStatus | None = None,
        limit: int = 50,
    ) -> list[ChatSession]:
        with self._connect() as conn:
            return session_ops.list_sessions(conn, user_id, status=status, limit=limit)

    def update_session_summary_status(
        self,
        session_id: str,
        *,
        summary: str | None = None,
        summary_status: SummaryStatus,
        summary_started_at: datetime | None = None,
        summary_completed_at: datetime | None = None,
    ) -> ChatSession | None:
        with self._connect() as conn:
            session = session_ops.update_session_summary_status(
                conn,
                session_id,
                summary=summary,
                summary_status=summary_status,
                summary_started_at=summary_started_at,
                summary_completed_at=summary_completed_at,
            )
            conn.commit()
            return session

    def append_messages(
        self,
        session_id: str,
        user_id: int,
        messages: list[dict[str, Any]],
        *,
        default_source_at: datetime | None = None,
        source_at_for_message: list[datetime | None] | None = None,
        metadata_for_message: list[dict[str, Any] | None] | None = None,
    ) -> list[int]:
        with self._connect() as conn:
            ids = message_ops.append_messages(
                conn,
                session_id,
                user_id,
                messages,
                default_source_at=default_source_at,
                source_at_for_message=source_at_for_message,
                metadata_for_message=metadata_for_message,
            )
            conn.commit()
            return ids

    def read_messages(
        self,
        session_id: str,
        *,
        from_seq: int = 1,
        limit: int | None = None,
    ) -> list[ChatMessage]:
        with self._connect() as conn:
            return message_ops.read_range(
                conn,
                session_id,
                from_seq=from_seq,
                limit=limit,
            )

    def read_message_dicts(
        self,
        session_id: str,
        *,
        from_seq: int = 1,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return message_ops.read_message_dicts(
                conn,
                session_id,
                from_seq=from_seq,
                limit=limit,
            )

    def get_message_by_id(self, message_id: int) -> ChatMessage | None:
        with self._connect() as conn:
            return message_ops.get_message_by_id(conn, message_id)

    def get_session_for_user(self, session_id: str, user_id: int) -> ChatSession | None:
        with self._connect() as conn:
            return session_ops.get_session_for_user(conn, session_id, user_id)

    def get_message_for_user(self, message_id: int, user_id: int) -> ChatMessage | None:
        with self._connect() as conn:
            return message_ops.get_message_for_user(conn, message_id, user_id)

    def max_message_id(self) -> int:
        with self._connect() as conn:
            return message_ops.max_message_id(conn)

    def read_messages_after_id(self, message_id: int, *, limit: int) -> list[ChatMessage]:
        with self._connect() as conn:
            return message_ops.read_messages_after_id(conn, message_id, limit=limit)

    def search_messages(
        self,
        user_id: int,
        *,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
        use_regex: bool = False,
    ) -> list[ChatMessage]:
        with self._connect() as conn:
            return message_ops.search_messages(
                conn,
                user_id,
                query=query,
                session_id=session_id,
                limit=limit,
                use_regex=use_regex,
            )

    def get_last_user_source_at(self, session_id: str) -> datetime | None:
        with self._connect() as conn:
            return message_ops.get_last_user_source_at(conn, session_id)

    def load_active_history_for_prompt(
        self,
        user_id: int,
        *,
        max_turns: int,
    ) -> tuple[ChatSession | None, list[dict[str, Any]], datetime | None]:
        with self._connect() as conn:
            session = session_ops.get_active_session(conn, user_id)
            if session is None:
                return None, [], None
            messages = message_ops.read_message_dicts(conn, session.session_id)
            trimmed = trim_history_to_turns(messages, max_turns)
            last_user_at = message_ops.get_last_user_source_at(conn, session.session_id)
            return session, trimmed, last_user_at

    def append_session_trace(
        self,
        session_id: str,
        user_id: int,
        *,
        trace: RunTrace,
        assistant_reply: str,
        source_at: datetime | None = None,
    ) -> int:
        with self._connect() as conn:
            row_id = trace_ops.append_session_trace(
                conn,
                session_id,
                user_id,
                trace=trace,
                assistant_reply=assistant_reply,
                source_at=source_at,
            )
            conn.commit()
            return row_id

    def list_session_traces(self, session_id: str) -> list[ChatSessionTrace]:
        with self._connect() as conn:
            return trace_ops.list_session_traces(conn, session_id)

    def count_session_traces(self, session_id: str) -> int:
        with self._connect() as conn:
            return trace_ops.count_session_traces(conn, session_id)

    def read_turns(
        self,
        session_id: str,
        turn_numbers: list[int],
    ) -> dict[int, list[ChatMessage]]:
        from bot.chat_index.turns import group_messages_by_turn

        with self._connect() as conn:
            messages = message_ops.read_all_messages(conn, session_id)
            grouped = group_messages_by_turn(messages)
            return {turn: grouped[turn] for turn in turn_numbers if turn in grouped}

    def get_period_summary(
        self,
        user_id: int,
        period_type: PeriodType | str,
        period_key: str,
    ) -> ChatPeriodSummary | None:
        from bot.chat_store import periods as period_ops

        with self._connect() as conn:
            return period_ops.get_period(conn, user_id, period_type, period_key)

    def list_period_summaries(
        self,
        user_id: int,
        *,
        period_type: PeriodType | str | None = None,
        limit: int = 20,
    ) -> list[ChatPeriodSummary]:
        from bot.chat_store import periods as period_ops

        with self._connect() as conn:
            return period_ops.list_periods(
                conn,
                user_id,
                period_type=period_type,
                limit=limit,
            )
