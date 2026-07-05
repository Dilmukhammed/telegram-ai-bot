from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from tools.coerce import normalize_use_tool_call

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


def strip_remaining_search_tools_artifacts(messages: list[dict[str, Any]]) -> int:
    """Remove orphan search_tools tool results and assistant-only search_tools calls."""
    removed = 0
    index = 0
    while index < len(messages):
        message = messages[index]
        role = message.get("role")
        content = str(message.get("content") or "")

        if role == "tool" and is_search_tools_result(content):
            messages.pop(index)
            removed += 1
            continue

        if role == "assistant":
            tool_calls = message.get("tool_calls") or []
            if tool_calls and all(
                call.get("function", {}).get("name") == "search_tools"
                for call in tool_calls
            ):
                messages.pop(index)
                removed += 1
                continue

        index += 1

    if removed:
        logger.info("context_collapse stripped orphan search_tools artifacts=%s", removed)
    return removed


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


def _parse_tool_call_arguments(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def use_tool_call_identity(tool_call: dict[str, Any]) -> tuple[str, str] | None:
    """Return (tool_name, canonical_key) for a use_tool call, or None."""
    if tool_call.get("function", {}).get("name") != "use_tool":
        return None
    raw_args = _parse_tool_call_arguments(tool_call.get("function", {}).get("arguments"))
    tool_name, inner = normalize_use_tool_call(raw_args)
    if not tool_name:
        return None
    canonical = json.dumps(
        {"tool_name": tool_name, "arguments": inner},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return tool_name, canonical


def _use_tool_exchange_valid(
    messages: list[dict[str, Any]],
    assistant_idx: int,
    tool_idx: int,
) -> bool:
    if assistant_idx < 0 or tool_idx < 0:
        return False
    if assistant_idx >= len(messages) or tool_idx >= len(messages):
        return False
    assistant = messages[assistant_idx]
    tool_message = messages[tool_idx]
    if assistant.get("role") != "assistant" or tool_message.get("role") != "tool":
        return False
    call_id = tool_message.get("tool_call_id")
    if not call_id:
        return False
    tool_calls = assistant.get("tool_calls") or []
    return any(
        call.get("id") == call_id and call.get("function", {}).get("name") == "use_tool"
        for call in tool_calls
    )


def find_all_use_tool_exchanges(
    messages: list[dict[str, Any]],
) -> list[tuple[int, int, str, str]]:
    """Return (assistant_idx, tool_idx, tool_name, identity_key) for each use_tool pair."""
    exchanges: list[tuple[int, int, str, str]] = []
    for assistant_idx, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls") or []
        for tool_call in tool_calls:
            identity = use_tool_call_identity(tool_call)
            if identity is None:
                continue
            tool_name, key = identity
            call_id = tool_call.get("id")
            if not call_id:
                continue
            for tool_idx in range(assistant_idx + 1, len(messages)):
                tool_message = messages[tool_idx]
                if tool_message.get("role") != "tool":
                    break
                if tool_message.get("tool_call_id") != call_id:
                    continue
                exchanges.append((assistant_idx, tool_idx, tool_name, key))
                break
    return exchanges


def _duplicate_use_tool_footnote(tool_name: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": (
            f"[Collapsed duplicate tool call: `{tool_name}` with identical arguments — "
            "called again; see the latest result below.]"
        ),
    }


def collapse_use_tool_exchange_to_footnote(
    messages: list[dict[str, Any]],
    assistant_idx: int,
    tool_idx: int,
    *,
    tool_name: str,
) -> bool:
    if not _use_tool_exchange_valid(messages, assistant_idx, tool_idx):
        return False

    assistant = messages[assistant_idx]
    tool_message = messages[tool_idx]
    call_id = tool_message.get("tool_call_id")
    tool_calls = assistant.get("tool_calls") or []
    footnote = _duplicate_use_tool_footnote(tool_name)

    if len(tool_calls) == 1:
        insert_at = min(assistant_idx, tool_idx)
        del messages[max(assistant_idx, tool_idx)]
        del messages[min(assistant_idx, tool_idx)]
        messages.insert(insert_at, footnote)
    else:
        assistant["tool_calls"] = [
            call for call in tool_calls if call.get("id") != call_id
        ]
        if not assistant["tool_calls"]:
            assistant.pop("tool_calls", None)
        del messages[tool_idx]
        messages.insert(tool_idx, footnote)

    logger.info(
        "context_collapse duplicate_use_tool tool=%s assistant_idx=%s tool_idx=%s messages_after=%s",
        tool_name,
        assistant_idx,
        tool_idx,
        len(messages),
    )
    return True


def collapse_duplicate_use_tool_calls(messages: list[dict[str, Any]]) -> int:
    """Keep the latest identical use_tool result; collapse earlier duplicates to footnotes."""
    exchanges = find_all_use_tool_exchanges(messages)
    by_key: dict[str, list[tuple[int, int, str]]] = {}
    for assistant_idx, tool_idx, tool_name, key in exchanges:
        by_key.setdefault(key, []).append((assistant_idx, tool_idx, tool_name))

    to_collapse: list[tuple[int, int, str]] = []
    for group in by_key.values():
        if len(group) < 2:
            continue
        to_collapse.extend(group[:-1])

    collapsed = 0
    for assistant_idx, tool_idx, tool_name in sorted(to_collapse, key=lambda item: item[0], reverse=True):
        if collapse_use_tool_exchange_to_footnote(
            messages,
            assistant_idx,
            tool_idx,
            tool_name=tool_name,
        ):
            collapsed += 1
    if collapsed:
        logger.info("context_collapse duplicate_use_tool total_collapsed=%s", collapsed)
    return collapsed


def collapse_all_search_tools(messages: list[dict[str, Any]]) -> int:
    """Remove every search_tools assistant+tool pair and orphan artifacts."""
    removed = 0
    while collapse_search_tools_exchange(messages):
        removed += 1
    orphans = strip_remaining_search_tools_artifacts(messages)
    total = removed + orphans
    if total:
        logger.info(
            "context_collapse search_tools all_collapsed exchanges=%s orphans=%s messages_after=%s",
            removed,
            orphans,
            len(messages),
        )
    return total


def turn_had_successful_use_tool(tool_calls: list[Any], tool_results: list[str]) -> bool:
    if not tool_calls or len(tool_calls) != len(tool_results):
        return False
    for tool_call, result in zip(tool_calls, tool_results, strict=True):
        if tool_call.function.name != "use_tool":
            return False
        if not is_successful_use_tool_result(result):
            return False
    return True


def turn_had_any_successful_use_tool(tool_calls: list[Any], tool_results: list[str]) -> bool:
    if not tool_calls or len(tool_calls) != len(tool_results):
        return False
    for tool_call, result in zip(tool_calls, tool_results, strict=True):
        if tool_call.function.name != "use_tool":
            continue
        if is_successful_use_tool_result(result):
            return True
    return False


def turn_includes_search_tools(tool_calls: list[Any]) -> bool:
    return any(tool_call.function.name == "search_tools" for tool_call in tool_calls)


class SearchContextCollapser:
    """Remove all search_tools exchanges after the first successful use_tool in a run."""

    def __init__(self, on_search_collapsed: Callable[[], None] | None = None) -> None:
        self._on_search_collapsed = on_search_collapsed

    def on_tool_turn(
        self,
        messages: list[dict[str, Any]],
        tool_calls: list[Any],
        tool_results: list[str],
    ) -> None:
        if turn_includes_search_tools(tool_calls):
            logger.info(
                "context_collapse search_tools turn messages=%s",
                len(messages),
            )
            return

        if turn_had_any_successful_use_tool(tool_calls, tool_results):
            collapsed = collapse_all_search_tools(messages)
            if collapsed and self._on_search_collapsed:
                self._on_search_collapsed()
            logger.info(
                "context_collapse use_tool_ok collapsed_all_search=%s messages=%s",
                collapsed,
                len(messages),
            )
            return

        logger.info("context_collapse no successful use_tool; search_tools kept")

    def collapse_if_pending(self, messages: list[dict[str, Any]]) -> bool:
        return False
