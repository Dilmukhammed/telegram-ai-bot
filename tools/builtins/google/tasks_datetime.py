from __future__ import annotations

from datetime import date, datetime, time, timedelta

from tools.builtins.google.datetime_utils import resolve_timezone, to_rfc3339


def today_date(time_zone: str | None = None) -> date:
    tz = resolve_timezone(time_zone)
    return datetime.now(tz).date()


def due_bounds_for_day(target: date, time_zone: str | None = None) -> tuple[str, str]:
    tz = resolve_timezone(time_zone)
    start = datetime.combine(target, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return to_rfc3339(start), to_rfc3339(end)


def due_max_before_day(target: date, time_zone: str | None = None) -> str:
    tz = resolve_timezone(time_zone)
    start = datetime.combine(target, time.min, tzinfo=tz)
    return to_rfc3339(start)


def normalize_task_due(value: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("due must be a non-empty date or datetime string")
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        parsed = datetime.fromisoformat(text)
        return to_rfc3339(parsed.replace(hour=0, minute=0, second=0, microsecond=0))
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=resolve_timezone(None))
    return to_rfc3339(parsed)
