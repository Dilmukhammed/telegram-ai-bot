from datetime import datetime, timezone
import logging
from typing import Any

from aiogram.types import Message

from agent.context_collapse import collapse_duplicate_use_tool_calls
from agent.loop import Agent
from agent.reply_markup import build_reply_markup
from bot.chat_response import ChatResponse
from bot.chat_store import ChatStore, get_chat_store
from bot.chat_store.sessions import ArchiveReason
from bot.chat_store.summary import enqueue_session_summary
from bot.history_persist import trim_history_to_turns
from bot.message_gap import prefix_message_if_gap
from bot.telegram_reply_context import apply_reply_context_prefix
from bot.vision import history_text_for_image_turn
from skills.session import SkillSessionStore, apply_skill_run_snapshot
from config import get_settings
from tools.runtime import ToolRuntime

logger = logging.getLogger(__name__)

_PREVIEW_CHARS = 100


def _content_snippet(content: Any) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif block.get("type") == "image_url":
                    parts.append("[image]")
                else:
                    parts.append(f"[{block.get('type', 'block')}]")
        text = " ".join(parts)
    else:
        text = str(content or "")
    collapsed = " ".join(text.split())
    if len(collapsed) <= _PREVIEW_CHARS:
        return collapsed
    return f"{collapsed[: _PREVIEW_CHARS - 1]}…"


