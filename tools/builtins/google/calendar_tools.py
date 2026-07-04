from __future__ import annotations

import asyncio
from typing import Any

from tools.builtins.google.auth import get_calendar_service
from tools.builtins.google.tool_hints import GOOGLE_CALENDAR_OAUTH_HINT
from tools.builtins.google.datetime_utils import (
    build_create_calendar_body,
    build_create_event_body,
    build_patch_event_body,
    compact_calendar,
    compact_color_palette,
    compact_event,
    find_free_slots,
    merge_calendar_for_update,
    merge_event_for_update,
    parse_iso_datetime,
    today_bounds,
    to_rfc3339,
    upcoming_bounds,
)
from tools.context import get_run_context
from tools.schema import ToolSpec


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


async def _run_calendar_call(user_id: int, fn):
    service = await get_calendar_service(user_id)
    return await asyncio.to_thread(fn, service)


async def _get_calendar_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments.get("calendar_id", "primary")

    def _call(service):
        return service.calendars().get(calendarId=calendar_id).execute()

    calendar = await _run_calendar_call(user_id, _call)
    return {"calendar": compact_calendar(calendar)}


async def _list_events_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments.get("calendar_id", "primary")
    time_min = parse_iso_datetime(arguments["time_min"])
    time_max = parse_iso_datetime(arguments["time_max"]) if arguments.get("time_max") else None
    max_results = min(int(arguments.get("max_results", 25)), 250)
    single_events = bool(arguments.get("single_events", True))
    order_by = arguments.get("order_by", "startTime")
    query = arguments.get("query")

    def _call(service):
        params: dict[str, Any] = {
            "calendarId": calendar_id,
            "timeMin": to_rfc3339(time_min),
            "maxResults": max_results,
            "singleEvents": single_events,
            "orderBy": order_by,
        }
        if time_max is not None:
            params["timeMax"] = to_rfc3339(time_max)
        if query:
            params["q"] = query
        response = service.events().list(**params).execute()
        return response.get("items", [])

    events = await _run_calendar_call(user_id, _call)
    return {
        "calendar_id": calendar_id,
        "count": len(events),
        "events": [compact_event(event) for event in events],
    }


async def _get_event_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments.get("calendar_id", "primary")
    event_id = arguments["event_id"]

    def _call(service):
        return service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    event = await _run_calendar_call(user_id, _call)
    return {"event": compact_event(event)}


async def _search_events_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = {
        **arguments,
        "single_events": arguments.get("single_events", True),
        "order_by": arguments.get("order_by", "startTime"),
    }
    if "time_min" not in payload:
        time_min, time_max, _ = upcoming_bounds(int(arguments.get("days_ahead", 30)))
        payload["time_min"] = to_rfc3339(time_min)
        payload["time_max"] = to_rfc3339(time_max)
    result = await _list_events_handler(payload)
    result["query"] = arguments["query"]
    return result


async def _list_upcoming_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    count = min(int(arguments.get("count", 10)), 50)
    days_ahead = int(arguments.get("days_ahead", 7))
    time_min, time_max, time_zone = upcoming_bounds(days_ahead, arguments.get("time_zone"))
    result = await _list_events_handler(
        {
            "calendar_id": arguments.get("calendar_id", "primary"),
            "time_min": to_rfc3339(time_min),
            "time_max": to_rfc3339(time_max),
            "max_results": count,
            "single_events": True,
            "order_by": "startTime",
            "time_zone": time_zone,
        }
    )
    result["time_zone"] = time_zone
    return result


async def _list_today_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    time_min, time_max, time_zone = today_bounds(arguments.get("time_zone"))
    result = await _list_events_handler(
        {
            "calendar_id": arguments.get("calendar_id", "primary"),
            "time_min": to_rfc3339(time_min),
            "time_max": to_rfc3339(time_max),
            "max_results": int(arguments.get("max_results", 50)),
            "single_events": True,
            "order_by": "startTime",
        }
    )
    result["date"] = time_min.date().isoformat()
    result["time_zone"] = time_zone
    return result


