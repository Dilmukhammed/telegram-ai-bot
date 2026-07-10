"""Close day/week/month digests when the period boundary passes in BOT_TIMEZONE."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from bot.chat_store import meta as meta_ops
from bot.chat_store.models import PeriodType
from bot.chat_store.period_keys import closed_period_keys, current_period_keys
from bot.chat_store.period_summary import summarize_period
from config import get_settings

logger = logging.getLogger(__name__)

_META_PREFIX = "period_boundary_closed:"
_PERIOD_TYPES: tuple[PeriodType, ...] = ("day", "week", "month")


def list_chat_user_ids(store) -> list[int]:
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM chat_sessions ORDER BY user_id"
        ).fetchall()
    return [int(row["user_id"]) for row in rows]


def _meta_key(period_type: PeriodType | str) -> str:
    return f"{_META_PREFIX}{period_type}"


def _already_closed(store, period_type: PeriodType | str, period_key: str) -> bool:
    with store._connect() as conn:
        return meta_ops.get_meta(conn, _meta_key(period_type)) == period_key


def _mark_closed(store, period_type: PeriodType | str, period_key: str) -> None:
    with store._connect() as conn:
        meta_ops.set_meta(conn, _meta_key(period_type), period_key)
        conn.commit()


async def close_period_for_all_users(
    store,
    *,
    period_type: PeriodType | str,
    period_key: str,
) -> dict[str, int]:
    """Generate digests for one closed period across all users with chat history."""
    users = list_chat_user_ids(store)
    ok = 0
    skipped = 0
    failed = 0
    for user_id in users:
        try:
            result = await summarize_period(
                store,
                user_id=user_id,
                period_type=period_type,  # type: ignore[arg-type]
                period_key=period_key,
                force=False,
            )
            if result.get("ok"):
                ok += 1
            elif "No archived sessions" in str(result.get("error") or ""):
                skipped += 1
            elif "not ready" in str(result.get("error") or "").lower():
                skipped += 1
            else:
                failed += 1
                logger.warning(
                    "period_boundary user=%s %s %s result=%s",
                    user_id,
                    period_type,
                    period_key,
                    result,
                )
        except Exception:
            failed += 1
            logger.exception(
                "period_boundary failed user=%s %s %s",
                user_id,
                period_type,
                period_key,
            )
    return {"users": len(users), "ok": ok, "skipped": skipped, "failed": failed}


async def run_period_boundary_once(
    store=None,
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, int]]:
    """
    If local day/week/month rolled over since last mark, close the previous period.

    Idempotent via chat_store_meta keys period_boundary_closed:{day,week,month}.
    """
    from bot.chat_store import get_chat_store

    settings = get_settings()
    if not settings.chat_period_summary_enabled:
        return {}
    if not settings.chat_period_summary_boundary_enabled:
        return {}

    store = store or get_chat_store()
    now = now or datetime.now(timezone.utc)
    tz_name = settings.bot_timezone
    closed = closed_period_keys(now, tz_name)
    # Also useful for logs: which periods are still open.
    _ = current_period_keys(now, tz_name)

    results: dict[str, dict[str, int]] = {}
    for period_type in _PERIOD_TYPES:
        period_key = closed[period_type]
        if _already_closed(store, period_type, period_key):
            continue
        logger.info(
            "period_boundary closing %s=%s tz=%s",
            period_type,
            period_key,
            tz_name,
        )
        stats = await close_period_for_all_users(
            store,
            period_type=period_type,
            period_key=period_key,
        )
        _mark_closed(store, period_type, period_key)
        results[period_type] = stats
        logger.info(
            "period_boundary closed %s=%s users=%s ok=%s skipped=%s failed=%s",
            period_type,
            period_key,
            stats["users"],
            stats["ok"],
            stats["skipped"],
            stats["failed"],
        )
    return results


async def period_boundary_loop() -> None:
    settings = get_settings()
    if not settings.chat_period_summary_enabled:
        return
    if not settings.chat_period_summary_boundary_enabled:
        return

    interval = max(30, int(settings.chat_period_summary_boundary_poll_seconds))
    logger.info(
        "period_boundary loop started tz=%s poll=%ss",
        settings.bot_timezone,
        interval,
    )
    # Catch up immediately on boot (e.g. bot was down overnight).
    try:
        await run_period_boundary_once()
    except Exception:
        logger.exception("period_boundary startup catch-up failed")

    while True:
        await asyncio.sleep(interval)
        try:
            await run_period_boundary_once()
        except Exception:
            logger.exception("period_boundary loop tick failed")


def enqueue_period_boundary_loop() -> asyncio.Task[None] | None:
    settings = get_settings()
    if not settings.chat_period_summary_enabled:
        return None
    if not settings.chat_period_summary_boundary_enabled:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return loop.create_task(period_boundary_loop())
