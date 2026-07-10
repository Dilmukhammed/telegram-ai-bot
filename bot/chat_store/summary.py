from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from agent.run_cycle_log import CycleLogOptions, build_run_cycle_log
from agent.run_trace import RunTrace
from bot.chat_store.models import ChatSessionTrace
from config import Settings, get_settings
from llm import LLMClient

logger = logging.getLogger(__name__)

_SESSION_SUMMARY_SYSTEM = (
    "Respond with JSON only: {\"title\": \"...\", \"summary\": \"...\"}. "
    "title: short English headline, max 10 words. "
    "summary: 2-4 English sentences on user goals, tools used, outcomes, open items. "
    "Do not invent facts."
)


def _parse_title_and_summary(raw: str) -> tuple[str | None, str]:
    text = raw.strip()
    if not text:
        return None, ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, text
    if not isinstance(payload, dict):
        return None, text
    title = str(payload.get("title") or "").strip() or None
    summary = str(payload.get("summary") or "").strip()
    if summary:
        return title, summary
    return title, text


def format_turn_trace_block(
    record: ChatSessionTrace,
    *,
    settings: Settings,
    per_turn_max_chars: int,
) -> str:
    trace = RunTrace.from_dict(record.trace)
    options = CycleLogOptions(
        step_limit=120,
        max_chars=max(1000, per_turn_max_chars - 400),
        include_collapse_tags=False,
        include_checker_reviews=False,
    )
    cycle_log = build_run_cycle_log(trace, settings=settings, options=options)
    reply_preview = record.assistant_reply.strip()
    if len(reply_preview) > 1200:
        reply_preview = reply_preview[:1199] + "…"
    return (
        f"=== Turn {record.turn_seq} ===\n"
        f"User: {record.user_message}\n"
        f"Assistant reply: {reply_preview}\n"
        f"Outcome: {trace.final_outcome or 'unknown'}\n"
        f"{cycle_log}"
    )


def format_session_traces_for_summary(
    traces: list[ChatSessionTrace],
    *,
    settings: Settings,
) -> str:
    if not traces:
        return ""

    per_turn_max = settings.chat_session_summary_per_turn_max_chars
    max_total = settings.chat_session_summary_max_input_chars
    selected = list(traces)

    def render(items: list[ChatSessionTrace]) -> str:
        blocks = [
            format_turn_trace_block(record, settings=settings, per_turn_max_chars=per_turn_max)
            for record in items
        ]
        return "\n\n".join(blocks)

    text = render(selected)
    while len(text) > max_total and len(selected) > 1:
        selected = selected[1:]
        text = render(selected)
    if len(text) > max_total:
        text = text[: max_total - 1] + "…"
    if len(selected) < len(traces):
        omitted = len(traces) - len(selected)
        text = f"[Note: {omitted} earliest turn(s) omitted to fit input budget]\n\n" + text
    return text


async def summarize_archived_session(store, session_id: str) -> None:
    from bot.chat_store import sessions as session_ops
    from bot.chat_store import traces as trace_ops

    settings = get_settings()
    if not settings.chat_session_summary_on_archive:
        return

    with store._connect() as conn:
        session = conn.execute(
            "SELECT session_id, status FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if session is None:
            logger.warning("chat_session_summary missing session_id=%s", session_id)
            return
        if session["status"] != "archived":
            logger.warning(
                "chat_session_summary skip not archived session_id=%s status=%s",
                session_id,
                session["status"],
            )
            return

        started_at = datetime.now(timezone.utc)
        session_ops.update_session_summary_status(
            conn,
            session_id,
            summary_status="pending",
            summary_started_at=started_at,
        )
        traces = trace_ops.list_session_traces(conn, session_id)
        conn.commit()

    formatted = format_session_traces_for_summary(traces, settings=settings)
    if not formatted.strip():
        logger.warning("chat_session_summary no traces session_id=%s", session_id)
        with store._connect() as conn:
            session_ops.update_session_summary_status(
                conn,
                session_id,
                summary_status="failed",
                summary_completed_at=datetime.now(timezone.utc),
            )
            conn.commit()
        return

    llm = LLMClient(settings, profile="summarize")
    messages = [
        {"role": "system", "content": _SESSION_SUMMARY_SYSTEM},
        {"role": "user", "content": f"Session trace log:\n\n{formatted}"},
    ]

    title: str | None = None
    summary: str | None = None
    try:
        raw = (await llm.chat_without_reasoning(messages)).strip()
        title, summary = _parse_title_and_summary(raw)
        if len(summary) < 40:
            raise ValueError(f"summary too short ({len(summary)} chars)")
        status = "done"
    except Exception as exc:
        logger.warning(
            "chat_session_summary failed session_id=%s error=%s",
            session_id,
            exc,
            exc_info=True,
        )
        summary = None
        title = None
        status = "failed"

    completed_at = datetime.now(timezone.utc)
    with store._connect() as conn:
        session_ops.update_session_summary_status(
            conn,
            session_id,
            title=title,
            summary=summary,
            summary_status=status,
            summary_completed_at=completed_at,
        )
        conn.commit()

    logger.info(
        "chat_session_summary %s session_id=%s turns=%s title=%s chars=%s",
        status,
        session_id,
        len(traces),
        title,
        len(summary or ""),
    )

    if status == "done" and summary:
        from bot.chat_index.sync import index_session_messages, index_session_summary
        from bot.chat_store.period_summary import enqueue_period_refresh_for_session

        index_session_summary(store, session_id)
        index_session_messages(store, session_id)
        enqueue_period_refresh_for_session(store, session_id)


def enqueue_session_summary(store, session_id: str) -> asyncio.Task[None] | None:
    settings = get_settings()
    if not settings.chat_session_summary_on_archive:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "chat_session_summary no event loop session_id=%s",
            session_id,
        )
        return None

    async def _run() -> None:
        try:
            await summarize_archived_session(store, session_id)
        except Exception:
            logger.exception("chat_session_summary task failed session_id=%s", session_id)

    task = loop.create_task(_run())
    logger.info("chat_session_summary queued session_id=%s", session_id)
    return task