async def _freebusy_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    time_min = parse_iso_datetime(arguments["time_min"])
    time_max = parse_iso_datetime(arguments["time_max"])
    calendar_ids = arguments.get("calendar_ids") or ["primary"]
    if isinstance(calendar_ids, str):
        calendar_ids = [calendar_ids]

    def _call(service):
        body = {
            "timeMin": to_rfc3339(time_min),
            "timeMax": to_rfc3339(time_max),
            "items": [{"id": calendar_id} for calendar_id in calendar_ids],
        }
        return service.freebusy().query(body=body).execute()

    response = await _run_calendar_call(user_id, _call)
    calendars = response.get("calendars", {})
    return {
        "time_min": to_rfc3339(time_min),
        "time_max": to_rfc3339(time_max),
        "calendars": {
            calendar_id: calendar.get("busy", [])
            for calendar_id, calendar in calendars.items()
        },
    }


def _send_updates(arguments: dict[str, Any]) -> str:
    value = arguments.get("send_updates", "none")
    if value not in {"all", "externalOnly", "none"}:
        raise ValueError("send_updates must be one of: all, externalOnly, none")
    return value


def _ensure_secondary_calendar(service, calendar_id: str) -> dict[str, Any]:
    if calendar_id == "primary":
        raise ValueError("The primary calendar cannot be deleted or cleared")
    calendar = service.calendars().get(calendarId=calendar_id).execute()
    if calendar.get("primary"):
        raise ValueError("The primary calendar cannot be deleted or cleared")
    return calendar


async def _create_event_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments.get("calendar_id", "primary")
    body = build_create_event_body(arguments)
    send_updates = _send_updates(arguments)

    def _call(service):
        return (
            service.events()
            .insert(calendarId=calendar_id, body=body, sendUpdates=send_updates)
            .execute()
        )

    event = await _run_calendar_call(user_id, _call)
    return {
        "created": True,
        "calendar_id": calendar_id,
        "event": compact_event(event),
        "htmlLink": event.get("htmlLink"),
    }


async def _quick_add_event_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments.get("calendar_id", "primary")
    text = arguments["text"].strip()
    if not text:
        raise ValueError("text is required for quick_add_event")
    send_updates = _send_updates(arguments)

    def _call(service):
        return (
            service.events()
            .quickAdd(calendarId=calendar_id, text=text, sendUpdates=send_updates)
            .execute()
        )

    event = await _run_calendar_call(user_id, _call)
    return {
        "created": True,
        "calendar_id": calendar_id,
        "text": text,
        "event": compact_event(event),
        "htmlLink": event.get("htmlLink"),
    }


async def _patch_event_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments.get("calendar_id", "primary")
    event_id = arguments["event_id"]
    body = build_patch_event_body(arguments)
    if not body:
        raise ValueError("Provide at least one field to patch")
    send_updates = _send_updates(arguments)

    def _call(service):
        return (
            service.events()
            .patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=body,
                sendUpdates=send_updates,
            )
            .execute()
        )

    event = await _run_calendar_call(user_id, _call)
    return {
        "patched": True,
        "calendar_id": calendar_id,
        "event_id": event_id,
        "event": compact_event(event),
        "htmlLink": event.get("htmlLink"),
    }


async def _delete_event_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments.get("calendar_id", "primary")
    event_id = arguments["event_id"]
    send_updates = _send_updates(arguments)

    def _call(service):
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id,
            sendUpdates=send_updates,
        ).execute()
        return True

    await _run_calendar_call(user_id, _call)
    return {"deleted": True, "calendar_id": calendar_id, "event_id": event_id}


async def _update_event_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments.get("calendar_id", "primary")
    event_id = arguments["event_id"]
    send_updates = _send_updates(arguments)

    def _call(service):
        existing = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        body = merge_event_for_update(existing, arguments)
        return (
            service.events()
            .update(
                calendarId=calendar_id,
                eventId=event_id,
                body=body,
                sendUpdates=send_updates,
            )
            .execute()
        )

    event = await _run_calendar_call(user_id, _call)
    return {
        "updated": True,
        "calendar_id": calendar_id,
        "event_id": event_id,
        "event": compact_event(event),
        "htmlLink": event.get("htmlLink"),
    }


