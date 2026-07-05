from __future__ import annotations

import json
import logging
import re
from typing import Any

from config import get_settings
from skills.pending import unmark_skill_loaded
from skills.registry import get_skill
from skills.skill_map import skill_id_for_tool_name

logger = logging.getLogger(__name__)

SKILL_LOADED_PREFIX = "[Skill loaded:"
SKILL_COLLAPSED_PREFIX = "[Skill collapsed:"
_SKILL_LOADED_LINE_RE = re.compile(r"^\[Skill loaded:\s*([^\]]+)\]\s*$", re.MULTILINE)
_SKILL_COLLAPSED_LINE_RE = re.compile(r"^\[Skill collapsed:\s*([^\]]+)\]\s*$", re.MULTILINE)


def skills_collapse_idle_turns() -> int:
    return max(1, get_settings().skills_collapse_idle_turns)


def parse_expanded_skill_id(content: str) -> str | None:
    if not isinstance(content, str) or not content.startswith(SKILL_LOADED_PREFIX):
        return None
    first_line = content.split("\n", 1)[0].strip()
    match = _SKILL_LOADED_LINE_RE.match(first_line)
    if not match:
        return None
    body = content.split("\n", 1)
    if len(body) < 2 or not body[1].strip():
        return None
    return match.group(1).strip()


def parse_collapsed_skill_id(content: str) -> str | None:
    if not isinstance(content, str) or not content.startswith(SKILL_COLLAPSED_PREFIX):
        return None
    first_line = content.split("\n", 1)[0].strip()
    match = _SKILL_COLLAPSED_LINE_RE.match(first_line)
    return match.group(1).strip() if match else None


def build_collapsed_skill_content(skill_id: str, *, reason: str) -> str:
    spec = get_skill(skill_id)
    description = spec.description if spec else skill_id
    return (
        f"[Skill collapsed: {skill_id}]\n\n"
        f"Full playbook removed from context ({reason}).\n"
        f"Area: {description}\n"
        f'To restore: use_tool skills.load with {{"skill_id":"{skill_id}"}}.'
    )


def collapse_idle_reason() -> str:
    n = skills_collapse_idle_turns()
    return f"no tools from this area for {n}+ agent turns"


def collapse_replaced_reason(new_skill_id: str) -> str:
    return (
        f"replaced by {new_skill_id} — only one expanded skill playbook at a time"
    )


def collapse_manual_unload_reason() -> str:
    return "unloaded via skills.unload"


def collapse_persist_reason() -> str:
    return (
        "saved to session history without full playbook "
        "(still active this chat session until reset or idle)"
    )


def collapse_all_expanded_skills(
    messages: list[dict[str, Any]],
    *,
    reason: str | None = None,
) -> list[str]:
    reason = reason or collapse_persist_reason()
    collapsed: list[str] = []
    for skill_id in list(expanded_skill_ids_in_messages(messages)):
        if collapse_skill_in_messages(messages, skill_id, reason=reason):
            collapsed.append(skill_id)
    return collapsed


def compact_expanded_skills_inplace(messages: list[dict[str, Any]]) -> int:
    """Legacy hook — expanded skills stay in chat history until replace or unload."""
    return 0


def sanitize_expanded_skills_for_context(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    import copy

    return copy.deepcopy(messages)


def collapse_skill_in_messages(
    messages: list[dict[str, Any]],
    skill_id: str,
    *,
    reason: str,
) -> bool:
    collapsed = False
    replacement = build_collapsed_skill_content(skill_id, reason=reason)
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        if parse_expanded_skill_id(content) != skill_id:
            continue
        message["content"] = replacement
        collapsed = True
    if collapsed:
        unmark_skill_loaded(skill_id)
        logger.info("skill_collapse skill_id=%s reason=%s", skill_id, reason)
    return collapsed


def expanded_skill_ids_in_messages(messages: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        skill_id = parse_expanded_skill_id(content)
        if skill_id:
            found.add(skill_id)
    return found


class SkillContextCollapser:
    """Collapse expanded skill playbooks when idle or replaced by a new load."""

    def __init__(self) -> None:
        self._expanded: set[str] = set()
        self._last_used_turn: dict[str, int] = {}

    def sync_from_messages(self, messages: list[dict[str, Any]], *, turn_index: int = 0) -> None:
        self._expanded = expanded_skill_ids_in_messages(messages)
        self._last_used_turn = {skill_id: turn_index for skill_id in self._expanded}

    def on_skill_expanded(self, skill_id: str, turn_index: int) -> None:
        self._expanded.add(skill_id)
        self._last_used_turn[skill_id] = turn_index

    def on_tool_use(self, skill_id: str | None, turn_index: int) -> None:
        if skill_id and skill_id in self._expanded:
            self._last_used_turn[skill_id] = turn_index

    def collapse_others_for_new_skill(
        self,
        messages: list[dict[str, Any]],
        new_skill_id: str,
        *,
        turn_index: int,
    ) -> list[str]:
        collapsed: list[str] = []
        for skill_id in list(self._expanded):
            if skill_id == new_skill_id:
                continue
            if collapse_skill_in_messages(
                messages,
                skill_id,
                reason=collapse_replaced_reason(new_skill_id),
            ):
                self._expanded.discard(skill_id)
                self._last_used_turn.pop(skill_id, None)
                collapsed.append(skill_id)
        return collapsed

    def collapse_idle_if_needed(
        self,
        messages: list[dict[str, Any]],
        turn_index: int,
    ) -> list[str]:
        return []

    def primary_expanded_skill_id(self) -> str | None:
        if not self._expanded:
            return None
        return sorted(self._expanded)[0]

    def collapse_skill(
        self,
        messages: list[dict[str, Any]],
        skill_id: str,
        *,
        reason: str,
    ) -> bool:
        collapsed = collapse_skill_in_messages(messages, skill_id, reason=reason)
        if collapsed:
            self._expanded.discard(skill_id)
            self._last_used_turn.pop(skill_id, None)
            return True
        from skills.pending import is_skill_loaded, unmark_skill_loaded

        if is_skill_loaded(skill_id):
            unmark_skill_loaded(skill_id)
            self._expanded.discard(skill_id)
            self._last_used_turn.pop(skill_id, None)
            return True
        return False

    def record_tool_uses_from_results(
        self,
        tool_results: list[str],
        turn_index: int,
    ) -> None:
        for result in tool_results:
            try:
                payload = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                continue
            if payload.get("ok") is not True:
                continue
            tool_name = str(payload.get("tool_name") or "").strip()
            if not tool_name:
                continue
            self.on_tool_use(skill_id_for_tool_name(tool_name), turn_index)
