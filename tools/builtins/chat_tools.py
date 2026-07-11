from __future__ import annotations

from typing import Any

from bot.chat_store.encode import row_to_message_dict
from bot.chat_store.session_period import session_overlaps_day
from bot.chat_store.models import ChatMessage, ChatSession, SessionStatus
from config import get_settings
from tools.builtins.chat_checker import CHAT_CHECKER_QUESTIONS_BY_TOOL
from tools.context import get_run_context
from tools.schema import ToolSpec

_READ_RATE_LIMIT = (120, 60)


def _chat_store():
    from bot.chat_store import get_chat_store

    return get_chat_store()


def _require_user_id() -> int:
    ctx = get_run_context()
    if ctx.user_id is None:
        raise RuntimeError("Chat tools require an authenticated Telegram user context")
    return ctx.user_id


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _session_payload(session: ChatSession, *, include_summary: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": session.session_id,
        "status": session.status,
        "message_count": session.message_count,
        "created_at": _iso(session.created_at),
        "started_at": _iso(session.started_at),
        "last_message_at": _iso(session.last_message_at),
        "archived_at": _iso(session.archived_at),
        "summary_status": session.summary_status,
        "title": session.title,
    }
    if include_summary:
        payload["summary"] = session.summary
    return payload


def _message_payload(message: ChatMessage) -> dict[str, Any]:
    payload = row_to_message_dict(message)
    payload["message_id"] = message.message_id
    payload["session_id"] = message.session_id
    payload["seq"] = message.seq
    payload["content_type"] = message.content_type
    payload["source_at"] = _iso(message.source_at)
    if message.tool_name:
        payload["tool_name"] = message.tool_name
    return payload


def _turn_payload(turn_number: int, messages: list[ChatMessage]) -> dict[str, Any]:
    return {
        "turn": turn_number,
        "messages": [_message_payload(message) for message in messages],
        "message_count": len(messages),
    }


def _get_owned_session(session_id: str, user_id: int) -> ChatSession | None:
    session_id = session_id.strip()
    if not session_id:
        raise ValueError("session_id is required")
    return _chat_store().get_session_for_user(session_id, user_id)


async def _sessions_list_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    status_raw = arguments.get("status")
    status: SessionStatus | None = None
    if status_raw is not None:
        status = str(status_raw).strip().lower()
        if status not in {"active", "archived"}:
            raise ValueError("status must be 'active', 'archived', or omitted")
    date_raw = arguments.get("date")
    date = str(date_raw).strip()[:10] if date_raw else None
    limit = int(arguments.get("limit", 20))
    limit = max(1, min(limit, 100))

    sessions = _chat_store().list_sessions(user_id, status=status, limit=limit)
    if date:
        tz_name = get_settings().bot_timezone
        sessions = [
            session
            for session in sessions
            if session_overlaps_day(session, date, tz_name)
        ]
    return {
        "ok": True,
        "sessions": [_session_payload(session, include_summary=True) for session in sessions],
        "count": len(sessions),
        "date": date,
    }