async def _move_event_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments.get("calendar_id", "primary")
    event_id = arguments["event_id"]
    destination_calendar_id = arguments["destination_calendar_id"]
    send_updates = _send_updates(arguments)

    def _call(service):
        return (
            service.events()
            .move(
                calendarId=calendar_id,
                eventId=event_id,
                destination=destination_calendar_id,
                sendUpdates=send_updates,
            )
            .execute()
        )

    event = await _run_calendar_call(user_id, _call)
    return {
        "moved": True,
        "source_calendar_id": calendar_id,
        "destination_calendar_id": destination_calendar_id,
        "event_id": event_id,
        "event": compact_event(event),
        "htmlLink": event.get("htmlLink"),
    }


async def _list_instances_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments.get("calendar_id", "primary")
    event_id = arguments["event_id"]
    time_min = parse_iso_datetime(arguments["time_min"])
    time_max = parse_iso_datetime(arguments["time_max"])
    max_results = min(int(arguments.get("max_results", 25)), 250)

    def _call(service):
        response = (
            service.events()
            .instances(
                calendarId=calendar_id,
                eventId=event_id,
                timeMin=to_rfc3339(time_min),
                timeMax=to_rfc3339(time_max),
                maxResults=max_results,
            )
            .execute()
        )
        return response.get("items", [])

    instances = await _run_calendar_call(user_id, _call)
    return {
        "calendar_id": calendar_id,
        "recurring_event_id": event_id,
        "count": len(instances),
        "instances": [compact_event(event) for event in instances],
    }


async def _find_free_slots_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    time_min = parse_iso_datetime(arguments["time_min"])
    time_max = parse_iso_datetime(arguments["time_max"])
    calendar_ids = arguments.get("calendar_ids") or ["primary"]
    if isinstance(calendar_ids, str):
        calendar_ids = [calendar_ids]
    duration_minutes = int(arguments.get("duration_minutes", 60))
    max_slots = min(int(arguments.get("max_slots", 5)), 20)
    time_zone = arguments.get("time_zone")

    def _call(service):
        body = {
            "timeMin": to_rfc3339(time_min),
            "timeMax": to_rfc3339(time_max),
            "items": [{"id": calendar_id} for calendar_id in calendar_ids],
        }
        return service.freebusy().query(body=body).execute()

    response = await _run_calendar_call(user_id, _call)
    busy_blocks: list[dict[str, Any]] = []
    for calendar in response.get("calendars", {}).values():
        busy_blocks.extend(calendar.get("busy", []))

    slots = find_free_slots(
        time_min=time_min,
        time_max=time_max,
        busy_blocks=busy_blocks,
        duration_minutes=duration_minutes,
        working_hours_start=str(arguments.get("working_hours_start", "09:00")),
        working_hours_end=str(arguments.get("working_hours_end", "18:00")),
        time_zone=time_zone,
        max_slots=max_slots,
    )
    return {
        "duration_minutes": duration_minutes,
        "time_min": to_rfc3339(time_min),
        "time_max": to_rfc3339(time_max),
        "count": len(slots),
        "slots": slots,
    }


async def _list_calendars_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    show_hidden = bool(arguments.get("show_hidden", False))
    show_deleted = bool(arguments.get("show_deleted", False))

    def _call(service):
        response = (
            service.calendarList()
            .list(showHidden=show_hidden, showDeleted=show_deleted, maxResults=250)
            .execute()
        )
        return response.get("items", [])

    calendars = await _run_calendar_call(user_id, _call)
    return {
        "count": len(calendars),
        "calendars": [compact_calendar(item) for item in calendars],
    }


async def _create_calendar_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    body = build_create_calendar_body(arguments)

    def _call(service):
        return service.calendars().insert(body=body).execute()

    calendar = await _run_calendar_call(user_id, _call)
    return {"created": True, "calendar": compact_calendar(calendar)}


async def _update_calendar_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments["calendar_id"]

    def _call(service):
        existing = service.calendars().get(calendarId=calendar_id).execute()
        body = merge_calendar_for_update(existing, arguments)
        return service.calendars().update(calendarId=calendar_id, body=body).execute()

    calendar = await _run_calendar_call(user_id, _call)
    return {"updated": True, "calendar_id": calendar_id, "calendar": compact_calendar(calendar)}


