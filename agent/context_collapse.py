from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def _parse_tool_payload(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def is_search_tools_result(content: str) -> bool:
    payload = _parse_tool_payload(content)
    if payload is None:
        return False
    if payload.get("ok") is False:
        return False
    return "tools" in payload or "count" in payload


def is_successful_use_tool_result(content: str) -> bool:
    payload = _parse_tool_payload(content)
    if payload is None:
        return False
    return payload.get("ok") is True and "tool_name" in payload


def find_search_tools_exchange(messages: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Return (assistant_idx, tool_idx) for the last search_tools call/response pair."""
    last: tuple[int, int] | None = None
    for assistant_idx, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls") or []
        search_call = next(
            (
                call
                for call in tool_calls
                if call.get("function", {}).get("name") == "search_tools"
            ),
            None,
        )
        if search_call is None:
            continue
        call_id = search_call.get("id")
        if not call_id:
            continue
        for tool_idx in range(assistant_idx + 1, len(messages)):
            tool_message = messages[tool_idx]
            if tool_message.get("role") != "tool":
                break
            if tool_message.get("tool_call_id") != call_id:
                continue
            if is_search_tools_result(str(tool_message.get("content", ""))):
                last = (assistant_idx, tool_idx)
            break
    return last


def _assistant_only_search_tools(assistant: dict[str, Any]) -> bool:
    tool_calls = assistant.get("tool_calls") or []
    return bool(tool_calls) and all(
        call.get("function", {}).get("name") == "search_tools" for call in tool_calls
    )


def _exchange_still_valid(
    messages: list[dict[str, Any]],
    exchange: tuple[int, int],
) -> bool:
    assistant_idx, tool_idx = exchange
    if assistant_idx < 0 or tool_idx < 0:
        return False
    if assistant_idx >= len(messages) or tool_idx >= len(messages):
        return False
    assistant = messages[assistant_idx]
    tool_message = messages[tool_idx]
    if assistant.get("role") != "assistant" or tool_message.get("role") != "tool":
        return False
    if not _assistant_only_search_tools(assistant):
        return False
    return is_search_tools_result(str(tool_message.get("content", "")))


def collapse_search_tools_exchange(
    messages: list[dict[str, Any]],
    exchange: tuple[int, int] | None = None,
) -> bool:
    """Remove a search_tools assistant+tool pair. Returns True if collapsed."""
    target = exchange or find_search_tools_exchange(messages)
    if target is None:
        return False
    if not _exchange_still_valid(messages, target):
        return False

    assistant_idx, tool_idx = target
    before_count = len(messages)
    del messages[max(assistant_idx, tool_idx)]
    del messages[min(assistant_idx, tool_idx)]
    logger.info(
        "context_collapse search_tools removed assistant_idx=%s tool_idx=%s messages_before=%s messages_after=%s",
        assistant_idx,
        tool_idx,
        before_count,
        len(messages),
    )
    return True


def turn_had_successful_use_tool(tool_calls: list[Any], tool_results: list[str]) -> bool:
    if not tool_calls or len(tool_calls) != len(tool_results):
        return False
    for tool_call, result in zip(tool_calls, tool_results, strict=True):
        if tool_call.function.name != "use_tool":
            return False
        if not is_successful_use_tool_result(result):
            return False
    return True


def turn_includes_search_tools(tool_calls: list[Any]) -> bool:
    return any(tool_call.function.name == "search_tools" for tool_call in tool_calls)


class SearchContextCollapser:
    """Defer removing search_tools until a successful use_tool chain finishes."""

    def __init__(self, on_search_collapsed: Callable[[], None] | None = None) -> None:
        self._pending = False
        self._search_exchange: tuple[int, int] | None = None
        self._on_search_collapsed = on_search_collapsed

    @property
    def pending(self) -> bool:
        return self._pending

    @property
    def tracked_search_exchange(self) -> tuple[int, int] | None:
        return self._search_exchange

    def _collapse_tracked(self, messages: list[dict[str, Any]]) -> bool:
        if self._search_exchange is None:
            return False
        collapsed = collapse_search_tools_exchange(messages, self._search_exchange)
        if collapsed:
            self._search_exchange = None
            if self._on_search_collapsed:
                self._on_search_collapsed()
        return collapsed

    def on_tool_turn(
        self,
        messages: list[dict[str, Any]],
        tool_calls: list[Any],
        tool_results: list[str],
    ) -> None:
        if turn_includes_search_tools(tool_calls):
            if self._pending:
                self._collapse_tracked(messages)
            self._pending = False
            self._search_exchange = find_search_tools_exchange(messages)
            logger.info(
                "context_collapse track_new_search exchange=%s pending=false",
                self._search_exchange,
            )
            return

        if turn_had_successful_use_tool(tool_calls, tool_results):
            if self._search_exchange is None:
                self._search_exchange = find_search_tools_exchange(messages)
            self._pending = self._search_exchange is not None
            logger.info(
                "context_collapse use_tool_ok exchange=%s pending=%s",
                self._search_exchange,
                self._pending,
            )
            return

        self._pending = False
        logger.info("context_collapse reset pending=false (no successful use_tool)")

    def collapse_if_pending(self, messages: list[dict[str, Any]]) -> bool:
        if not self._pending:
            return False
        logger.info(
            "context_collapse finalize pending=true exchange=%s messages_before=%s",
            self._search_exchange,
            len(messages),
        )
        collapsed = self._collapse_tracked(messages)
        if collapsed:
            self._pending = False
        return collapsed
