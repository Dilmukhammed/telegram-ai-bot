from __future__ import annotations

# Tool name prefix → skills.load skill_id (shared by hints and auto-load).
_TOOL_PREFIX_TO_SKILL_ID: tuple[tuple[str, str], ...] = (
    ("google.maps.", "google.maps"),
    ("google.drive.", "google.drive"),
    ("google.sheets.", "google.sheets"),
    ("google.calendar.", "google.calendar"),
    ("google.tasks.", "google.tasks"),
    ("google.gmail.", "google.gmail"),
    ("workspace.", "workspace"),
)

GROUP_SKILL_IDS: dict[str, str] = {
    "google|maps": "google.maps",
    "google|drive": "google.drive",
    "google|sheets": "google.sheets",
    "google|calendar": "google.calendar",
    "google|tasks": "google.tasks",
    "google|gmail": "google.gmail",
    "workspace|filesystem": "workspace",
}


def skill_id_for_tool_name(tool_name: str) -> str | None:
    for prefix, skill_id in _TOOL_PREFIX_TO_SKILL_ID:
        if tool_name.startswith(prefix):
            return skill_id
    return None


def skill_id_for_group_key(group_key: str) -> str | None:
    return GROUP_SKILL_IDS.get(group_key)