async def _delete_calendar_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments["calendar_id"]

    def _call(service):
        _ensure_secondary_calendar(service, calendar_id)
        service.calendars().delete(calendarId=calendar_id).execute()
        return True

    await _run_calendar_call(user_id, _call)
    return {"deleted": True, "calendar_id": calendar_id}


async def _clear_calendar_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments["calendar_id"]
    if not bool(arguments.get("confirm")):
        raise ValueError("clear_calendar requires confirm=true")

    def _call(service):
        _ensure_secondary_calendar(service, calendar_id)
        service.calendars().clear(calendarId=calendar_id).execute()
        return True

    await _run_calendar_call(user_id, _call)
    return {"cleared": True, "calendar_id": calendar_id}


async def _import_event_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments.get("calendar_id", "primary")
    body = build_create_event_body(arguments)

    def _call(service):
        return service.events().import_(calendarId=calendar_id, body=body).execute()

    event = await _run_calendar_call(user_id, _call)
    return {
        "imported": True,
        "calendar_id": calendar_id,
        "event": compact_event(event),
        "htmlLink": event.get("htmlLink"),
    }


async def _list_colors_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()

    def _call(service):
        return service.colors().get().execute()

    colors = await _run_calendar_call(user_id, _call)
    return compact_color_palette(colors)


async def _set_calendar_color_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    calendar_id = arguments["calendar_id"]
    color_id = str(arguments["color_id"])

    def _call(service):
        return (
            service.calendarList()
            .patch(
                calendarId=calendar_id,
                body={"colorId": color_id},
            )
            .execute()
        )

    calendar = await _run_calendar_call(user_id, _call)
    return {
        "updated": True,
        "calendar_id": calendar_id,
        "color_id": color_id,
        "calendar": compact_calendar(calendar),
    }


_CALENDAR_ID_PARAM = {
    "calendar_id": {
        "type": "string",
        "description": "Google Calendar ID. Default: primary.",
        "default": "primary",
    }
}

_EVENT_TIME_SCHEMA = {
    "type": "object",
    "description": "Timed: {datetime, time_zone?}. All-day: {date: YYYY-MM-DD}.",
    "properties": {
        "datetime": {"type": "string", "description": "ISO 8601 datetime for timed events."},
        "time_zone": {"type": "string", "description": "IANA timezone for naive datetime."},
        "date": {"type": "string", "description": "YYYY-MM-DD for all-day events."},
    },
}

_SEND_UPDATES_PARAM = {
    "send_updates": {
        "type": "string",
        "enum": ["all", "externalOnly", "none"],
        "default": "none",
        "description": "Whether to notify attendees about the change.",
    }
}

_EVENT_ID_PARAM = {
    "event_id": {"type": "string", "description": "Google Calendar event ID."},
}

_REMINDERS_SCHEMA = {
    "type": "object",
    "description": (
        "Reminder overrides, e.g. "
        "{useDefault: false, overrides: [{method: 'popup', minutes: 30}]}."
    ),
}

_CREATE_EVENT_FIELDS = {
    **_CALENDAR_ID_PARAM,
    "summary": {"type": "string", "description": "Event title."},
    "start": _EVENT_TIME_SCHEMA,
    "end": _EVENT_TIME_SCHEMA,
    "description": {"type": "string", "description": "Event notes or agenda."},
    "location": {"type": "string", "description": "Physical or virtual location."},
    "time_zone": {
        "type": "string",
        "description": "Default IANA timezone for naive start/end datetimes.",
    },
    "attendees": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "display_name": {"type": "string"},
            },
            "required": ["email"],
        },
    },
    "reminders": _REMINDERS_SCHEMA,
    "recurrence": {
        "type": "array",
        "items": {"type": "string"},
        "description": "RRULE strings, e.g. RRULE:FREQ=WEEKLY;BYDAY=MO",
    },
    "color_id": {
        "type": "string",
        "description": "Event color ID (1-11). Call google.calendar.list_colors for palette.",
    },
    **_SEND_UPDATES_PARAM,
}

GOOGLE_CALENDAR_GET_CALENDAR = ToolSpec(
    name="google.calendar.get_calendar",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Get metadata for one Google Calendar (timezone, summary, description)."
    ),
    parameters={"type": "object", "properties": _CALENDAR_ID_PARAM},
    handler=_get_calendar_handler,
    tags=("google", "calendar", "calendars", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    examples=("show my calendar settings", "calendar timezone"),
)

