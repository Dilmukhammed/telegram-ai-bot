import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import get_settings


def build_runtime_context_prompt() -> str:
    """Date-only context so the system prompt stays stable within a calendar day (provider prompt cache)."""
    tz_name = get_settings().bot_timezone or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz_name = "UTC"
        tz = ZoneInfo("UTC")

    today = datetime.now(tz).date()
    weekday = today.strftime("%A")
    return (
        f"Today's date for the user: {today.isoformat()} ({weekday}), timezone {tz_name}. "
        f"Use this when the user asks about today, yesterday, this week, or recent events."
    )
