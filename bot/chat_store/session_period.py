"""Session ↔ calendar period overlap helpers (bot timezone)."""

from __future__ import annotations

from datetime import date

from bot.chat_store.models import ChatSession, PeriodType
from bot.chat_store.period_keys import parse_period_key, period_date_span, to_local_date


def session_local_date_span(session: ChatSession, tz_name: str) -> tuple[date, date] | None:
    start = session.started_at or session.created_at
    if start is None:
        return None
    end = (
        session.last_message_at
        or session.archived_at
        or session.updated_at
        or start
    )
    local_start = to_local_date(start, tz_name)
    local_end = to_local_date(end, tz_name)
    if local_end < local_start:
        local_start, local_end = local_end, local_start
    return local_start, local_end


def ranges_overlap(
    a_start: date,
    a_end: date,
    b_start: date,
    b_end: date,
) -> bool:
    return a_start <= b_end and b_start <= a_end


def session_overlaps_period(
    session: ChatSession,
    *,
    period_type: PeriodType | str,
    period_key: str,
    tz_name: str,
) -> bool:
    span = session_local_date_span(session, tz_name)
    if span is None:
        return False
    session_start, session_end = span
    period_start, period_end = period_date_span(str(period_type), period_key)
    return ranges_overlap(session_start, session_end, period_start, period_end)


def session_overlaps_day(session: ChatSession, day_key: str, tz_name: str) -> bool:
    return session_overlaps_period(
        session,
        period_type="day",
        period_key=parse_period_key("day", day_key),
        tz_name=tz_name,
    )