async def _session_summary_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    session_id = str(arguments.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("session_id is required")

    store = _chat_store()
    session = store.get_session_for_user(session_id, user_id)
    if session is None:
        return {"ok": False, "error": f"Session not found: {session_id}"}

    return {
        "ok": True,
        "session": _session_payload(session, include_summary=True),
        "trace_count": store.count_session_traces(session_id),
    }


async def _search_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    from bot.chat_index.search import search_chat_chunks

    user_id = _require_user_id()
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")

    session_id_raw = arguments.get("session_id")
    session_id = str(session_id_raw).strip() if session_id_raw else None
    if session_id:
        session = _get_owned_session(session_id, user_id)
        if session is None:
            return {"ok": False, "error": f"Session not found: {session_id}"}

    date_raw = arguments.get("date")
    date = str(date_raw).strip()[:10] if date_raw else None
    top_k_raw = arguments.get("top_k")
    top_k = int(top_k_raw) if top_k_raw is not None else get_settings().chat_search_top_k

    hits = await search_chat_chunks(
        user_id,
        query,
        session_id=session_id,
        date=date,
        top_k=top_k,
    )
    return {
        "ok": True,
        "query": query,
        "session_id": session_id,
        "date": date,
        "hits": hits,
        "count": len(hits),
        "hint": "If a hit includes tool_ref, use tool_results.get for exact archived tool payload.",
    }


async def _turns_read_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    from bot.chat_index.turns import parse_turn_spec

    user_id = _require_user_id()
    session_id = str(arguments.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("session_id is required")

    session = _get_owned_session(session_id, user_id)
    if session is None:
        return {"ok": False, "error": f"Session not found: {session_id}"}

    turn_numbers = parse_turn_spec(arguments.get("turns"))
    grouped = _chat_store().read_turns(session_id, turn_numbers)
    missing = [turn for turn in turn_numbers if turn not in grouped]
    return {
        "ok": True,
        "session_id": session_id,
        "turns": [_turn_payload(turn, grouped[turn]) for turn in turn_numbers if turn in grouped],
        "missing_turns": missing,
        "count": len(grouped),
    }


def _period_tool_payload(period) -> dict[str, Any]:
    return {
        "period_id": period.period_id,
        "period_type": period.period_type,
        "period_key": period.period_key,
        "title": period.title,
        "summary": period.summary,
        "summary_status": period.summary_status,
        "session_count": period.session_count,
        "source_session_ids": list(period.source_session_ids),
        "coverage_start": _iso(period.coverage_start),
        "coverage_end": _iso(period.coverage_end),
        "summary_completed_at": _iso(period.summary_completed_at),
    }


async def _periods_list_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    period_type_raw = arguments.get("period_type")
    period_type = str(period_type_raw).strip().lower() if period_type_raw else None
    if period_type is not None and period_type not in {"day", "week", "month"}:
        raise ValueError("period_type must be 'day', 'week', 'month', or omitted")
    limit = int(arguments.get("limit", 20))
    limit = max(1, min(limit, 100))
    periods = _chat_store().list_period_summaries(
        user_id,
        period_type=period_type,
        limit=limit,
    )
    return {
        "ok": True,
        "periods": [_period_tool_payload(item) for item in periods],
        "count": len(periods),
        "period_type": period_type,
        "hint": (
            "Keys use BOT_TIMEZONE: day=YYYY-MM-DD, week=YYYY-Www (ISO), month=YYYY-MM. "
            "Use chat.period.summary to fetch/generate one digest."
        ),
    }


async def _period_summary_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    from bot.chat_store.period_summary import ensure_period_summary

    user_id = _require_user_id()
    period_type = str(arguments.get("period_type") or "").strip().lower()
    period_key = str(arguments.get("period_key") or "").strip()
    if period_type not in {"day", "week", "month"}:
        raise ValueError("period_type must be day, week, or month")
    if not period_key:
        raise ValueError("period_key is required")

    result = await ensure_period_summary(
        _chat_store(),
        user_id=user_id,
        period_type=period_type,
        period_key=period_key,
    )
    return result


CHAT_SESSIONS_LIST = ToolSpec(
    name="chat.sessions.list",
    description=(
        "List the current user's chat sessions with summary, dates, and message counts. "
        "Optional date filter matches sessions with activity on that local day (YYYY-MM-DD)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["active", "archived"],
                "description": "Optional filter by session status.",
            },
            "date": {
                "type": "string",
                "description": "Optional YYYY-MM-DD filter on session activity (bot timezone).",
            },
            "limit": {
                "type": "integer",
                "default": 20,
                "description": "Max sessions to return (1-100).",
            },
        },
    },
    handler=_sessions_list_handler,
    tags=("chat", "history", "archive", "sessions"),
    verification_questions=CHAT_CHECKER_QUESTIONS_BY_TOOL["chat.sessions.list"],
    cache_ttl_seconds=None,
    rate_limit=_READ_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "list chat sessions from a specific date",
        "show archived sessions",
    ),
)

CHAT_SESSION_SUMMARY = ToolSpec(
    name="chat.session.summary",
    description=(
        "Get LLM-generated summary and metadata for one chat session. "
        "Summary is built from run traces when the session is archived."
    ),
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session id from chat.sessions.list or chat.search.",
            },
        },
        "required": ["session_id"],
    },
    handler=_session_summary_handler,
    tags=("chat", "history", "archive", "sessions"),
    verification_questions=CHAT_CHECKER_QUESTIONS_BY_TOOL["chat.session.summary"],
    cache_ttl_seconds=None,
    rate_limit=_READ_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "get archived session summary",
        "read metadata for past chat session",
    ),
)

