from datetime import datetime, timedelta, timezone

from config import get_settings


def gap_prefix_minutes() -> int:
    return max(0, get_settings().message_gap_minutes)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _plural(value: int, singular: str, plural: str) -> str:
    return singular if value == 1 else plural


def format_elapsed(delta: timedelta) -> str:
    total_minutes = int(delta.total_seconds()) // 60
    days = total_minutes // (24 * 60)
    hours = (total_minutes % (24 * 60)) // 60
    minutes = total_minutes % 60

    parts: list[str] = []
    if days:
        parts.append(f"{days} {_plural(days, 'day', 'days')}")
    if hours:
        parts.append(f"{hours} {_plural(hours, 'hour', 'hours')}")
    if not days and not hours and minutes:
        parts.append(f"{minutes} {_plural(minutes, 'minute', 'minutes')}")
    elif not days and hours and minutes:
        parts.append(f"{minutes} {_plural(minutes, 'minute', 'minutes')}")

    return " ".join(parts)


def build_gap_prefix(previous_at: datetime | None, current_at: datetime) -> str | None:
    if previous_at is None:
        return None

    previous = _ensure_utc(previous_at)
    current = _ensure_utc(current_at)
    delta = current - previous
    if delta.total_seconds() < gap_prefix_minutes() * 60:
        return None

    elapsed = format_elapsed(delta)
    return f"[gap: {elapsed} since your last message]"


def prefix_message_if_gap(
    text: str,
    previous_at: datetime | None,
    current_at: datetime,
) -> str:
    prefix = build_gap_prefix(previous_at, current_at)
    if not prefix:
        return text
    return f"{prefix}\n\n{text}"
