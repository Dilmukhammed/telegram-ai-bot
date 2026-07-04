from __future__ import annotations

from typing import Any

from tools.builtins.google.drive_urls import (
    label_for_drive_url,
    normalize_drive_url,
    parse_file_id_from_url,
    truncate_drive_button_label,
)
from tools.builtins.google.sheets_serialize import SPREADSHEET_MIME

DRIVE_MAX_BUTTONS = 5
DRIVE_PAIR_WHEN_MORE_THAN = 1

TOOL_INGEST_URL_KEYS: tuple[str, ...] = (
    "web_view_link",
    "url",
    "web_content_link",
)


def group_key_for_drive_url(
    url: str,
    *,
    mime_type: str | None = None,
) -> str:
    normalized = normalize_drive_url(url)
    file_id = parse_file_id_from_url(normalized)
    if file_id:
        return f"file:{file_id}"
    return f"url:{normalized}"


def label_for_drive_file(
    *,
    name: str | None = None,
    url: str | None = None,
    mime_type: str | None = None,
    title: str | None = None,
) -> str:
    resolved_name = name or title
    if url:
        return label_for_drive_url(url, name=resolved_name, mime_type=mime_type)
    if resolved_name and str(resolved_name).strip():
        return truncate_drive_button_label(str(resolved_name).strip())
    return label_for_drive_url("", mime_type=mime_type)


def label_for_drive_tool(
    tool_name: str,
    result: dict[str, Any],
    *,
    url: str = "",
    name: str | None = None,
    mime_type: str | None = None,
    title: str | None = None,
) -> str:
    spreadsheet = result.get("spreadsheet")
    if isinstance(spreadsheet, dict):
        title = title or spreadsheet.get("title")
        mime_type = mime_type or SPREADSHEET_MIME
        url = url or str(spreadsheet.get("url") or "")

    if tool_name.startswith("google.sheets."):
        return label_for_drive_file(name=name, url=url, mime_type=mime_type or SPREADSHEET_MIME, title=title)

    if tool_name == "google.drive.search_files":
        if name and str(name).strip():
            return truncate_drive_button_label(str(name).strip())
        return label_for_drive_url(url, mime_type=mime_type)

    if tool_name in {"google.drive.create_folder", "google.drive.get_shared_drive"}:
        return label_for_drive_file(name=name or title, url=url, mime_type=mime_type or "application/vnd.google-apps.folder")

    return label_for_drive_file(name=name, url=url, mime_type=mime_type, title=title)


def button_sort_key(group_key: str, label: str) -> tuple[int, str]:
    prefix = group_key.split(":", 1)[0]
    url_rank = 1 if prefix == "url" else 0
    return (url_rank, label.casefold())
