from collections import defaultdict
from datetime import datetime, timezone
import logging
from typing import Any

from agent.loop import Agent
from agent.reply_markup import build_reply_markup
from bot.chat_response import ChatResponse
from bot.history_persist import trim_history_to_turns
from bot.message_gap import prefix_message_if_gap
from bot.vision import history_text_for_image_turn
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
    def __init__(self, agent: Agent) -> None:
        self._agent = agent
        self._histories: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self._last_message_at: dict[int, datetime] = {}

    def stats_report(self, runtime: ToolRuntime) -> str:
        return self._agent.stats_report(runtime)

    def trace_last_report(self, user_id: int) -> str:
        return self._agent.trace_last_report(user_id)

    def reset_history(self, user_id: int) -> None:
        had_history = user_id in self._histories
        previous_count = len(self._histories.get(user_id, []))
        self._histories.pop(user_id, None)
        self._last_message_at.pop(user_id, None)
        if had_history:
            logger.info(
                "chat_history_reset user_id=%s cleared_messages=%s",
                user_id,
                previous_count,
            )

    def get_history(self, user_id: int) -> list[dict[str, Any]]:
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

    def append_turn_messages(self, user_id: int, turn_messages: list[dict[str, Any]]) -> None:
        if not turn_messages:
            return

        history = self._histories[user_id]
        history.extend(turn_messages)

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
    ) -> ChatResponse:
        if message_at is None:
            message_at = datetime.now(timezone.utc)

        prepared_text = self.prepare_user_message(user_id, user_text, message_at)
        history = self.get_history(user_id)
        self._log_history_snapshot(user_id=user_id, stage="before_agent", history=history)
        logger.info(
            "chat_history_current_message user_id=%s %s",
            user_id,
            _content_snippet(prepared_text),
        )
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
        self.append_turn_messages(
            user_id,
            [{"role": "user", "content": history_text}, *result.worker_history],
        )
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
