from __future__ import annotations

from bot.chat_store.models import ChatSession


def _format_started(session: ChatSession) -> str:
    if session.started_at is None:
        return "—"
    return session.started_at.strftime("%Y-%m-%d %H:%M UTC")


def _short_session_id(session_id: str) -> str:
    return session_id[:8]


def format_sessions_list(sessions: list[ChatSession]) -> str:
    if not sessions:
        return "Нет сохранённых сессий."
    lines = ["<b>Chat sessions</b>", ""]
    for index, session in enumerate(sessions, start=1):
        title = session.title or "(no title)"
        summary = session.summary or "—"
        if len(summary) > 160:
            summary = summary[:159] + "…"
        lines.append(
            f"{index}. <code>{_short_session_id(session.session_id)}</code> "
            f"[{session.status}] {_format_started(session)}\n"
            f"   <b>{title}</b>\n"
            f"   {summary}\n"
            f"   messages={session.message_count}"
        )
    lines.append("")
    lines.append("Подробнее: /session &lt;session_id&gt;")
    return "\n".join(lines)


def format_session_detail(session: ChatSession, *, trace_count: int) -> str:
    title = session.title or "(no title)"
    summary = session.summary or "Summary ещё не готов."
    return (
        "<b>Chat session</b>\n"
        f"id: <code>{session.session_id}</code>\n"
        f"status: {session.status}\n"
        f"started: {_format_started(session)}\n"
        f"messages: {session.message_count}\n"
        f"traces: {trace_count}\n"
        f"summary_status: {session.summary_status or '—'}\n\n"
        f"<b>{title}</b>\n\n"
        f"{summary}"
    )
