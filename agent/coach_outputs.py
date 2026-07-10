"""Structured 'already produced' summary for the trajectory coach.

The coach kept telling the worker to redo finished work because done-tracking only
covered Google Sheets. This module builds a general, always-present list of concrete
artifacts the worker has produced this run (calendar events, drive files, gmail sends,
pdf/workspace files, spreadsheets, telegram deliveries, ...), extracted from successful
tool results. It survives cycle-log truncation because it lives in the trace header.
"""

from __future__ import annotations

import json
from typing import Any

from agent.run_trace import ToolStep

# Mutating / output-producing tools grouped into human categories. Read-only tools
# (search, list, get, read, download-to-context) are intentionally excluded.
_CALENDAR_WRITE = frozenset(
    {
        "google.calendar.create_event",
        "google.calendar.quick_add_event",
        "google.calendar.patch_event",
        "google.calendar.update_event",
        "google.calendar.move_event",
        "google.calendar.delete_event",
    }
)

_DRIVE_WRITE = frozenset(
    {
        "google.drive.create_folder",
        "google.drive.create_file",
        "google.drive.upload_file",
        "google.drive.update_file_content",
        "google.drive.copy_file",
        "google.drive.move_file",
        "google.drive.rename_file",
        "google.drive.create_shortcut",
        "google.drive.trash_file",
        "google.drive.delete_file",
        "google.drive.share_file",
    }
)

_GMAIL_WRITE = frozenset(
    {
        "google.gmail.send_message",
        "google.gmail.reply_to_message",
        "google.gmail.forward_message",
        "google.gmail.send_draft",
        "google.gmail.create_draft",
        "google.gmail.import_message",
    }
)

_WORKSPACE_WRITE = frozenset(
    {
        "workspace.write_file",
        "workspace.append_file",
        "workspace.mkdir",
        "workspace.move",
        "workspace.copy",
        "workspace.unzip",
        "workspace.import_from_file_ref",
    }
)

_SHEETS_CREATE = frozenset(
    {
        "google.sheets.create_spreadsheet",
        "google.sheets.add_sheet",
    }
)

_TELEGRAM_SEND = frozenset({"telegram.send_file"})

_YANDEX_DOWNLOAD = frozenset({"yandex.music.track_download"})


def _parse_payload(result_json: str | None) -> dict[str, Any]:
    if not result_json:
        return {}
    try:
        payload = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _inner_result(payload: dict[str, Any]) -> dict[str, Any]:
    inner = payload.get("result")
    if isinstance(inner, dict) and ("tool_name" in payload or "ok" in payload):
        return inner
    return payload


