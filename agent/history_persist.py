from __future__ import annotations

import copy
import logging
from typing import Any

from agent.context_collapse import collapse_search_tools_exchange
from bot.history_format import strip_rich_appendices
from skills.collapse import collapse_all_expanded_skills, collapse_persist_reason

logger = logging.getLogger(__name__)


def _is_supervisor_injection(message: dict[str, Any]) -> bool:
    if message.get("role") != "user":
        return False
    content = message.get("content")
    return isinstance(content, str) and content.startswith("Supervisor review (")


def strip_all_search_tools(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = copy.deepcopy(messages)
    removed = 0
    while collapse_search_tools_exchange(out):
        removed += 1
    if removed:
        logger.info("chat_history_persist stripped search_tools exchanges=%s", removed)
    return out


def strip_supervisor_injections(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [message for message in messages if not _is_supervisor_injection(message)]


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
    collapsed = collapse_all_expanded_skills(worker, reason=collapse_persist_reason())
    if collapsed:
        logger.info("chat_history_persist collapsed_skills=%s", collapsed)
    worker.append(
        {
            "role": "assistant",
            "content": strip_rich_appendices(display_reply),
        }
    )
    return worker
