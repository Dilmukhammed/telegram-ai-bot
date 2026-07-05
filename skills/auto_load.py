from __future__ import annotations

import re
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
from skills.usage_tracker import distinct_tools_in_run, reset_skill_usage_tracker

_SKILL_LOADED_LINE_RE = re.compile(r"^\[Skill loaded:\s*([^\]]+)\]", re.MULTILINE)


def auto_load_distinct_threshold() -> int:
    """Min distinct tools in one skill area before auto-load (SKILLS_AUTO_LOAD_DISTINCT_TOOLS)."""
    return max(1, get_settings().skills_auto_load_distinct_tools)


def auto_load_status_message(skill_id: str) -> str:
    return f"Автозагрузка skill: {skill_id}…"


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


def prepare_skills_for_run(history: list[dict[str, Any]] | None) -> None:
    """Sync in-run loaded-skill state from expanded playbooks already in chat history."""
    mark_skills_loaded_from_history(history)


def should_auto_load_skill(skill_id: str) -> bool:
    """True after enough distinct use_tool or tagged search_tools activity this run."""
    return distinct_tools_in_run(skill_id) >= auto_load_distinct_threshold()


def queue_skill_load(skill_id: str) -> bool:
    if is_skill_loaded(skill_id):
        return False
    spec = get_skill(skill_id)
    if spec is None:
        return False
    mark_skill_loaded(skill_id)
    push_pending_skill(skill_id, spec.content)
    return True


def maybe_auto_load_for_skill(skill_id: str | None) -> str | None:
    if not skill_id or is_skill_loaded(skill_id):
        return None
    if not should_auto_load_skill(skill_id):
        return None
    if queue_skill_load(skill_id):
        return skill_id
    return None


def maybe_auto_load_after_tool(tool_name: str) -> str | None:
    """Load skill once area has enough activity this run (record_tool_use first)."""
    return maybe_auto_load_for_skill(skill_id_for_tool_name(tool_name))


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