GOOGLE_CALENDAR_LIST_EVENTS = ToolSpec(
    name="google.calendar.list_events",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "List events in an explicit time range (time_min required). "
        "Prefer list_upcoming for 'what's next' or list_today for today's schedule."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_CALENDAR_ID_PARAM,
            "time_min": {"type": "string", "description": "ISO 8601 start time."},
            "time_max": {"type": "string", "description": "ISO 8601 end time."},
            "query": {"type": "string", "description": "Optional text search query."},
            "max_results": {"type": "integer", "default": 25},
            "single_events": {"type": "boolean", "default": True},
            "order_by": {
                "type": "string",
                "enum": ["startTime", "updated"],
                "default": "startTime",
                "description": "startTime for chronological order; updated for recently changed events.",
            },
        },
        "required": ["time_min"],
    },
    handler=_list_events_handler,
    tags=("google", "calendar", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    examples=("list events this week", "calendar events between dates"),
)

GOOGLE_CALENDAR_GET_EVENT = ToolSpec(
    name="google.calendar.get_event",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Get one Google Calendar event by ID (from list/search/create results)."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_CALENDAR_ID_PARAM,
            "event_id": {"type": "string", "description": "Google event ID."},
        },
        "required": ["event_id"],
    },
    handler=_get_event_handler,
    tags=("google", "calendar", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    examples=("get calendar event details", "show event by id"),
)

GOOGLE_CALENDAR_SEARCH_EVENTS = ToolSpec(
    name="google.calendar.search_events",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Search events by text in title, description, or attendees. "
        "Defaults to the next 30 days if time_min is omitted. "
        "Prefer over list_events when searching by keyword."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_CALENDAR_ID_PARAM,
            "query": {"type": "string", "description": "Text to search for."},
            "time_min": {"type": "string", "description": "Optional ISO 8601 lower bound."},
            "time_max": {"type": "string", "description": "Optional ISO 8601 upper bound."},
            "days_ahead": {"type": "integer", "default": 30},
            "max_results": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    },
    handler=_search_events_handler,
    tags=("google", "calendar", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    examples=("find meeting with Alex", "search calendar for dentist"),
)

GOOGLE_CALENDAR_LIST_UPCOMING = ToolSpec(
    name="google.calendar.list_upcoming",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "List upcoming events from now (default: next 7 days, 10 events). "
        "Prefer over list_events when the user asks what's on their calendar next."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_CALENDAR_ID_PARAM,
            "count": {"type": "integer", "default": 10},
            "days_ahead": {"type": "integer", "default": 7},
            "time_zone": {"type": "string", "description": "IANA timezone name."},
        },
    },
    handler=_list_upcoming_handler,
    tags=("google", "calendar", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    examples=("what is coming up on my calendar", "next calendar events"),
)

GOOGLE_CALENDAR_LIST_TODAY = ToolSpec(
    name="google.calendar.list_today",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "List all events for today in the user's timezone. "
        "Prefer over list_upcoming when the user asks specifically about today."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_CALENDAR_ID_PARAM,
            "time_zone": {"type": "string", "description": "IANA timezone name."},
            "max_results": {"type": "integer", "default": 50},
        },
    },
    handler=_list_today_handler,
    tags=("google", "calendar", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    examples=("what is on my calendar today", "today schedule"),
)

GOOGLE_CALENDAR_LIST_COLORS = ToolSpec(
    name="google.calendar.list_colors",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "List Google Calendar color palettes for calendars and events. "
        "Use returned color_id values with create_event, patch_event, or set_calendar_color."
    ),
    parameters={"type": "object", "properties": {}},
    handler=_list_colors_handler,
    tags=("google", "calendar", "colors", "read"),
    cache_ttl_seconds=3600,
    parallel_safe=True,
    examples=("show calendar color options", "what colors can I use for events"),
)