def _clip(value: Any, limit: int = 60) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _first(source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if isinstance(value, dict):
            nested = value.get("id") or value.get("name") or value.get("title")
            if nested:
                return str(nested)
        elif value not in (None, "", [], {}):
            return str(value)
    return ""


def _pdf_is_write(tool: str) -> bool:
    if not tool.startswith("pdf."):
        return False
    write_verbs = (
        "create",
        "merge",
        "split",
        "overlay",
        "fill_form",
        "flatten_form",
        "redact",
        "add_image",
        "add_annotations",
        "encrypt",
        "decrypt",
        "optimize",
        "repair",
        "rotate",
        "delete_pages",
        "reorder",
        "extract_pages",
        "set_metadata",
        "set_outline",
        "add_bookmark",
        "reset_form",
    )
    return any(verb in tool for verb in write_verbs)


def _describe(step: ToolStep) -> tuple[str, str] | None:
    """Return (category, one-item descriptor) for a successful mutating step."""
    tool = step.target_tool or ""
    if not tool or step.result_ok is not True:
        return None

    payload = _parse_payload(step.result_json)
    result = _inner_result(payload)
    args = step.arguments_normalized or {}

    if tool in _CALENDAR_WRITE:
        if tool == "google.calendar.delete_event":
            eid = _first(args, "event_id") or _first(result, "event_id", "id")
            return ("Calendar", f"deleted {eid or 'event'}")
        event = result.get("event") if isinstance(result.get("event"), dict) else result
        summary = _first(event, "summary") or _first(args, "summary", "text")
        eid = _first(event, "id", "event_id")
        label = _clip(summary) or "event"
        return ("Calendar", f'"{label}"' + (f" (id={eid})" if eid else ""))

    if tool in _SHEETS_CREATE:
        title = _first(result, "title", "name") or _first(args, "title")
        sid = _first(result, "spreadsheet_id", "spreadsheetId", "id")
        if tool == "google.sheets.add_sheet":
            tab = _first(result, "title") or _first(args, "title")
            return ("Spreadsheets", f"tab {_clip(tab) or '?'}")
        return ("Spreadsheets", f'"{_clip(title) or "spreadsheet"}"' + (f" (id={sid})" if sid else ""))

    if tool in _DRIVE_WRITE:
        verb = tool.rsplit(".", 1)[-1].replace("_file", "").replace("_", " ")
        name = _first(result, "name", "title", "filename") or _first(args, "name", "title")
        fid = _first(result, "id", "file_id", "fileId")
        desc = f"{verb} {_clip(name) or ''}".strip()
        return ("Drive", desc + (f" (id={fid})" if fid else ""))

    if tool in _GMAIL_WRITE:
        to = _first(result, "to") or _first(args, "to")
        subject = _first(result, "subject") or _first(args, "subject")
        mid = _first(result, "message_id", "messageId", "id")
        verb = "draft" if "draft" in tool else "sent"
        parts = [verb]
        if to:
            parts.append(f"to {_clip(to, 40)}")
        if subject:
            parts.append(f'"{_clip(subject, 40)}"')
        if mid and not to and not subject:
            parts.append(f"id={mid}")
        return ("Gmail", " ".join(parts))

    if tool in _WORKSPACE_WRITE:
        path = _first(result, "path") or _first(args, "path")
        verb = tool.rsplit(".", 1)[-1]
        return ("Files", f"{verb} {_clip(path, 80) or '?'}")

    if _pdf_is_write(tool):
        path = _first(result, "path", "output_path") or _first(args, "output_path", "path")
        return ("Files", f"pdf {_clip(path, 80) or tool.rsplit('.', 1)[-1]}")

    if tool in _TELEGRAM_SEND:
        path = _first(result, "path", "filename", "file_ref") or _first(args, "path", "file_ref")
        return ("Delivered", f"telegram {_clip(path, 60) or 'file'}")

    if tool in _YANDEX_DOWNLOAD:
        path = _first(result, "path") or _first(args, "path")
        title = _first(result, "title")
        return ("Files", f"track {_clip(title or path, 60) or '?'}")

    return None


def format_outputs_produced(steps: list[ToolStep], *, per_category: int = 8) -> str:
    """Concrete artifacts already produced this run, grouped by category.

    Sheets *data writes* are covered separately by ``format_sheets_progress``; this
    covers everything else (and spreadsheet/tab creation)."""
    grouped: dict[str, list[str]] = {}
    for step in steps:
        described = _describe(step)
        if described is None:
            continue
        category, item = described
        bucket = grouped.setdefault(category, [])
        if item not in bucket:
            bucket.append(item)

    if not grouped:
        return ""

    order = ["Spreadsheets", "Calendar", "Gmail", "Drive", "Files", "Delivered"]
    lines = ["Outputs already produced this run (DONE — do not ask to redo these):"]
    for category in [*order, *[c for c in grouped if c not in order]]:
        items = grouped.get(category)
        if not items:
            continue
        shown = items[:per_category]
        suffix = f" (+{len(items) - per_category} more)" if len(items) > per_category else ""
        lines.append(f"- {category}: {'; '.join(shown)}{suffix}")
    return "\n".join(lines)
