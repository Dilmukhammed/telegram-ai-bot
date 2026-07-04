import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import get_settings

_USER_HOME_ADDRESS = "массив Мавлоно Риёзи, 28, Ташкент"
_USER_HOME_LAT = 41.313964
_USER_HOME_LNG = 69.326233


def build_runtime_context_prompt() -> str:
    """Date + user context appended to system prompt (stable within a calendar day for prompt cache)."""
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
        f"Use this when the user asks about today, yesterday, this week, or recent events.\n"
        f"User home address: {_USER_HOME_ADDRESS}. "
        f"Coordinates: {_USER_HOME_LAT}, {_USER_HOME_LNG}. "
        f"Use as default origin/destination for maps and travel when the user says «домой», «от дома», «до дома», or similar."
    )
