"""Archive active chat sessions at day boundary so period digests can cover yesterday."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from bot.chat_store import meta as meta_ops
from bot.chat_store.period_boundary import list_chat_user_ids
from bot.chat_store.period_keys import closed_period_keys, parse_period_key
from bot.chat_store.summary import enqueue_session_summary
from config import get_settings

logger = logging.getLogger(__name__)

_META_LAST_DAY_ARCHIVE = "day_boundary_archived"
_day_archive_callbacks: list[Callable[[int], None]] = []


def register_day_archive_callback(callback: Callable[[int], None]) -> None:
    _day_archive_callbacks.append(callback)


def _notify_day_archive(user_id: int) -> None:
    for callback in _day_archive_callbacks:
        try:
            callback(user_id)
        except Exception:
            logger.exception("day_archive callback failed user_id=%s", user_id)


def _last_archived_day(store) -> str | None:
    with store._connect() as conn:
        return meta_ops.get_meta(conn, _META_LAST_DAY_ARCHIVE)


def _mark_day_archived(store, day_key: str) -> None:
    with store._connect() as conn:
        meta_ops.set_meta(conn, _META_LAST_DAY_ARCHIVE, day_key)
        conn.commit()


def pending_day_archive_keys(
    store,
    *,
    now: datetime | None = None,
    tz_name: str | None = None,
) -> list[str]:
    """Closed local days that still need a day-boundary archive pass."""
    settings = get_settings()
    tz_name = tz_name or settings.bot_timezone
    now = now or datetime.now(timezone.utc)
    target = closed_period_keys(now, tz_name)["day"]
    last = _last_archived_day(store)
    if last is None:
        return [target]
    if last >= target:
        return []

    keys: list[str] = []
    cursor = date.fromisoformat(parse_period_key("day", last)) + timedelta(days=1)
    end = date.fromisoformat(parse_period_key("day", target))
    while cursor <= end:
        keys.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return keys


async def archive_active_sessions_for_closed_day(
    store,
    *,
    closed_day_key: str,
    tz_name: str | None = None,
) -> dict[str, int]:
    """
    Archive non-empty active sessions once per closed calendar day.

    Each archived slice becomes input for session + day period summaries.
    """
    settings = get_settings()
    if not settings.chat_day_archive_enabled:
        return {"users": 0, "archived": 0, "skipped": 0}

    tz_name = tz_name or settings.bot_timezone
    closed_day_key = parse_period_key("day", closed_day_key)
    users = list_chat_user_ids(store)
    archived = 0
    skipped = 0

    for user_id in users:
        active = store.get_active_session(user_id)
        if active is None or active.message_count == 0:
            skipped += 1
            continue

        archived_session, _created = store.archive_and_create_active(
            user_id,
            closed_by="day_boundary",
            opened_by="day_boundary",
            metadata_patch={"closed_day": closed_day_key},
        )
        if archived_session is None:
            skipped += 1
            continue

        archived += 1
        logger.info(
            "chat_day_archive user_id=%s session_id=%s messages=%s closed_day=%s",
            user_id,
            archived_session.session_id,
            archived_session.message_count,
            closed_day_key,
        )
        if settings.chat_session_summary_on_archive:
            enqueue_session_summary(store, archived_session.session_id)
        _notify_day_archive(user_id)

    _mark_day_archived(store, closed_day_key)
    return {"users": len(users), "archived": archived, "skipped": skipped}


async def run_day_archives_for_pending_days(
    store=None,
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, int]]:
    from bot.chat_store import get_chat_store

    settings = get_settings()
    if not settings.chat_day_archive_enabled:
        return {}

    store = store or get_chat_store()
    now = now or datetime.now(timezone.utc)
    tz_name = settings.bot_timezone
    results: dict[str, dict[str, int]] = {}
    for day_key in pending_day_archive_keys(store, now=now, tz_name=tz_name):
        logger.info("day_archive closing day=%s tz=%s", day_key, tz_name)
        results[day_key] = await archive_active_sessions_for_closed_day(
            store,
            closed_day_key=day_key,
            tz_name=tz_name,
        )
        logger.info(
            "day_archive closed day=%s archived=%s skipped=%s users=%s",
            day_key,
            results[day_key]["archived"],
            results[day_key]["skipped"],
            results[day_key]["users"],
        )
    return results