CHAT_SEARCH = ToolSpec(
    name="chat.search",
    description=(
        "Hybrid semantic + Unicode lexical search over stored chat history. "
        "Returns diverse top matches with session metadata, turn, turn_context, and tool_ref. "
        "Optional session_id or date (message activity day, YYYY-MM-DD) narrows the search scope."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language or keyword query.",
            },
            "session_id": {
                "type": "string",
                "description": "Optional session scope.",
            },
            "date": {
                "type": "string",
                "description": "Optional YYYY-MM-DD filter on session activity (bot timezone).",
            },
            "top_k": {
                "type": "integer",
                "default": 5,
                "description": "Number of chunks to return (1-20).",
            },
        },
        "required": ["query"],
    },
    handler=_search_handler,
    tags=("chat", "history", "archive", "search"),
    verification_questions=CHAT_CHECKER_QUESTIONS_BY_TOOL["chat.search"],
    cache_ttl_seconds=None,
    rate_limit=_READ_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "search past chats about cafes",
        "find earlier conversation on a topic",
    ),
)

CHAT_TURNS_READ = ToolSpec(
    name="chat.turns.read",
    description=(
        "Read stored chat history for specific turns in a session. "
        "turns=5 for one turn; turns=[5,10] inclusive range; turns=[3,7,12] for discrete turns."
    ),
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session id from chat.search or chat.sessions.list.",
            },
            "turns": {
                "description": (
                    "Turn selector: integer, [from,to] inclusive range, or list of turn numbers."
                ),
            },
        },
        "required": ["session_id", "turns"],
    },
    handler=_turns_read_handler,
    tags=("chat", "history", "archive", "messages"),
    verification_questions=CHAT_CHECKER_QUESTIONS_BY_TOOL["chat.turns.read"],
    cache_ttl_seconds=None,
    rate_limit=_READ_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "read turns 5 through 10 from archived session",
        "load turn 3 from past chat",
    ),
)

CHAT_PERIODS_LIST = ToolSpec(
    name="chat.periods.list",
    description=(
        "List precomputed chat period digests (day / week / month) for the current user. "
        "Keys use bot timezone: day=YYYY-MM-DD, week=YYYY-Www (ISO week), month=YYYY-MM."
    ),
    parameters={
        "type": "object",
        "properties": {
            "period_type": {
                "type": "string",
                "enum": ["day", "week", "month"],
                "description": "Optional filter by period grain.",
            },
            "limit": {
                "type": "integer",
                "default": 20,
                "description": "Max periods to return (1-100).",
            },
        },
    },
    handler=_periods_list_handler,
    tags=("chat", "history", "archive", "periods"),
    verification_questions=CHAT_CHECKER_QUESTIONS_BY_TOOL["chat.periods.list"],
    cache_ttl_seconds=None,
    rate_limit=_READ_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "list day digests",
        "show recent weekly chat summaries",
    ),
)

CHAT_PERIOD_SUMMARY = ToolSpec(
    name="chat.period.summary",
    description=(
        "Get a precomputed day/week/month chat digest. Returns cached summary when ready; "
        "otherwise builds it from archived session summaries. "
        "Use for 'what did we do yesterday/this week/last month' before diving into sessions."
    ),
    parameters={
        "type": "object",
        "properties": {
            "period_type": {
                "type": "string",
                "enum": ["day", "week", "month"],
                "description": "Grain of the digest.",
            },
            "period_key": {
                "type": "string",
                "description": (
                    "Period id in bot timezone: day=YYYY-MM-DD, "
                    "week=YYYY-Www (ISO, e.g. 2026-W28), month=YYYY-MM."
                ),
            },
        },
        "required": ["period_type", "period_key"],
    },
    handler=_period_summary_handler,
    tags=("chat", "history", "archive", "periods"),
    verification_questions=CHAT_CHECKER_QUESTIONS_BY_TOOL["chat.period.summary"],
    cache_ttl_seconds=None,
    rate_limit=_READ_RATE_LIMIT,
    parallel_safe=True,
    examples=(
        "summarize yesterday's chats",
        "what did we discuss last week",
        "monthly overview of past chats",
    ),
)

CHAT_TOOLS: tuple[ToolSpec, ...] = (
    CHAT_SESSIONS_LIST,
    CHAT_SESSION_SUMMARY,
    CHAT_SEARCH,
    CHAT_TURNS_READ,
    CHAT_PERIODS_LIST,
    CHAT_PERIOD_SUMMARY,
)
