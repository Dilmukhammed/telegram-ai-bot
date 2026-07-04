from __future__ import annotations

from typing import Any

from tools.builtins.google.calendar_urls import (
    is_calendar_event_url,
    label_for_calendar_event,
    label_for_calendar_url,
    normalize_calendar_url,
    parse_event_key_from_url,
    truncate_calendar_button_label,
)

CALENDAR_MAX_BUTTONS = 5

TOOL_INGEST_URL_KEYS: tuple[str, ...] = ("htmlLink",)


def group_key_for_calendar_url(url: str) -> str:
    normalized = normalize_calendar_url(url)
    event_key = parse_event_key_from_url(normalized)
    if event_key:
        return f"event:{event_key}"
    return f"url:{normalized}"


def label_for_calendar_tool(
    tool_name: str,
    result: dict[str, Any],
    *,
    url: str = "",
    summary: str | None = None,
) -> str:
    if summary and str(summary).strip():
        return truncate_calendar_button_label(str(summary).strip())

    event = result.get("event")
    if isinstance(event, dict):
        event_summary = event.get("summary")
        if event_summary and str(event_summary).strip():
            return truncate_calendar_button_label(str(event_summary).strip())

    if tool_name in {
        "google.calendar.create_event",
        "google.calendar.quick_add_event",
        "google.calendar.import_event",
    }:
        return "Открыть новое событие"
    if tool_name in {
        "google.calendar.patch_event",
        "google.calendar.update_event",
        "google.calendar.move_event",
    }:
        return "Открыть событие"
    if tool_name == "google.calendar.get_event":
        return "Открыть событие"
    if tool_name in {
        "google.calendar.list_events",
        "google.calendar.list_upcoming",
        "google.calendar.list_today",
        "google.calendar.search_events",
    }:
        return label_for_calendar_event(summary=summary)

    if url and is_calendar_event_url(url):
        return label_for_calendar_url(url)
    return "Открыть календарь"


def button_sort_key(group_key: str, label: str) -> tuple[int, str]:
    kind_order = {"event": 0, "url": 1}
    prefix = group_key.split(":", 1)[0]
    return (kind_order.get(prefix, 9), label.casefold())