GOOGLE_CALENDAR_FREEBUSY = ToolSpec(
    name="google.calendar.freebusy",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Return raw busy time blocks for one or more calendars. "
        "Use find_free_slots when the user needs suggested bookable meeting slots."
    ),
    parameters={
        "type": "object",
        "properties": {
            "time_min": {"type": "string", "description": "ISO 8601 start time."},
            "time_max": {"type": "string", "description": "ISO 8601 end time."},
            "calendar_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Calendar IDs to inspect. Default: [primary].",
            },
        },
        "required": ["time_min", "time_max"],
    },
    handler=_freebusy_handler,
    tags=("google", "calendar", "scheduling", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    examples=("when am I busy tomorrow", "freebusy this week"),
)

GOOGLE_CALENDAR_READ_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_CALENDAR_GET_CALENDAR,
    GOOGLE_CALENDAR_LIST_EVENTS,
    GOOGLE_CALENDAR_GET_EVENT,
    GOOGLE_CALENDAR_SEARCH_EVENTS,
    GOOGLE_CALENDAR_LIST_UPCOMING,
    GOOGLE_CALENDAR_LIST_TODAY,
    GOOGLE_CALENDAR_LIST_COLORS,
    GOOGLE_CALENDAR_FREEBUSY,
)

GOOGLE_CALENDAR_CREATE_EVENT = ToolSpec(
    name="google.calendar.create_event",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Create an event with full control (attendees, recurrence, reminders, location). "
        "Prefer quick_add_event for simple natural-language requests."
    ),
    parameters={
        "type": "object",
        "properties": _CREATE_EVENT_FIELDS,
        "required": ["summary", "start", "end"],
    },
    handler=_create_event_handler,
    tags=("google", "calendar", "write"),
    parallel_safe=False,
    examples=("create calendar meeting tomorrow at 15:00", "schedule dentist appointment"),
)

GOOGLE_CALENDAR_QUICK_ADD_EVENT = ToolSpec(
    name="google.calendar.quick_add_event",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Create an event from natural language (e.g. 'Lunch tomorrow at 13:00'). "
        "Prefer over create_event for simple requests without attendees or recurrence."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_CALENDAR_ID_PARAM,
            "text": {
                "type": "string",
                "description": "Natural language event text, e.g. Lunch tomorrow at 13:00.",
            },
            **_SEND_UPDATES_PARAM,
        },
        "required": ["text"],
    },
    handler=_quick_add_event_handler,
    tags=("google", "calendar", "write"),
    parallel_safe=False,
    examples=("quick add lunch tomorrow 13:00", "add event from natural language"),
)

GOOGLE_CALENDAR_PATCH_EVENT = ToolSpec(
    name="google.calendar.patch_event",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Partially update an event (only fields you pass are changed). "
        "Prefer over update_event unless replacing the entire event."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_CALENDAR_ID_PARAM,
            **_EVENT_ID_PARAM,
            "summary": {"type": "string"},
            "description": {"type": "string"},
            "location": {"type": "string"},
            "start": _EVENT_TIME_SCHEMA,
            "end": _EVENT_TIME_SCHEMA,
            "time_zone": {"type": "string"},
            "attendees": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"},
                        "display_name": {"type": "string"},
                    },
                    "required": ["email"],
                },
            },
            "reminders": _REMINDERS_SCHEMA,
            "recurrence": {"type": "array", "items": {"type": "string"}},
            "color_id": {
                "type": "string",
                "description": "Event color ID (1-11). Call google.calendar.list_colors for palette.",
            },
            **_SEND_UPDATES_PARAM,
        },
        "required": ["event_id"],
    },
    handler=_patch_event_handler,
    tags=("google", "calendar", "write"),
    parallel_safe=False,
    examples=("move meeting one hour later", "rename calendar event", "change event time"),
)

GOOGLE_CALENDAR_DELETE_EVENT = ToolSpec(
    name="google.calendar.delete_event",
    description=GOOGLE_CALENDAR_OAUTH_HINT + "Delete a Google Calendar event by ID.",
    parameters={
        "type": "object",
        "properties": {
            **_CALENDAR_ID_PARAM,
            **_EVENT_ID_PARAM,
            **_SEND_UPDATES_PARAM,
        },
        "required": ["event_id"],
    },
    handler=_delete_event_handler,
    tags=("google", "calendar", "write"),
    parallel_safe=False,
    examples=("cancel calendar event", "delete meeting from calendar"),
)

