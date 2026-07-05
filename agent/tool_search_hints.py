from __future__ import annotations

import json

from skills.auto_load import auto_load_distinct_threshold
from skills.pending import is_skill_loaded
from skills.skill_map import skill_id_for_group_key
from skills.usage_tracker import distinct_tools_in_run

# Prefix → catalog tags for search_tools (same families as agent/prompts.py).
_TOOL_GROUP_TAGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("skills.", ("skills", "agent")),
    ("google.auth.", ("google", "auth")),
    ("google.calendar.", ("google", "calendar")),
    ("google.gmail.", ("google", "gmail")),
    ("google.drive.", ("google", "drive")),
    ("google.sheets.", ("google", "sheets")),
    ("google.tasks.", ("google", "tasks")),
    ("google.maps.", ("google", "maps")),
    ("yandex.auth.", ("yandex", "auth")),
    ("yandex.music.", ("yandex", "music")),
    ("exa.", ("web", "search")),
    ("telegram.", ("telegram", "bot")),
    ("workspace.", ("workspace", "filesystem")),
)


def tags_for_tool_name(tool_name: str) -> tuple[str, ...] | None:
    for prefix, tags in _TOOL_GROUP_TAGS:
        if tool_name.startswith(prefix):
            return tags
    return None


def group_key_for_tool_name(tool_name: str) -> str | None:
    tags = tags_for_tool_name(tool_name)
    if not tags:
        return None
    return "|".join(tags)


def build_search_tools_hint(tags: tuple[str, ...]) -> str:
    tags_json = json.dumps(list(tags), ensure_ascii=False)
    area = tags[-1] if tags else "tools"
    return (
        f"For accurate search_tools results in this {area} area, always pass "
        f"tags={tags_json} (AND filter). Without tags, rank/catalog can miss the "
        f"right tools or mix unrelated ones. "
        f'Rank example: {{"mode":"rank","query":"<capability>","tags":{tags_json}}}. '
        f'Catalog example: {{"mode":"catalog","tags":{tags_json}}}.'
    )


def build_skill_load_hint(skill_id: str) -> str:
    return (
        f"A full workflow playbook is available for this area (skill_id={skill_id}). "
        f"If it is not already in context, call use_tool skills.load with "
        f'{{"skill_id":"{skill_id}"}} before more tools in this area — '
        f"or the server auto-loads after {auto_load_distinct_threshold()}+ distinct tools in that area."
    )


def maybe_append_tool_search_hint(result_json: str, *, hinted_groups: set[str]) -> str:
    """Append a one-time-per-group search_tools hint to successful use_tool results."""
    try:
        payload = json.loads(result_json)
    except json.JSONDecodeError:
        return result_json

    if not payload.get("ok"):
        return result_json

    tool_name = str(payload.get("tool_name") or "")
    group_key = group_key_for_tool_name(tool_name)
    if not group_key or group_key in hinted_groups:
        return result_json

    tags = tags_for_tool_name(tool_name)
    if not tags:
        return result_json

    hinted_groups.add(group_key)
    payload["search_tools_hint"] = build_search_tools_hint(tags)
    return json.dumps(payload, ensure_ascii=False)


def maybe_append_skill_load_hint(result_json: str, *, hinted_skill_groups: set[str]) -> str:
    """Append skills.load hint after 2+ distinct tools in the same area this run."""
    try:
        payload = json.loads(result_json)
    except json.JSONDecodeError:
        return result_json

    if not payload.get("ok"):
        return result_json

    tool_name = str(payload.get("tool_name") or "")
    if tool_name.startswith("skills."):
        return result_json

    group_key = group_key_for_tool_name(tool_name)
    if not group_key or group_key in hinted_skill_groups:
        return result_json

    skill_id = skill_id_for_group_key(group_key)
    if not skill_id or is_skill_loaded(skill_id):
        return result_json

    if distinct_tools_in_run(skill_id) < auto_load_distinct_threshold():
        return result_json

    hinted_skill_groups.add(group_key)
    payload["skill_load_hint"] = build_skill_load_hint(skill_id)
    return json.dumps(payload, ensure_ascii=False)


def maybe_append_tool_hints(
    result_json: str,
    *,
    hinted_search_groups: set[str],
    hinted_skill_groups: set[str],
) -> str:
    result = maybe_append_tool_search_hint(result_json, hinted_groups=hinted_search_groups)
    return maybe_append_skill_load_hint(result, hinted_skill_groups=hinted_skill_groups)
