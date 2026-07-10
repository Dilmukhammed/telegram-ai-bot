from __future__ import annotations

from tools.checker.common import has_param, is_write_tool
from tools.schema import ToolSpec
from tools.verification import EVIDENCE_LIVE_FETCH, EvidenceRef, FETCH_CALENDAR_EVENT_EXISTS, FETCH_CALENDAR_SLOT_CONFLICTS, FETCH_DRIVE_FILE, FETCH_GMAIL_MESSAGE, FETCH_SHEETS_RANGE_VALUES, FETCH_TASKS_GET_TASK, FETCH_WORKSPACE_STAT, FETCH_YANDEX_TRACK


def live_fetch_refs_for_spec(spec: ToolSpec) -> tuple[EvidenceRef, ...]:
    refs: list[EvidenceRef] = []
    name = spec.name

    if name.startswith("google.calendar.") and is_write_tool(spec):
        if has_param(spec, "start") or has_param(spec, "text"):
            refs.append(
                EvidenceRef(
                    kind=EVIDENCE_LIVE_FETCH,
                    fetch=FETCH_CALENDAR_SLOT_CONFLICTS,
                    label="slot_conflicts_live",
                )
            )
        if has_param(spec, "event_id"):
            refs.append(
                EvidenceRef(
                    kind=EVIDENCE_LIVE_FETCH,
                    fetch=FETCH_CALENDAR_EVENT_EXISTS,
                    label="event_exists_live",
                )
            )

    if name.startswith("google.gmail.") and has_param(spec, "message_id"):
        refs.append(
            EvidenceRef(
                kind=EVIDENCE_LIVE_FETCH,
                fetch=FETCH_GMAIL_MESSAGE,
                label="gmail_message_live",
            )
        )

    if name.startswith("google.sheets.") and is_write_tool(spec) and (
        has_param(spec, "range") or has_param(spec, "ranges") or has_param(spec, "data")
    ):
        refs.append(
            EvidenceRef(
                kind=EVIDENCE_LIVE_FETCH,
                fetch=FETCH_SHEETS_RANGE_VALUES,
                label="sheets_range_live",
            )
        )

    if name.startswith("google.drive.") and has_param(spec, "file_id"):
        refs.append(
            EvidenceRef(
                kind=EVIDENCE_LIVE_FETCH,
                fetch=FETCH_DRIVE_FILE,
                label="drive_file_live",
            )
        )

    if name.startswith("google.tasks.") and has_param(spec, "task_id"):
        refs.append(
            EvidenceRef(
                kind=EVIDENCE_LIVE_FETCH,
                fetch=FETCH_TASKS_GET_TASK,
                label="task_exists_live",
            )
        )

    if name.startswith("workspace.") and is_write_tool(spec) and has_param(spec, "path"):
        refs.append(
            EvidenceRef(
                kind=EVIDENCE_LIVE_FETCH,
                fetch=FETCH_WORKSPACE_STAT,
                label="workspace_path_live",
            )
        )

    if name == "yandex.music.track_download" and has_param(spec, "track_id"):
        refs.append(
            EvidenceRef(
                kind=EVIDENCE_LIVE_FETCH,
                fetch=FETCH_YANDEX_TRACK,
                label="yandex_track_live",
            )
        )

    if name == "telegram.send_file" and has_param(spec, "path"):
        refs.append(
            EvidenceRef(
                kind=EVIDENCE_LIVE_FETCH,
                fetch=FETCH_WORKSPACE_STAT,
                label="workspace_path_live",
            )
        )

    return tuple(refs)
