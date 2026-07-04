from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from config import get_settings
from skills.collapse import (
    SKILL_COLLAPSED_PREFIX,
    SKILL_LOADED_PREFIX,
    SkillContextCollapser,
    collapse_manual_unload_reason,
)
from skills.pending import (
    is_skill_loaded,
    mark_skill_loaded,
    push_pending_skill,
    take_pending_skill_unloads,
    take_pending_skills,
)
from skills.registry import get_skill
from skills.skill_map import skill_id_for_tool_name
from skills.usage_tracker import (
    distinct_tools_in_run,
    reset_skill_usage_tracker,
    run_tools_for_skill,
)

_SKILL_LOADED_LINE_RE = re.compile(r"^\[Skill loaded:\s*([^\]]+)\]", re.MULTILINE)


def auto_load_distinct_threshold() -> int:
    """Min distinct tools in one skill area before auto-load (SKILLS_AUTO_LOAD_DISTINCT_TOOLS)."""
    return max(1, get_settings().skills_auto_load_distinct_tools)

# Short follow-up in an ongoing area (separate user messages).
_FOLLOW_UP_RE = re.compile(
    r"(^а\s|^\s*и\s|ещё|еще|тоже|его|её|ее|туда|там|завтра|послезавтра|"
    r"сегодня|now|that|this|it\b|reply|ответ|перенес|отмен|удали|добав)",
    re.IGNORECASE,
)


def mark_skills_loaded_from_history(history: list[dict[str, Any]] | None) -> None:
    if not history:
        return
    for message in history:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        if content.startswith(SKILL_COLLAPSED_PREFIX):
            continue
        if not content.startswith(SKILL_LOADED_PREFIX):
            continue
        first_line = content.split("\n", 1)[0]
        match = _SKILL_LOADED_LINE_RE.match(first_line.strip())
        if match:
            mark_skill_loaded(match.group(1).strip())


def extract_tool_names_from_history(history: list[dict[str, Any]] | None) -> list[str]:
    names: list[str] = []
    if not history:
        return names

    for message in history:
        role = message.get("role")
        if role == "assistant":
            for tool_call in message.get("tool_calls") or []:
                function = tool_call.get("function") or {}
                if function.get("name") != "use_tool":
                    continue
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    continue
                tool_name = str(arguments.get("tool_name") or "").strip()
                if tool_name:
                    names.append(tool_name)
        elif role == "tool":
            try:
                payload = json.loads(message.get("content") or "{}")
            except json.JSONDecodeError:
                continue
            tool_name = str(payload.get("tool_name") or "").strip()
            if tool_name:
                names.append(tool_name)
    return names


def distinct_tools_by_skill_from_history(
    history: list[dict[str, Any]] | None,
) -> dict[str, set[str]]:
    by_skill: dict[str, set[str]] = defaultdict(set)
    for tool_name in extract_tool_names_from_history(history):
        skill_id = skill_id_for_tool_name(tool_name)
        if skill_id:
            by_skill[skill_id].add(tool_name)
    return dict(by_skill)


def _is_follow_up_message(user_message: str) -> bool:
    text = user_message.strip()
    if not text:
        return False
    if len(text) > 160:
        return False
    return bool(_FOLLOW_UP_RE.search(text))


def should_auto_load_skill(
    skill_id: str,
    *,
    history: list[dict[str, Any]] | None,
    user_message: str = "",
) -> bool:
    """True when multi-step work in skill_id is established (not a one-off tool)."""
    history_tools = distinct_tools_by_skill_from_history(history).get(skill_id, set())
    total_distinct = len(history_tools | run_tools_for_skill(skill_id))

    if total_distinct >= auto_load_distinct_threshold():
        return True

    # Second user message in same area: one tool already used + short follow-up.
    if len(history_tools) >= 1 and distinct_tools_in_run(skill_id) == 0 and _is_follow_up_message(
        user_message
    ):
        return True

    return False


def decide_auto_load_skill_ids(
    user_message: str,
    history: list[dict[str, Any]] | None,
) -> list[str]:
    """Skills to inject at run start — only when history already shows multi-step work."""
    by_skill = distinct_tools_by_skill_from_history(history)
    candidates: set[str] = set()

    for skill_id, tools in by_skill.items():
        if len(tools) >= auto_load_distinct_threshold():
            candidates.add(skill_id)
        elif len(tools) >= 1 and _is_follow_up_message(user_message):
            candidates.add(skill_id)

    ordered = sorted(candidates)
    to_load: list[str] = []
    for skill_id in ordered:
        if is_skill_loaded(skill_id):
            continue
        if get_skill(skill_id) is None:
            continue
        to_load.append(skill_id)
    return to_load


def queue_skill_load(skill_id: str) -> bool:
    if is_skill_loaded(skill_id):
        return False
    spec = get_skill(skill_id)
    if spec is None:
        return False
    mark_skill_loaded(skill_id)
    push_pending_skill(skill_id, spec.content)
    return True


def maybe_auto_load_after_tool(
    tool_name: str,
    *,
    history: list[dict[str, Any]] | None,
) -> str | None:
    """Load skill once area has enough distinct tools (caller must record_tool_use first)."""
    skill_id = skill_id_for_tool_name(tool_name)
    if not skill_id or is_skill_loaded(skill_id):
        return None
    if not should_auto_load_skill(skill_id, history=history):
        return None
    if queue_skill_load(skill_id):
        return skill_id
    return None


def auto_load_skills_for_run(
    user_message: str,
    history: list[dict[str, Any]] | None,
) -> list[str]:
    mark_skills_loaded_from_history(history)
    loaded: list[str] = []
    for skill_id in decide_auto_load_skill_ids(user_message, history):
        if queue_skill_load(skill_id):
            loaded.append(skill_id)
    return loaded


def append_pending_skills_to_messages(
    messages: list[dict[str, Any]],
    collapser: SkillContextCollapser | None = None,
    *,
    turn_index: int = 0,
) -> list[str]:
    loaded: list[str] = []
    for skill_id, skill_content in take_pending_skills():
        if collapser is not None:
            collapser.collapse_others_for_new_skill(
                messages,
                skill_id,
                turn_index=turn_index,
            )
        messages.append(
            {
                "role": "user",
                "content": f"[Skill loaded: {skill_id}]\n\n{skill_content}",
            }
        )
        if collapser is not None:
            collapser.on_skill_expanded(skill_id, turn_index)
        loaded.append(skill_id)
    return loaded


def apply_pending_skill_unloads(
    messages: list[dict[str, Any]],
    collapser: SkillContextCollapser | None = None,
) -> list[str]:
    unloaded: list[str] = []
    reason = collapse_manual_unload_reason()
    for skill_id in take_pending_skill_unloads():
        if collapser is not None:
            if collapser.collapse_skill(messages, skill_id, reason=reason):
                unloaded.append(skill_id)
        else:
            from skills.collapse import collapse_skill_in_messages

            if collapse_skill_in_messages(messages, skill_id, reason=reason):
                unloaded.append(skill_id)
    return unloaded


def reset_auto_load_run_state() -> None:
    reset_skill_usage_tracker()
