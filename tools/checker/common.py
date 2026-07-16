from __future__ import annotations

import fnmatch
from typing import Any

from tools.schema import ToolSpec
from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_USER_GOAL,
    EvidenceRef,
)

_USER_GOAL = EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal")

_COMMON_ID_FIELDS: tuple[str, ...] = (
    "calendar_id",
    "event_id",
    "spreadsheet_id",
    "sheet_id",
    "range",
    "ranges",
    "message_id",
    "thread_id",
    "draft_id",
    "file_id",
    "drive_id",
    "task_id",
    "tasklist_id",
    "place_id",
    "path",
    "from_path",
    "to_path",
    "file_ref",
    "track_id",
    "album_id",
    "artist_id",
    "playlist_uuid",
    "label_id",
    "permission_id",
    "comment_id",
    "draft_id",
    "query",
    "q",
    "text_query",
    "address",
    "origin",
    "destination",
)

CHECKER_EXCLUDED_PATTERNS: tuple[str, ...] = (
    "echo.*",
    "coach.*",
    "agent.wait",
    "tool_results.*",
    "skills.*",
    "google.auth.*",
    "yandex.auth.*",
    "browser.profile.*",
    "browser.session.*",
)


def is_checker_excluded(spec: ToolSpec) -> bool:
    if not spec.checker_enabled:
        return True
    return any(fnmatch.fnmatchcase(spec.name, pattern) for pattern in CHECKER_EXCLUDED_PATTERNS)


def infer_call_fields(spec: ToolSpec) -> tuple[str, ...]:
    props = spec.parameters.get("properties") or {}
    if not isinstance(props, dict):
        props = {}
    required = spec.parameters.get("required") or []
    if not isinstance(required, list):
        required = []
    fields: list[str] = []
    for key in required:
        if isinstance(key, str) and key in props:
            fields.append(key)
    for key in _COMMON_ID_FIELDS:
        if key in props and key not in fields:
            fields.append(key)
    if not fields:
        fields = [key for key in list(props.keys())[:8] if isinstance(key, str)]
    return tuple(fields[:14])


def call_evidence(spec: ToolSpec, *, label: str | None = None) -> EvidenceRef:
    suffix = spec.name.rsplit(".", 1)[-1]
    return EvidenceRef(
        kind=EVIDENCE_CALL,
        fields=infer_call_fields(spec),
        label=label or f"{suffix}_call",
    )


def prior_family_context(spec: ToolSpec, *, label: str | None = None) -> EvidenceRef:
    prefix = spec.name.rsplit(".", 1)[0] + ".*"
    return EvidenceRef(
        kind=EVIDENCE_PRIOR_TOOL,
        tool_name_pattern=prefix,
        optional=True,
        max_age_steps=10,
        label=label or "prior_family_context",
    )


def prior_matched(
    spec: ToolSpec,
    *,
    tool_names: tuple[str, ...],
    match: tuple[tuple[str, str], ...],
    label: str,
) -> EvidenceRef:
    return EvidenceRef(
        kind=EVIDENCE_PRIOR_TOOL,
        tool_names=tool_names,
        match=match,
        optional=True,
        max_age_steps=10,
        label=label,
    )


def prior_spreadsheet_read() -> EvidenceRef:
    return EvidenceRef(
        kind=EVIDENCE_PRIOR_TOOL,
        tool_names=(
            "google.sheets.get_values",
            "google.sheets.read_sheet",
            "google.sheets.batch_get_values",
            "google.sheets.get_spreadsheet",
        ),
        match=(("spreadsheet_id", "$call.spreadsheet_id"),),
        optional=True,
        max_age_steps=10,
        label="prior_sheet_read",
    )


def prior_gmail_context() -> EvidenceRef:
    return EvidenceRef(
        kind=EVIDENCE_PRIOR_TOOL,
        tool_names=(
            "google.gmail.get_message",
            "google.gmail.get_thread",
            "google.gmail.search_messages",
            "google.gmail.list_inbox",
            "google.gmail.list_threads",
            "google.gmail.list_messages",
        ),
        optional=True,
        max_age_steps=10,
        label="prior_gmail_context",
    )


def prior_message_for_call() -> EvidenceRef:
    return EvidenceRef(
        kind=EVIDENCE_PRIOR_TOOL,
        tool_names=(
            "google.gmail.get_message",
            "google.gmail.get_thread",
            "google.gmail.search_messages",
        ),
        match=(("message_id", "$call.message_id"),),
        optional=True,
        max_age_steps=10,
        label="prior_message_read",
    )


def prior_drive_file() -> EvidenceRef:
    return EvidenceRef(
        kind=EVIDENCE_PRIOR_TOOL,
        tool_names=("google.drive.get_file", "google.drive.search_files", "google.drive.list_files"),
        match=(("file_id", "$call.file_id"),),
        optional=True,
        max_age_steps=10,
        label="prior_drive_file_read",
    )


def prior_calendar_event() -> EvidenceRef:
    return EvidenceRef(
        kind=EVIDENCE_PRIOR_TOOL,
        tool_names=("google.calendar.get_event", "google.calendar.list_events", "google.calendar.search_events"),
        match=(("event_id", "$call.event_id"),),
        optional=True,
        max_age_steps=10,
        label="prior_event_read",
    )


def prior_task() -> EvidenceRef:
    return EvidenceRef(
        kind=EVIDENCE_PRIOR_TOOL,
        tool_names=("google.tasks.get_task", "google.tasks.list_tasks", "google.tasks.search_tasks"),
        match=(("task_id", "$call.task_id"),),
        optional=True,
        max_age_steps=10,
        label="prior_task_read",
    )


def prior_workspace_path() -> EvidenceRef:
    return EvidenceRef(
        kind=EVIDENCE_PRIOR_TOOL,
        tool_names=(
            "workspace.stat",
            "workspace.read_file",
            "workspace.list_dir",
            "workspace.find",
        ),
        match=(("path", "$call.path"),),
        optional=True,
        max_age_steps=10,
        label="prior_workspace_path",
    )


def has_param(spec: ToolSpec, name: str) -> bool:
    props = spec.parameters.get("properties") or {}
    return isinstance(props, dict) and name in props


def has_confirm(spec: ToolSpec) -> bool:
    return has_param(spec, "confirm")


def is_read_tool(spec: ToolSpec) -> bool:
    return "read" in spec.tags


def is_write_tool(spec: ToolSpec) -> bool:
    return "write" in spec.tags


def is_search_tool(spec: ToolSpec) -> bool:
    return "search" in spec.tags or spec.name.startswith(("exa.", "google.maps.places_", "google.gmail.search_"))


def target_id_fields(spec: ToolSpec) -> tuple[str, ...]:
    props = spec.parameters.get("properties") or {}
    if not isinstance(props, dict):
        return ()
    return tuple(field for field in _COMMON_ID_FIELDS if field in props and field.endswith("_id"))
