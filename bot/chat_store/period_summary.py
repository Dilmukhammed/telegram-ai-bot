"""Generate precomputed day / week / month chat digests from session summaries."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from bot.chat_store.models import ChatSession, PeriodType
from bot.chat_store.period_keys import (
    current_period_keys,
    parse_period_key,
    period_key_for,
)
from bot.chat_store.session_period import session_local_date_span, session_overlaps_period
from bot.chat_store.summary import _parse_title_and_summary
from config import Settings, get_settings
from llm import LLMClient

logger = logging.getLogger(__name__)

_PERIOD_TYPES: tuple[PeriodType, ...] = ("day", "week", "month")

_PERIOD_SUMMARY_SYSTEM = (
    "Respond with JSON only: {\"title\": \"...\", \"summary\": \"...\"}. "
    "title: short English headline for this time period, max 12 words. "
    "summary: 3-6 English sentences covering what the user worked on across sessions "
    "in this period — goals, tools/outcomes, open items. Do not invent facts. "
    "If session notes conflict, prefer later sessions."
)


def _sessions_for_period(
    sessions: Iterable[ChatSession],
    *,
    period_type: PeriodType,
    period_key: str,
    tz_name: str,
) -> list[ChatSession]:
    matched: list[ChatSession] = []
    for session in sessions:
        if not session_overlaps_period(
            session,
            period_type=period_type,
            period_key=period_key,
            tz_name=tz_name,
        ):
            continue
        matched.append(session)
    matched.sort(
        key=lambda s: (s.started_at or s.created_at).timestamp()
        if (s.started_at or s.created_at)
        else 0.0
    )
    return matched


def _format_sessions_for_period(
    sessions: list[ChatSession],
    *,
    max_chars: int,
) -> str:
    blocks: list[str] = []
    for session in sessions:
        title = session.title or "(untitled)"
        status = session.summary_status or "missing"
        summary = (session.summary or "").strip()
        if not summary:
            summary = f"(no session summary yet; status={status})"
        started = session.started_at.isoformat() if session.started_at else "?"
        blocks.append(
            f"=== Session {session.session_id} ===\n"
            f"title: {title}\n"
            f"started_at: {started}\n"
            f"messages: {session.message_count}\n"
            f"summary:\n{summary}"
        )
    text = "\n\n".join(blocks)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


async def summarize_period(
    store,
    *,
    user_id: int,
    period_type: PeriodType | str,
    period_key: str,
    force: bool = False,
) -> dict:
    """Build or refresh one period digest. Returns status payload."""
    from bot.chat_store import periods as period_ops

    settings = get_settings()
    if not settings.chat_period_summary_enabled:
        return {"ok": False, "error": "period summaries disabled"}

    period_type = str(period_type).strip().lower()  # type: ignore[assignment]
    if period_type not in _PERIOD_TYPES:
        return {"ok": False, "error": "period_type must be day, week, or month"}
    try:
        period_key = parse_period_key(period_type, period_key)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    tz_name = settings.bot_timezone
    # Load enough archived sessions (period may be older than last 50).
    sessions = store.list_sessions(user_id, status="archived", limit=500)
    matched = _sessions_for_period(
        sessions,
        period_type=period_type,  # type: ignore[arg-type]
        period_key=period_key,
        tz_name=tz_name,
    )
    if not matched:
        return {
            "ok": False,
            "error": f"No archived sessions for {period_type} {period_key}",
            "period_type": period_type,
            "period_key": period_key,
        }

    with_summary = [s for s in matched if (s.summary or "").strip()]
    if not with_summary and not force:
        return {
            "ok": False,
            "error": "Session summaries not ready yet for this period",
            "period_type": period_type,
            "period_key": period_key,
            "session_count": len(matched),
        }

    coverage_start = min(
        (s.started_at or s.created_at for s in matched),
        default=None,
    )
    coverage_end = max(
        (s.last_message_at or s.archived_at or s.updated_at for s in matched),
        default=None,
    )
    session_ids = [s.session_id for s in matched]

    with store._connect() as conn:
        existing = period_ops.get_period(conn, user_id, period_type, period_key)
        if (
            existing
            and existing.summary_status == "done"
            and existing.summary
            and not force
            and set(existing.source_session_ids) == set(session_ids)
        ):
            return {
                "ok": True,
                "cached": True,
                "period_id": existing.period_id,
                "period_type": period_type,
                "period_key": period_key,
                "summary_status": existing.summary_status,
            }
        period = period_ops.upsert_period_pending(
            conn,
            user_id=user_id,
            period_type=period_type,
            period_key=period_key,
            session_ids=session_ids,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
        )
        period_ops.update_period_summary_status(
            conn,
            period.period_id,
            summary_status="pending",
            summary_started_at=datetime.now(timezone.utc),
        )
        conn.commit()
        period_id = period.period_id

    formatted = _format_sessions_for_period(
        matched,
        max_chars=settings.chat_period_summary_max_input_chars,
    )
    llm = LLMClient(settings, profile="summarize")
    messages = [
        {"role": "system", "content": _PERIOD_SUMMARY_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Period type: {period_type}\n"
                f"Period key: {period_key}\n"
                f"Timezone: {tz_name}\n"
                f"Session count: {len(matched)}\n\n"
                f"Session notes:\n\n{formatted}"
            ),
        },
    ]

    title: str | None = None
    summary: str | None = None
    status = "failed"
    try:
        raw = (await llm.chat_without_reasoning(messages)).strip()
        title, summary = _parse_title_and_summary(raw)
        if len(summary) < 40:
            raise ValueError(f"summary too short ({len(summary)} chars)")
        status = "done"
    except Exception as exc:
        logger.warning(
            "chat_period_summary failed user=%s %s %s error=%s",
            user_id,
            period_type,
            period_key,
            exc,
            exc_info=True,
        )
        title = None
        summary = None
        status = "failed"

    completed_at = datetime.now(timezone.utc)
    with store._connect() as conn:
        period_ops.update_period_summary_status(
            conn,
            period_id,
            title=title,
            summary=summary,
            summary_status=status,  # type: ignore[arg-type]
            summary_completed_at=completed_at,
            session_count=len(matched),
            source_session_ids=session_ids,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
        )
        conn.commit()

    logger.info(
        "chat_period_summary %s user=%s %s %s sessions=%s chars=%s",
        status,
        user_id,
        period_type,
        period_key,
        len(matched),
        len(summary or ""),
    )
    return {
        "ok": status == "done",
        "cached": False,
        "period_id": period_id,
        "period_type": period_type,
        "period_key": period_key,
        "summary_status": status,
        "session_count": len(matched),
        "title": title,
        "summary": summary,
    }


async def refresh_periods_for_session(store, session_id: str) -> None:
    """After a session summary completes, refresh closed day/week/month digests."""
    settings = get_settings()
    if not settings.chat_period_summary_enabled:
        return
    if not settings.chat_period_summary_on_session_archive:
        return

    session = None
    with store._connect() as conn:
        from bot.chat_store import sessions as session_ops

        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is not None:
            session = session_ops.row_to_session(row)
    if session is None or session.status != "archived":
        return
    if not (session.summary or "").strip():
        return

    tz_name = settings.bot_timezone
    span = session_local_date_span(session, tz_name)
    if span is None:
        return
    session_start, session_end = span
    now_keys = current_period_keys(datetime.now(timezone.utc), tz_name)

    period_keys_by_type: dict[PeriodType, set[str]] = {t: set() for t in _PERIOD_TYPES}
    cursor = session_start
    while cursor <= session_end:
        for period_type in _PERIOD_TYPES:
            period_keys_by_type[period_type].add(
                period_key_for(cursor, period_type)
            )
        cursor += timedelta(days=1)

    for period_type in _PERIOD_TYPES:
        for key in sorted(period_keys_by_type[period_type]):
            if key == now_keys[period_type]:
                continue
            try:
                await summarize_period(
                    store,
                    user_id=session.user_id,
                    period_type=period_type,
                    period_key=key,
                    force=True,
                )
            except Exception:
                logger.exception(
                    "chat_period_summary refresh failed user=%s %s %s",
                    session.user_id,
                    period_type,
                    key,
                )


def enqueue_period_refresh_for_session(store, session_id: str) -> asyncio.Task | None:
    settings = get_settings()
    if not settings.chat_period_summary_enabled:
        return None
    if not settings.chat_period_summary_on_session_archive:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "chat_period_summary no event loop session_id=%s",
            session_id,
        )
        return None

    async def _run() -> None:
        try:
            await refresh_periods_for_session(store, session_id)
        except Exception:
            logger.exception(
                "chat_period_summary task failed session_id=%s",
                session_id,
            )

    task = loop.create_task(_run())
    logger.info("chat_period_summary queued after session_id=%s", session_id)
    return task


async def ensure_period_summary(
    store,
    *,
    user_id: int,
    period_type: PeriodType | str,
    period_key: str,
) -> dict:
    """Tool-facing: return existing done summary or generate on demand."""
    from bot.chat_store import periods as period_ops

    settings = get_settings()
    period_type = str(period_type).strip().lower()
    if period_type not in _PERIOD_TYPES:
        return {"ok": False, "error": "period_type must be day, week, or month"}
    try:
        period_key = parse_period_key(period_type, period_key)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    with store._connect() as conn:
        existing = period_ops.get_period(conn, user_id, period_type, period_key)
    if existing and existing.summary_status == "done" and existing.summary:
        return {
            "ok": True,
            "cached": True,
            "period": _period_payload(existing),
        }

    result = await summarize_period(
        store,
        user_id=user_id,
        period_type=period_type,  # type: ignore[arg-type]
        period_key=period_key,
        force=False,
    )
    if not result.get("ok"):
        return result
    with store._connect() as conn:
        period = period_ops.get_period(conn, user_id, period_type, period_key)
    if period is None:
        return {"ok": False, "error": "period summary missing after generate"}
    return {"ok": True, "cached": bool(result.get("cached")), "period": _period_payload(period)}


def _period_payload(period) -> dict:
    return {
        "period_id": period.period_id,
        "period_type": period.period_type,
        "period_key": period.period_key,
        "title": period.title,
        "summary": period.summary,
        "summary_status": period.summary_status,
        "session_count": period.session_count,
        "source_session_ids": list(period.source_session_ids),
        "coverage_start": period.coverage_start.isoformat() if period.coverage_start else None,
        "coverage_end": period.coverage_end.isoformat() if period.coverage_end else None,
        "summary_completed_at": (
            period.summary_completed_at.isoformat() if period.summary_completed_at else None
        ),
    }


# silence unused Settings import warning in type checkers
_ = Settings
