"""Period key helpers for day / ISO week / month digests (bot timezone)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bot.chat_store.models import PeriodType


def resolve_tz(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def to_local_date(dt: datetime, tz_name: str) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(resolve_tz(tz_name)).date()


def day_key(d: date) -> str:
    return d.isoformat()


def week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def period_key_for(d: date, period_type: PeriodType) -> str:
    if period_type == "day":
        return day_key(d)
    if period_type == "week":
        return week_key(d)
    if period_type == "month":
        return month_key(d)
    raise ValueError(f"Unknown period_type: {period_type}")


def period_keys_for_date(d: date) -> dict[PeriodType, str]:
    return {
        "day": day_key(d),
        "week": week_key(d),
        "month": month_key(d),
    }


def parse_period_key(period_type: PeriodType | str, period_key: str) -> str:
    """Normalize / validate period_key; returns canonical key."""
    key = period_key.strip()
    if period_type == "day":
        # YYYY-MM-DD
        parsed = date.fromisoformat(key[:10])
        return day_key(parsed)
    if period_type == "week":
        # 2026-W28 or 2026-W28-1
        upper = key.upper()
        if "-W" not in upper:
            raise ValueError("week key must look like 2026-W28")
        year_s, week_s = upper.split("-W", 1)
        year = int(year_s)
        week = int(week_s.split("-")[0])
        if week < 1 or week > 53:
            raise ValueError("week must be 1-53")
        return f"{year}-W{week:02d}"
    if period_type == "month":
        # YYYY-MM
        parts = key.split("-")
        if len(parts) < 2:
            raise ValueError("month key must look like 2026-07")
        year = int(parts[0])
        month = int(parts[1])
        if month < 1 or month > 12:
            raise ValueError("month must be 1-12")
        return f"{year:04d}-{month:02d}"
    raise ValueError(f"Unknown period_type: {period_type}")


def current_period_keys(now: datetime, tz_name: str) -> dict[PeriodType, str]:
    return period_keys_for_date(to_local_date(now, tz_name))


def previous_day_key(d: date) -> str:
    return day_key(d - timedelta(days=1))


def previous_week_key(d: date) -> str:
    return week_key(d - timedelta(days=7))


def previous_month_key(d: date) -> str:
    if d.month == 1:
        return f"{d.year - 1:04d}-12"
    return f"{d.year:04d}-{d.month - 1:02d}"


def closed_period_keys(now: datetime, tz_name: str) -> dict[PeriodType, str]:
    """Keys for the most recently closed day / week / month in bot timezone."""
    local = to_local_date(now, tz_name)
    return {
        "day": previous_day_key(local),
        "week": previous_week_key(local),
        "month": previous_month_key(local),
    }


def period_date_span(period_type: PeriodType | str, period_key: str) -> tuple[date, date]:
    """Inclusive local-date span covered by a period key."""
    period_type = str(period_type).strip().lower()  # type: ignore[assignment]
    key = parse_period_key(period_type, period_key)
    if period_type == "day":
        day = date.fromisoformat(key)
        return day, day
    if period_type == "week":
        year_s, week_s = key.upper().split("-W", 1)
        year = int(year_s)
        week = int(week_s)
        start = date.fromisocalendar(year, week, 1)
        return start, start + timedelta(days=6)
    if period_type == "month":
        year_s, month_s = key.split("-", 1)
        year = int(year_s)
        month = int(month_s)
        start = date(year, month, 1)
        if month == 12:
            end = date(year, 12, 31)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        return start, end
    raise ValueError(f"Unknown period_type: {period_type}")