def _history_log_lines(messages: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for index, message in enumerate(messages):
        role = message.get("role", "?")
        if role == "tool":
            snippet = _content_snippet(message.get("content"))
            lines.append(f"{index}:tool:{snippet}")
            continue
        if role == "assistant" and message.get("tool_calls"):
            names = [
                call.get("function", {}).get("name", "?")
                for call in message.get("tool_calls") or []
            ]
            lines.append(f"{index}:assistant:tool_calls={names}")
            continue
        snippet = _content_snippet(message.get("content"))
        lines.append(f"{index}:{role}:{snippet}")
    return lines


def _count_turns(messages: list[dict[str, Any]]) -> int:
    return sum(1 for message in messages if message.get("role") == "user")


class ChatService:
    def __init__(
        self,
        agent: Agent,
        *,
        chat_store: ChatStore | None = None,
    ) -> None:
        self._agent = agent
        self._chat_store = chat_store or get_chat_store()
        self._histories: dict[int, list[dict[str, Any]]] = {}
        self._last_message_at: dict[int, datetime] = {}

    def stats_report(self, runtime: ToolRuntime) -> str:
        return self._agent.stats_report(runtime)

    async def context_stats_report(self, user_id: int) -> str:
        return await self._agent.context_stats_report(
            self.get_history(user_id),
            user_id=user_id,
        )

    async def dump_context_to_file(self, user_id: int):
        from bot.history_dump import dump_user_context

        return await dump_user_context(
            user_id=user_id,
            history=self.get_history(user_id),
            agent=self._agent,
        )

    def trace_last_report(self, user_id: int) -> str:
        return self._agent.trace_last_report(user_id)

    def coach_last_report(self, user_id: int) -> str:
        return self._agent.coach_last_report(user_id)

    def checker_last_report(self, user_id: int) -> str:
        return self._agent.checker_last_report(user_id)

    def reset_history(
        self,
        user_id: int,
        *,
        closed_by: ArchiveReason = "reset",
    ) -> int:
        active = self._chat_store.get_active_session(user_id)
        previous_count = len(self._histories.get(user_id, []))
        if active is None and previous_count == 0:
            had_history = False
        else:
            had_history = previous_count > 0 or (active is not None and active.message_count > 0)

        if active is not None and active.message_count > 0:
            archived, _created = self._chat_store.archive_and_create_active(
                user_id,
                closed_by=closed_by,
            )
            if archived is not None:
                logger.info(
                    "chat_session_archived user_id=%s session_id=%s messages=%s closed_by=%s",
                    user_id,
                    archived.session_id,
                    archived.message_count,
                    closed_by,
                )
                enqueue_session_summary(self._chat_store, archived.session_id)

        self._histories.pop(user_id, None)
        self._last_message_at.pop(user_id, None)
        SkillSessionStore.reset(user_id)
        from tools.tool_results.store import get_tool_result_store
        from bot.chat_index.sync import delete_tool_result_chunks_for_user

        deleted = get_tool_result_store().delete_for_user(user_id)
        delete_tool_result_chunks_for_user(self._chat_store, user_id)
        if deleted:
            logger.info("tool_result_archive_reset user_id=%s deleted=%s", user_id, deleted)
        if had_history:
            logger.info(
                "chat_history_reset user_id=%s cleared_messages=%s closed_by=%s",
                user_id,
                previous_count or (active.message_count if active else 0),
                closed_by,
            )
        return deleted

    def invalidate_user_history(self, user_id: int) -> None:
        """Drop in-memory prompt history after external session archive (e.g. day boundary)."""
        self._histories.pop(user_id, None)
        self._last_message_at.pop(user_id, None)

    def get_history(self, user_id: int) -> list[dict[str, Any]]:
        if user_id not in self._histories:
            settings = get_settings()
            session, history, last_user_at = self._chat_store.load_active_history_for_prompt(
                user_id,
                max_turns=settings.chat_max_history,
            )
            self._histories[user_id] = history
            if last_user_at is not None:
                self._last_message_at[user_id] = last_user_at
            if history:
                logger.info(
                    "chat_history_loaded user_id=%s session_id=%s messages=%s turns=%s",
                    user_id,
                    session.session_id if session else None,
                    len(history),
                    _count_turns(history),
                )
        return self._histories[user_id]

    def _log_history_snapshot(self, *, user_id: int, stage: str, history: list[dict[str, Any]]) -> None:
        settings = get_settings()
        max_turns = settings.chat_max_history
        logger.info(
            "chat_history_%s user_id=%s messages=%s turns=%s max_turns=%s chat_max_history=%s",
            stage,
            user_id,
            len(history),
            _count_turns(history),
            max_turns,
            settings.chat_max_history,
        )
        for line in _history_log_lines(history):
            logger.info("chat_history_%s user_id=%s %s", stage, user_id, line)

    def prepare_user_message(
        self,
        user_id: int,
        user_text: str,
        message_at: datetime,
    ) -> str:
        if message_at.tzinfo is None:
            message_at = message_at.replace(tzinfo=timezone.utc)

        prepared = prefix_message_if_gap(
            user_text,
            self._last_message_at.get(user_id),
            message_at,
        )
        self._last_message_at[user_id] = message_at
        return prepared

    def append_turn_messages(
        self,
        user_id: int,
        turn_messages: list[dict[str, Any]],
        *,
        user_message_at: datetime | None = None,
        user_message_metadata: dict[str, Any] | None = None,
    ) -> None:
        if not turn_messages:
            return

        session = self._chat_store.get_or_create_active_session(user_id)
        turn_finished_at = datetime.now(timezone.utc)
        user_at = user_message_at or self._last_message_at.get(user_id) or turn_finished_at
        if user_at.tzinfo is None:
            user_at = user_at.replace(tzinfo=timezone.utc)

        source_at_for_message: list[datetime | None] = []
        metadata_for_message: list[dict[str, Any] | None] = []
        for index, message in enumerate(turn_messages):
            if index == 0 and message.get("role") == "user":
                source_at_for_message.append(user_at)
                metadata_for_message.append(user_message_metadata)
            else:
                source_at_for_message.append(turn_finished_at)
                metadata_for_message.append(None)

        inserted_ids = self._chat_store.append_messages(
            session.session_id,
            user_id,
            turn_messages,
            source_at_for_message=source_at_for_message,
            metadata_for_message=metadata_for_message,
        )

        from bot.memory_chat_adapter import notify_chat_ingested

        notify_chat_ingested(user_id=user_id, message_ids=inserted_ids)

        from bot.chat_index.sync import enqueue_index_session

        enqueue_index_session(self._chat_store, session.session_id)

        history = self._histories.get(user_id)
        if history is None:
            history = []
            self._histories[user_id] = history
        history.extend(turn_messages)
        collapse_duplicate_use_tool_calls(history)

        settings = get_settings()
        max_turns = settings.chat_max_history
        before_count = len(history)
        before_turns = _count_turns(history)
        if before_turns > max_turns:
            dropped = history[: before_count - len(trim_history_to_turns(history, max_turns))]
            self._histories[user_id] = trim_history_to_turns(history, max_turns)
            after_count = len(self._histories[user_id])
            logger.info(
                "chat_history_trim user_id=%s before=%s after=%s dropped=%s max_turns=%s chat_max_history=%s",
                user_id,
                before_count,
                after_count,
                before_count - after_count,
                max_turns,
                settings.chat_max_history,
            )
            for line in _history_log_lines(dropped):
                logger.info("chat_history_trim_dropped user_id=%s %s", user_id, line)
            self._log_history_snapshot(user_id=user_id, stage="after_trim", history=self._histories[user_id])
        else:
            logger.info(
                "chat_history_append user_id=%s messages=%s turns=%s max_turns=%s (no trim)",
                user_id,
                before_count,
                before_turns,
                max_turns,
            )

    async def generate_reply(
        self,
        user_id: int,
        user_text: str,
        on_status=None,
        message_at: datetime | None = None,
        *,
        image_data_urls: list[str] | None = None,
        telegram_message_id: int | None = None,
        telegram_chat_id: int | None = None,
        telegram_message: Message | None = None,
    ) -> ChatResponse:
        if message_at is None:
            message_at = datetime.now(timezone.utc)

        prepared_text = self.prepare_user_message(user_id, user_text, message_at)
        history = self.get_history(user_id)
        prepared_text = apply_reply_context_prefix(
            prepared_text,
            telegram_message=telegram_message,
            user_id=user_id,
            chat_store=self._chat_store,
            prompt_history=history,
        )
        self._log_history_snapshot(user_id=user_id, stage="before_agent", history=history)
        logger.info(
            "chat_history_current_message user_id=%s %s",
            user_id,
            _content_snippet(prepared_text),
        )
        # PR8: shadow retrieval runs in parallel and must never mutate messages.
        try:
            from memory.retrieval import schedule_shadow_preflight

            schedule_shadow_preflight(
                user_id=user_id,
                query=prepared_text,
                query_time=message_at,
            )
        except Exception:
            logger.exception("memory_shadow_schedule_failed user_id=%s", user_id)
        result = await self._agent.run(
            prepared_text,
            history=history,
            on_status=on_status,
            user_id=user_id,
            image_data_urls=image_data_urls,
        )
        history_text = (
            history_text_for_image_turn(prepared_text)
            if image_data_urls
            else prepared_text
        )
        user_metadata: dict[str, Any] = {}
        if telegram_message_id is not None:
            user_metadata["telegram_message_id"] = telegram_message_id
        if telegram_chat_id is not None:
            user_metadata["telegram_chat_id"] = telegram_chat_id
        self.append_turn_messages(
            user_id,
            [{"role": "user", "content": history_text}, *result.worker_history],
            user_message_at=message_at,
            user_message_metadata=user_metadata or None,
        )
        trace = self._agent.last_trace(user_id)
        if trace is not None:
            session = self._chat_store.get_active_session(user_id)
            if session is not None:
                self._chat_store.append_session_trace(
                    session.session_id,
                    user_id,
                    trace=trace,
                    assistant_reply=result.reply,
                    source_at=message_at,
                )
        apply_skill_run_snapshot(user_id, result.skill_snapshot)
        self._log_history_snapshot(user_id=user_id, stage="after_agent", history=self.get_history(user_id))
        return ChatResponse(
            text=result.reply,
            reply_markup=build_reply_markup(
                maps_buttons=result.maps_buttons,
                gmail_buttons=result.gmail_buttons,
                calendar_buttons=result.calendar_buttons,
                tasks_buttons=result.tasks_buttons,
                drive_buttons=result.drive_buttons,
            ),
            outbound_files=result.outbound_files,
        )
