from __future__ import annotations

from typing import Any

from skills.pending import (
    is_skill_loaded,
    mark_skill_loaded,
    push_pending_skill,
    push_pending_skill_unload,
)
from skills.registry import get_skill, list_skills
from tools.schema import ToolSpec


async def _list_skills_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_tags = arguments.get("tags") or []
    tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else None
    items = list_skills(tags=tags)
    return {
        "count": len(items),
        "skills": [item.to_list_item() for item in items],
    }


async def _load_skill_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    skill_id = str(arguments.get("skill_id", "")).strip()
    if not skill_id:
        raise ValueError("skill_id is required")

    spec = get_skill(skill_id)
    if spec is None:
        available = [item.skill_id for item in list_skills()]
        raise ValueError(f"Unknown skill_id: {skill_id}. Available: {', '.join(available)}")

    if is_skill_loaded(skill_id):
        return {
            "ok": True,
            "skill_id": skill_id,
            "already_loaded": True,
            "message": f"Skill {skill_id} is already loaded in this agent run.",
            "tags": list(spec.tags),
        }

    mark_skill_loaded(skill_id)
    push_pending_skill(skill_id, spec.content)

    return {
        "ok": True,
        "skill_id": skill_id,
        "already_loaded": False,
        "description": spec.description,
        "tags": list(spec.tags),
        "content_chars": len(spec.content),
        "message": (
            f"Skill {skill_id} loaded into agent context. "
            "Follow its workflows for this run."
        ),
    }


async def _unload_skill_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    skill_id = str(arguments.get("skill_id", "")).strip()
    if not skill_id:
        raise ValueError("skill_id is required")

    spec = get_skill(skill_id)
    if spec is None:
        available = [item.skill_id for item in list_skills()]
        raise ValueError(f"Unknown skill_id: {skill_id}. Available: {', '.join(available)}")

    if not is_skill_loaded(skill_id):
        return {
            "ok": True,
            "skill_id": skill_id,
            "already_unloaded": True,
            "message": f"Skill {skill_id} is not expanded in this agent run.",
            "tags": list(spec.tags),
        }

    push_pending_skill_unload(skill_id)

    return {
        "ok": True,
        "skill_id": skill_id,
        "already_unloaded": False,
        "description": spec.description,
        "tags": list(spec.tags),
        "message": (
            f"Skill {skill_id} will be collapsed in context "
            "(same as idle/replace collapse). Use skills.load to restore."
        ),
    }


SKILLS_LIST = ToolSpec(
    name="skills.list",
    description=(
        "List available agent skills (workflow playbooks). "
        "Skills are loaded with skills.load to inject the full SKILL.md into context."
    ),
    parameters={
        "type": "object",
        "properties": {
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional AND filter on skill tags, e.g. [\"google\", \"maps\"].",
            },
        },
    },
    handler=_list_skills_handler,
    tags=("skills", "agent", "read"),
    parallel_safe=True,
    examples=("list available skills", "what skills can I load"),
)

SKILLS_LOAD = ToolSpec(
    name="skills.load",
    description=(
        "Load a full skill playbook (entire SKILL.md) into the agent context for the current run. "
        "Call before multi-step work in an area (e.g. google.maps for routes). "
        "Loading a new skill collapses any other expanded skill (one full playbook at a time). "
        "Idle skills collapse after SKILLS_COLLAPSE_IDLE_TURNS without tools from that area. "
        "The server may auto-load skills when the user message or dialog history clearly targets one domain. "
        "Idempotent — reloading the same skill_id in one run is a no-op."
    ),
    parameters={
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": (
                    "Skill identifier, e.g. google.maps. "
                    "Use skills.list to discover available skills."
                ),
            },
        },
        "required": ["skill_id"],
    },
    handler=_load_skill_handler,
    tags=("skills", "agent", "write"),
    parallel_safe=True,
    examples=("load google maps skill", "load skill google.maps"),
)

SKILLS_UNLOAD = ToolSpec(
    name="skills.unload",
    description=(
        "Collapse an expanded skill playbook in agent context (free tokens). "
        "Same effect as idle or replace collapse — full SKILL.md becomes a short stub. "
        "Use when switching tasks or the playbook is no longer needed this run. "
        "Idempotent if the skill is not currently expanded."
    ),
    parameters={
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": (
                    "Skill identifier to collapse, e.g. google.gmail. "
                    "Use skills.list to discover skill_id values."
                ),
            },
        },
        "required": ["skill_id"],
    },
    handler=_unload_skill_handler,
    tags=("skills", "agent", "write"),
    parallel_safe=True,
    examples=("unload gmail skill", "collapse skill google.maps"),
)

SKILLS_TOOLS: tuple[ToolSpec, ...] = (SKILLS_LIST, SKILLS_LOAD, SKILLS_UNLOAD)