GOOGLE_CALENDAR_WRITE_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_CALENDAR_CREATE_EVENT,
    GOOGLE_CALENDAR_QUICK_ADD_EVENT,
    GOOGLE_CALENDAR_PATCH_EVENT,
    GOOGLE_CALENDAR_DELETE_EVENT,
)

GOOGLE_CALENDAR_UPDATE_EVENT = ToolSpec(
    name="google.calendar.update_event",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Fully replace an event — omitted fields are cleared. "
        "Prefer patch_event for partial changes."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_CREATE_EVENT_FIELDS,
            **_EVENT_ID_PARAM,
        },
        "required": ["event_id", "summary", "start", "end"],
    },
    handler=_update_event_handler,
    tags=("google", "calendar", "write"),
    parallel_safe=False,
    examples=("replace calendar event completely", "full update meeting details"),
)

GOOGLE_CALENDAR_MOVE_EVENT = ToolSpec(
    name="google.calendar.move_event",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Move an event to another calendar (use list_calendars for destination IDs)."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_CALENDAR_ID_PARAM,
            **_EVENT_ID_PARAM,
            "destination_calendar_id": {
                "type": "string",
                "description": "Target Google Calendar ID.",
            },
            **_SEND_UPDATES_PARAM,
        },
        "required": ["event_id", "destination_calendar_id"],
    },
    handler=_move_event_handler,
    tags=("google", "calendar", "write"),
    parallel_safe=False,
    examples=("move event to work calendar", "transfer meeting to another calendar"),
)

GOOGLE_CALENDAR_LIST_INSTANCES = ToolSpec(
    name="google.calendar.list_instances",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "List occurrences of a recurring event in a time range."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_CALENDAR_ID_PARAM,
            **_EVENT_ID_PARAM,
            "time_min": {"type": "string", "description": "ISO 8601 start time."},
            "time_max": {"type": "string", "description": "ISO 8601 end time."},
            "max_results": {"type": "integer", "default": 25},
        },
        "required": ["event_id", "time_min", "time_max"],
    },
    handler=_list_instances_handler,
    tags=("google", "calendar", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    examples=("list weekly meeting instances", "recurring event occurrences"),
)

GOOGLE_CALENDAR_FIND_FREE_SLOTS = ToolSpec(
    name="google.calendar.find_free_slots",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Find bookable free slots of a given duration within working hours. "
        "Built on freebusy — prefer over freebusy when suggesting meeting times."
    ),
    parameters={
        "type": "object",
        "properties": {
            "time_min": {"type": "string", "description": "ISO 8601 start time."},
            "time_max": {"type": "string", "description": "ISO 8601 end time."},
            "duration_minutes": {"type": "integer", "default": 60},
            "calendar_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Calendar IDs to inspect. Default: [primary].",
            },
            "working_hours_start": {
                "type": "string",
                "default": "09:00",
                "description": "Working day start in HH:MM 24h format.",
            },
            "working_hours_end": {
                "type": "string",
                "default": "18:00",
                "description": "Working day end in HH:MM 24h format.",
            },
            "time_zone": {"type": "string", "description": "IANA timezone name."},
            "max_slots": {"type": "integer", "default": 5},
        },
        "required": ["time_min", "time_max"],
    },
    handler=_find_free_slots_handler,
    tags=("google", "calendar", "scheduling", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    examples=("find 1 hour free slot tomorrow", "when can we meet this week"),
)

GOOGLE_CALENDAR_CAL3_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_CALENDAR_UPDATE_EVENT,
    GOOGLE_CALENDAR_MOVE_EVENT,
    GOOGLE_CALENDAR_LIST_INSTANCES,
    GOOGLE_CALENDAR_FIND_FREE_SLOTS,
)

GOOGLE_CALENDAR_LIST_CALENDARS = ToolSpec(
    name="google.calendar.list_calendars",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "List all calendars for the connected user (IDs for move_event and multi-calendar queries)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "show_hidden": {"type": "boolean", "default": False},
            "show_deleted": {"type": "boolean", "default": False},
        },
    },
    handler=_list_calendars_handler,
    tags=("google", "calendar", "calendars", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    examples=("list my calendars", "show all google calendars"),
)

