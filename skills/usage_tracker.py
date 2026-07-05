from __future__ import annotations

import contextvars

from skills.skill_map import skill_id_for_search_tags, skill_id_for_tool_name

SEARCH_ACTIVITY_PREFIX = "search_tools:"

# Per agent run: skill_id → distinct activities (use_tool names + tagged searches).
_run_tools: contextvars.ContextVar[dict[str, set[str]]] = contextvars.ContextVar(
    "skill_run_tools",
    default={},
)


def reset_skill_usage_tracker() -> None:
    _run_tools.set({})


def record_tool_use(tool_name: str) -> str | None:
    """Record a successful use_tool; return skill_id if mapped."""
    skill_id = skill_id_for_tool_name(tool_name)
    if not skill_id:
        return None
    current = {key: set(values) for key, values in _run_tools.get().items()}
    current.setdefault(skill_id, set()).add(tool_name)
    _run_tools.set(current)
    return skill_id


def record_tagged_search(tags: list[str]) -> str | None:
    """Record a successful search_tools call with tags; return skill_id if mapped."""
    skill_id = skill_id_for_search_tags(tags)
    if not skill_id:
        return None
    current = {key: set(values) for key, values in _run_tools.get().items()}
    bucket = current.setdefault(skill_id, set())
    index = sum(1 for item in bucket if item.startswith(SEARCH_ACTIVITY_PREFIX))
    bucket.add(f"{SEARCH_ACTIVITY_PREFIX}{index}")
    _run_tools.set(current)
    return skill_id


def distinct_tools_in_run(skill_id: str) -> int:
    return len(_run_tools.get().get(skill_id, set()))


def run_tools_for_skill(skill_id: str) -> set[str]:
    return set(_run_tools.get().get(skill_id, set()))


def skills_with_tools_this_run() -> set[str]:
    return set(_run_tools.get().keys())
