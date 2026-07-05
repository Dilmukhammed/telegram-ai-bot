from __future__ import annotations

# Tool name prefix → skills.load skill_id (shared by hints and auto-load).
_TOOL_PREFIX_TO_SKILL_ID: tuple[tuple[str, str], ...] = (
    ("google.maps.", "google.maps"),
    ("google.drive.", "google.drive"),
    ("google.sheets.", "google.sheets"),
    ("google.calendar.", "google.calendar"),
    ("google.tasks.", "google.tasks"),
    ("google.gmail.", "google.gmail"),
    ("yandex.auth.", "yandex.music"),
    ("yandex.music.", "yandex.music"),
    ("workspace.", "workspace"),
)

GROUP_SKILL_IDS: dict[str, str] = {
    "google|maps": "google.maps",
    "google|drive": "google.drive",
    "google|sheets": "google.sheets",
    "google|calendar": "google.calendar",
    "google|tasks": "google.tasks",
    "google|gmail": "google.gmail",
    "yandex|music": "yandex.music",
    "yandex|auth": "yandex.music",
    "workspace|filesystem": "workspace",
}


def skill_id_for_tool_name(tool_name: str) -> str | None:
    for prefix, skill_id in _TOOL_PREFIX_TO_SKILL_ID:
        if tool_name.startswith(prefix):
            return skill_id
    return None


def skill_id_for_group_key(group_key: str) -> str | None:
    return GROUP_SKILL_IDS.get(group_key)


def skill_id_for_search_tags(tags: list[str] | None) -> str | None:
    """Map search_tools tags (AND filter) to a skill area; longest tag-set match wins."""
    if not tags:
        return None
    tag_set = {str(tag).strip().lower() for tag in tags if str(tag).strip()}
    if not tag_set:
        return None

    best_skill: str | None = None
    best_size = -1
    for group_key, skill_id in GROUP_SKILL_IDS.items():
        group_tags = frozenset(group_key.split("|"))
        if group_tags <= tag_set and len(group_tags) > best_size:
            best_skill = skill_id
            best_size = len(group_tags)
    return best_skill
