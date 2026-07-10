from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import get_settings


def resolve_timezone(time_zone: str | None = None) -> ZoneInfo:
    tz_name = (time_zone or get_settings().bot_timezone or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def parse_iso_datetime(value: str, *, time_zone: str | None = None) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        # Naive datetime is wall-clock time in the target/bot timezone — same
        # semantics as build_event_time, so create vs list/freebusy agree.
        return parsed.replace(tzinfo=resolve_timezone(time_zone))
    return parsed


def to_rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=resolve_timezone(None))
    return value.isoformat()


def day_bounds(target: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(target, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start, end


def today_bounds(time_zone: str | None = None) -> tuple[datetime, datetime, str]:
    tz = resolve_timezone(time_zone)
    today = datetime.now(tz).date()
    start, end = day_bounds(today, tz)
    return start, end, tz.key


def upcoming_bounds(days_ahead: int, time_zone: str | None = None) -> tuple[datetime, datetime, str]:
    tz = resolve_timezone(time_zone)
    now = datetime.now(tz)
    end = now + timedelta(days=max(days_ahead, 1))
    return now, end, tz.key


def compact_event(event: dict[str, Any]) -> dict[str, Any]:
    start = event.get("start") or {}
    end = event.get("end") or {}
    attendees = event.get("attendees") or []
    payload: dict[str, Any] = {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "description": event.get("description"),
        "location": event.get("location"),
        "status": event.get("status"),
        "htmlLink": event.get("htmlLink"),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "timeZone": start.get("timeZone") or end.get("timeZone"),
        "recurringEventId": event.get("recurringEventId"),
        "color_id": event.get("colorId"),
        "attendees": [
            {
                "email": attendee.get("email"),
                "displayName": attendee.get("displayName"),
                "responseStatus": attendee.get("responseStatus"),
            }
            for attendee in attendees
        ],
    }
    meet_link = extract_meet_link(event)
    if meet_link:
        payload["meet_link"] = meet_link
    return payload


def extract_meet_link(event: dict[str, Any]) -> str | None:
    hangout = event.get("hangoutLink")
    if isinstance(hangout, str) and hangout.strip():
        return hangout.strip()

    conference = event.get("conferenceData")
    if not isinstance(conference, dict):
        return None
    for entry in conference.get("entryPoints") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("entryPointType") != "video":
            continue
        uri = entry.get("uri")
        if isinstance(uri, str) and uri.strip():
            return uri.strip()
    return None


def build_google_meet_conference_data(*, request_id: str | None = None) -> dict[str, Any]:
    return {
        "createRequest": {
            "requestId": request_id or uuid.uuid4().hex,
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }
    }


def build_create_meet_event_body(arguments: dict[str, Any]) -> dict[str, Any]:
    body = build_create_event_body(arguments)
    body["conferenceData"] = build_google_meet_conference_data()
    return body


def compact_calendar(calendar: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": calendar.get("id"),
        "summary": calendar.get("summary"),
        "description": calendar.get("description"),
        "timeZone": calendar.get("timeZone"),
        "primary": calendar.get("primary"),
        "accessRole": calendar.get("accessRole"),
        "backgroundColor": calendar.get("backgroundColor"),
        "foregroundColor": calendar.get("foregroundColor"),
        "color_id": calendar.get("colorId"),
    }


def compact_color_palette(colors: dict[str, Any]) -> dict[str, Any]:
    def _entries(section: dict[str, Any] | None) -> list[dict[str, str]]:
        if not section:
            return []
        items = []
        for color_id, spec in section.items():
            items.append(
                {
                    "color_id": str(color_id),
                    "background": str(spec.get("background", "")),
                    "foreground": str(spec.get("foreground", "")),
                }
            )
        items.sort(key=lambda item: int(item["color_id"]) if item["color_id"].isdigit() else item["color_id"])
        return items

    return {
        "updated": colors.get("updated"),
        "calendar_colors": _entries(colors.get("calendar")),
        "event_colors": _entries(colors.get("event")),
    }


def build_create_calendar_body(arguments: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {"summary": arguments["summary"]}
    if arguments.get("description") is not None:
        body["description"] = arguments["description"]
    time_zone = arguments.get("time_zone") or get_settings().bot_timezone
    if time_zone:
        body["timeZone"] = time_zone
    return body


def merge_calendar_for_update(existing: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    updated = dict(existing)
    for field, key in (
        ("summary", "summary"),
        ("description", "description"),
        ("time_zone", "timeZone"),
    ):
        if field in arguments and arguments[field] is not None:
            updated[key] = arguments[field]
    return updated


def build_event_time(value: dict[str, Any], *, default_time_zone: str | None = None) -> dict[str, Any]:
    if "date" in value and value["date"]:
        return {"date": value["date"]}

    if "datetime" in value and value["datetime"]:
        raw = str(value["datetime"]).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        tz_name = (value.get("time_zone") or default_time_zone or get_settings().bot_timezone or "UTC").strip()
        tz = resolve_timezone(tz_name)
        if dt.tzinfo is None:
            # Naive datetime is wall-clock time in the target timezone, not UTC.
            dt = dt.replace(tzinfo=tz)
        else:
            dt = dt.astimezone(tz)
        return {"dateTime": to_rfc3339(dt), "timeZone": tz.key}

    raise ValueError("Event time must include 'date' (all-day) or 'datetime' (timed event).")


def build_attendees(attendees: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not attendees:
        return None
    built: list[dict[str, Any]] = []
    for attendee in attendees:
        email = attendee.get("email")
        if not email:
            continue
        item: dict[str, Any] = {"email": email}
        display_name = attendee.get("display_name") or attendee.get("displayName")
        if display_name:
            item["displayName"] = display_name
        built.append(item)
    return built or None


def build_create_event_body(arguments: dict[str, Any]) -> dict[str, Any]:
    default_tz = arguments.get("time_zone")
    body: dict[str, Any] = {
        "summary": arguments["summary"],
        "start": build_event_time(arguments["start"], default_time_zone=default_tz),
        "end": build_event_time(arguments["end"], default_time_zone=default_tz),
    }
    for field in ("description", "location", "color_id"):
        if arguments.get(field) is not None:
            body[field if field != "color_id" else "colorId"] = arguments[field]

    attendees = build_attendees(arguments.get("attendees"))
    if attendees:
        body["attendees"] = attendees
    if arguments.get("reminders") is not None:
        body["reminders"] = arguments["reminders"]
    if arguments.get("recurrence") is not None:
        body["recurrence"] = arguments["recurrence"]
    return body


def build_patch_event_body(arguments: dict[str, Any]) -> dict[str, Any]:
    default_tz = arguments.get("time_zone")
    body: dict[str, Any] = {}

    for field in ("summary", "description", "location"):
        if field in arguments and arguments[field] is not None:
            body[field] = arguments[field]

    if "color_id" in arguments and arguments["color_id"] is not None:
        body["colorId"] = arguments["color_id"]
    if "start" in arguments and arguments["start"] is not None:
        body["start"] = build_event_time(arguments["start"], default_time_zone=default_tz)
    if "end" in arguments and arguments["end"] is not None:
        body["end"] = build_event_time(arguments["end"], default_time_zone=default_tz)

    attendees = build_attendees(arguments.get("attendees"))
    if attendees is not None:
        body["attendees"] = attendees
    if "reminders" in arguments and arguments["reminders"] is not None:
        body["reminders"] = arguments["reminders"]
    if "recurrence" in arguments and arguments["recurrence"] is not None:
        body["recurrence"] = arguments["recurrence"]
    return body


def merge_event_for_update(existing: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    updated = dict(existing)
    updated.update(build_create_event_body(arguments))
    return updated


def parse_hhmm(value: str) -> time:
    hour_str, minute_str = value.split(":", 1)
    return time(hour=int(hour_str), minute=int(minute_str))


def merge_busy_intervals(blocks: list[dict[str, Any]]) -> list[tuple[datetime, datetime]]:
    intervals: list[tuple[datetime, datetime]] = []
    for block in blocks:
        start_raw = block.get("start")
        end_raw = block.get("end")
        if not start_raw or not end_raw:
            continue
        intervals.append((parse_iso_datetime(start_raw), parse_iso_datetime(end_raw)))
    intervals.sort(key=lambda item: item[0])
    merged: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def subtract_busy(
    window_start: datetime,
    window_end: datetime,
    busy: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    free: list[tuple[datetime, datetime]] = []
    cursor = window_start
    for busy_start, busy_end in busy:
        if busy_end <= cursor or busy_start >= window_end:
            continue
        clipped_start = max(busy_start, window_start)
        clipped_end = min(busy_end, window_end)
        if clipped_start > cursor:
            free.append((cursor, clipped_start))
        cursor = max(cursor, clipped_end)
    if cursor < window_end:
        free.append((cursor, window_end))
    return free


def find_free_slots(
    *,
    time_min: datetime,
    time_max: datetime,
    busy_blocks: list[dict[str, Any]],
    duration_minutes: int = 60,
    working_hours_start: str = "09:00",
    working_hours_end: str = "18:00",
    time_zone: str | None = None,
    max_slots: int = 5,
) -> list[dict[str, str]]:
    if time_max <= time_min:
        return []

    tz = resolve_timezone(time_zone)
    start = time_min.astimezone(tz)
    end = time_max.astimezone(tz)
    duration = timedelta(minutes=max(duration_minutes, 1))
    work_start = parse_hhmm(working_hours_start)
    work_end = parse_hhmm(working_hours_end)
    busy = merge_busy_intervals(busy_blocks)

    slots: list[dict[str, str]] = []
    day = start.date()
    last_day = end.date()

    while day <= last_day and len(slots) < max_slots:
        day_start = datetime.combine(day, work_start, tzinfo=tz)
        day_end = datetime.combine(day, work_end, tzinfo=tz)
        window_start = max(start, day_start)
        window_end = min(end, day_end)

        if window_start < window_end:
            for free_start, free_end in subtract_busy(window_start, window_end, busy):
                slot_start = free_start
                while slot_start + duration <= free_end and len(slots) < max_slots:
                    slot_end = slot_start + duration
                    slots.append(
                        {
                            "start": to_rfc3339(slot_start),
                            "end": to_rfc3339(slot_end),
                        }
                    )
                    slot_start = slot_end

        day += timedelta(days=1)

    return slots