GOOGLE_CALENDAR_CREATE_CALENDAR = ToolSpec(
    name="google.calendar.create_calendar",
    description=GOOGLE_CALENDAR_OAUTH_HINT + "Create a new secondary Google Calendar.",
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Calendar title."},
            "description": {"type": "string"},
            "time_zone": {"type": "string", "description": "IANA timezone name."},
        },
        "required": ["summary"],
    },
    handler=_create_calendar_handler,
    tags=("google", "calendar", "calendars", "write"),
    parallel_safe=False,
    examples=("create work calendar", "new project calendar"),
)

GOOGLE_CALENDAR_UPDATE_CALENDAR = ToolSpec(
    name="google.calendar.update_calendar",
    description=GOOGLE_CALENDAR_OAUTH_HINT + "Update metadata (title, description, timezone) for a calendar.",
    parameters={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Google Calendar ID."},
            "summary": {"type": "string"},
            "description": {"type": "string"},
            "time_zone": {"type": "string", "description": "IANA timezone name."},
        },
        "required": ["calendar_id"],
    },
    handler=_update_calendar_handler,
    tags=("google", "calendar", "calendars", "write"),
    parallel_safe=False,
    examples=("rename calendar", "change calendar timezone"),
)

GOOGLE_CALENDAR_DELETE_CALENDAR = ToolSpec(
    name="google.calendar.delete_calendar",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Delete a secondary Google Calendar. Primary calendar cannot be deleted."
    ),
    parameters={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Secondary Google Calendar ID."},
        },
        "required": ["calendar_id"],
    },
    handler=_delete_calendar_handler,
    tags=("google", "calendar", "calendars", "write"),
    parallel_safe=False,
    examples=("delete secondary calendar", "remove project calendar"),
)

GOOGLE_CALENDAR_CLEAR_CALENDAR = ToolSpec(
    name="google.calendar.clear_calendar",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Delete all events from a secondary Google Calendar (requires confirm=true)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Secondary Google Calendar ID."},
            "confirm": {
                "type": "boolean",
                "description": "Must be true to clear all events.",
            },
        },
        "required": ["calendar_id", "confirm"],
    },
    handler=_clear_calendar_handler,
    tags=("google", "calendar", "calendars", "write"),
    parallel_safe=False,
    examples=("clear all events from project calendar", "wipe secondary calendar"),
)

GOOGLE_CALENDAR_IMPORT_EVENT = ToolSpec(
    name="google.calendar.import_event",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Import a private event copy without sending invitations (e.g. migrated iCal data). "
        "Prefer create_event for new events with attendees."
    ),
    parameters={
        "type": "object",
        "properties": _CREATE_EVENT_FIELDS,
        "required": ["summary", "start", "end"],
    },
    handler=_import_event_handler,
    tags=("google", "calendar", "write"),
    parallel_safe=False,
    examples=("import event copy", "migrate event into calendar"),
)

GOOGLE_CALENDAR_SET_CALENDAR_COLOR = ToolSpec(
    name="google.calendar.set_calendar_color",
    description=(
        GOOGLE_CALENDAR_OAUTH_HINT
        + "Set the display color of a calendar in the user's calendar list."
    ),
    parameters={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Google Calendar ID."},
            "color_id": {
                "type": "string",
                "description": "Calendar color ID from google.calendar.list_colors calendar_colors.",
            },
        },
        "required": ["calendar_id", "color_id"],
    },
    handler=_set_calendar_color_handler,
    tags=("google", "calendar", "colors", "write"),
    parallel_safe=False,
    examples=("make work calendar green", "change calendar color"),
)

GOOGLE_CALENDAR_CAL4_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_CALENDAR_LIST_CALENDARS,
    GOOGLE_CALENDAR_CREATE_CALENDAR,
    GOOGLE_CALENDAR_UPDATE_CALENDAR,
    GOOGLE_CALENDAR_DELETE_CALENDAR,
    GOOGLE_CALENDAR_CLEAR_CALENDAR,
    GOOGLE_CALENDAR_IMPORT_EVENT,
    GOOGLE_CALENDAR_SET_CALENDAR_COLOR,
)

GOOGLE_CALENDAR_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_CALENDAR_READ_TOOLS
    + GOOGLE_CALENDAR_WRITE_TOOLS
    + GOOGLE_CALENDAR_CAL3_TOOLS
    + GOOGLE_CALENDAR_CAL4_TOOLS
)
