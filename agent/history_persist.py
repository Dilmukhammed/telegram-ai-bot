from __future__ import annotations

import copy
import logging
from typing import Any

from agent.context_collapse import (
    collapse_all_search_tools,
    collapse_duplicate_use_tool_calls,
)
from bot.history_format import strip_rich_appendices

logger = logging.getLogger(__name__)


def _is_supervisor_injection(message: dict[str, Any]) -> bool:
    if message.get("role") != "user":
        return False
    content = message.get("content")
    return isinstance(content, str) and content.startswith("Supervisor review (")


def strip_all_search_tools(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = copy.deepcopy(messages)
    collapse_all_search_tools(out)
    collapse_duplicate_use_tool_calls(out)
    return out


def strip_supervisor_injections(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [message for message in messages if not _is_supervisor_injection(message)]


def strip_reasoning_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove model reasoning_content from assistant messages; keep content as-is."""
    out = copy.deepcopy(messages)
    strip_reasoning_content_inplace(out)
    return out


def strip_reasoning_content_inplace(messages: list[dict[str, Any]]) -> None:
    for message in messages:
        if message.get("role") == "assistant":
            message.pop("reasoning_content", None)


def extract_worker_history_for_persist(
    messages: list[dict[str, Any]],
    *,
    worker_start_index: int,
    display_reply: str,
) -> list[dict[str, Any]]:
    """Collapsed worker slice: use_tool calls + tool results + final assistant text."""
    worker = copy.deepcopy(messages[worker_start_index:])
    worker = strip_supervisor_injections(worker)
    worker = strip_all_search_tools(worker)
    strip_reasoning_content_inplace(worker)
    worker.append(
        {
            "role": "assistant",
            "content": strip_rich_appendices(display_reply),
        }
    )
    return worker
