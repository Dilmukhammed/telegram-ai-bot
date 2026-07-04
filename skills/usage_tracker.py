from __future__ import annotations

import contextvars

from skills.skill_map import skill_id_for_tool_name

# Per agent run: skill_id → set of distinct tool names used this run.
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


def distinct_tools_in_run(skill_id: str) -> int:
    return len(_run_tools.get().get(skill_id, set()))


def run_tools_for_skill(skill_id: str) -> set[str]:
    return set(_run_tools.get().get(skill_id, set()))


def skills_with_tools_this_run() -> set[str]:
    return set(_run_tools.get().keys())
