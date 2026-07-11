"""Resolve Telegram reply-to-message quotes and inject agent context."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aiogram.types import ExternalReplyInfo, Message

from bot.chat_index.turns import group_messages_by_turn
from bot.chat_store import get_chat_store
from bot.chat_store.models import ChatMessage, ChatSession
from config import get_settings

if TYPE_CHECKING:
    from bot.chat_store.store import ChatStore

logger = logging.getLogger(__name__)

_TURN_SNIPPET_MAX_CHARS = 1600
_TURN_CONTEXT_MAX_CHARS = 3200
_SESSION_SUMMARY_MAX_CHARS = 500


@dataclass(frozen=True)
class ReplyContext:
    quoted_telegram_id: int | None
    quoted_role: str
    user_reply_text: str
    quoted_body: str
    source: str
    session_id: str | None = None
    session_status: str | None = None
    turn_number: int | None = None
    session_title: str | None = None
    session_summary: str | None = None
    is_cross_session: bool = False
    turn_maybe_trimmed: bool = False
    is_partial_quote: bool = False


@dataclass(frozen=True)
class _QuotedIncoming:
    telegram_message_id: int | None
    quoted_role: str
    telegram_text: str
    partial_quote_text: str | None = None
    is_partial_quote: bool = False


def _telegram_message_text(message: Message) -> str:
    if message.text:
        return message.text.strip()
    if message.caption:
        return message.caption.strip()
    if message.voice or message.audio:
        return "[voice message]"
    if message.photo:
        return "[photo]"
    if message.document:
        return "[document]"
    if message.sticker:
        return "[sticker]"
    if message.location:
        return "[location]"
    return ""


def _external_reply_text(external: ExternalReplyInfo) -> str:
    if external.audio or external.voice:
        return "[voice message]"
    if external.photo:
        return "[photo]"
    if external.document:
        return "[document]"
    if external.video:
        return "[video]"
    if external.video_note:
        return "[video message]"
    if external.sticker:
        return "[sticker]"
    if external.location:
        return "[location]"
    if external.contact:
        return "[contact]"
    if external.poll:
        return "[poll]"
    return ""


def _quoted_role(message: Message | None, *, default: str = "unknown") -> str:
    if message is None:
        return default
    sender = message.from_user
    if sender is not None and sender.is_bot:
        return "assistant"
    if sender is not None:
        return "user"
    return default


def _extract_quoted_incoming(telegram_message: Message) -> _QuotedIncoming | None:
    quote_text = ""
    quote_is_manual: bool | None = None
    quote = getattr(telegram_message, "quote", None)
    if quote is not None and getattr(quote, "text", None):
        quote_text = str(quote.text).strip()
        quote_is_manual = getattr(quote, "is_manual", None)

    def _incoming(
        *,
        telegram_message_id: int | None,
        quoted_role: str,
        telegram_text: str,
    ) -> _QuotedIncoming:
        if quote_text:
            return _QuotedIncoming(
                telegram_message_id=telegram_message_id,
                quoted_role=quoted_role,
                telegram_text=telegram_text,
                partial_quote_text=quote_text,
                is_partial_quote=True,
            )
        return _QuotedIncoming(
            telegram_message_id=telegram_message_id,
            quoted_role=quoted_role,
            telegram_text=telegram_text,
        )

    quoted = getattr(telegram_message, "reply_to_message", None)
    if quoted is not None:
        telegram_text = _telegram_message_text(quoted)
        return _incoming(
            telegram_message_id=int(quoted.message_id),
            quoted_role=_quoted_role(quoted),
            telegram_text=telegram_text or quote_text,
        )

    external = getattr(telegram_message, "external_reply", None)
    if external is not None and external.message_id is not None:
        telegram_text = quote_text or _external_reply_text(external)
        role = _quoted_role(None, default="unknown")
        if external.origin is not None:
            origin_type = getattr(external.origin, "type", None)
            if origin_type == "user":
                role = "user"
            elif origin_type in {"chat", "channel", "hidden_user"}:
                role = "assistant"
        return _incoming(
            telegram_message_id=int(external.message_id),
            quoted_role=role,
            telegram_text=telegram_text,
        )

    if quote_text:
        return _QuotedIncoming(
            telegram_message_id=None,
            quoted_role="unknown",
            telegram_text=quote_text,
            partial_quote_text=quote_text,
            is_partial_quote=quote_is_manual is not False,
        )

    return None


def _format_turn_context(messages: list[ChatMessage]) -> str:
    parts: list[str] = []
    for message in messages:
        content = (message.content or "").strip()
        if not content:
            continue
        if len(content) > _TURN_SNIPPET_MAX_CHARS:
            content = content[: _TURN_SNIPPET_MAX_CHARS - 1] + "…"
        label = message.role
        if message.tool_name:
            label = f"{label}:{message.tool_name}"
        parts.append(f"{label}: {content}")
    context = "\n".join(parts).strip()
    if len(context) > _TURN_CONTEXT_MAX_CHARS:
        context = context[: _TURN_CONTEXT_MAX_CHARS - 1] + "…"
    return context


def _turn_number_for_message(
    messages: list[ChatMessage],
    message_id: int,
) -> int | None:
    grouped = group_messages_by_turn(messages)
    for turn_number, turn_messages in grouped.items():
        if any(message.message_id == message_id for message in turn_messages):
            return turn_number
    return None


def _turn_maybe_trimmed(
    history: list[dict[str, Any]],
    *,
    turn_number: int,
) -> bool:
    if turn_number < 1:
        return False
    user_turn = 0
    kept_turn_numbers: list[int] = []
    for message in history:
        if message.get("role") != "user":
            continue
        user_turn += 1
        kept_turn_numbers.append(user_turn)
    if not kept_turn_numbers:
        return True
    max_turns = get_settings().chat_max_history
    visible = (
        kept_turn_numbers[-max_turns:]
        if len(kept_turn_numbers) > max_turns
        else kept_turn_numbers
    )
    return turn_number not in visible


def resolve_reply_context(
    telegram_message: Message,
    user_id: int,
    chat_store: ChatStore | None = None,
    *,
    prompt_history: list[dict[str, Any]] | None = None,
) -> ReplyContext | None:
    settings = get_settings()
    if not settings.telegram_reply_context_enabled:
        return None

    incoming = _extract_quoted_incoming(telegram_message)
    if incoming is None:
        return None

    store = chat_store or get_chat_store()
    quoted_telegram_id = incoming.telegram_message_id
    quoted_role = incoming.quoted_role
    telegram_text = incoming.telegram_text
    is_partial_quote = incoming.is_partial_quote

    db_message: ChatMessage | None = None
    if quoted_telegram_id is not None:
        db_message = store.find_message_by_telegram_id(user_id, quoted_telegram_id)
    session: ChatSession | None = None
    turn_number: int | None = None

    if is_partial_quote and incoming.partial_quote_text:
        quoted_body = incoming.partial_quote_text
        source = "telegram_partial_quote"
    else:
        quoted_body = telegram_text
        source = "telegram_only"

    if db_message is not None:
        session = store.get_session_for_user(db_message.session_id, user_id)
        session_messages = store.read_messages(db_message.session_id)
        turn_number = _turn_number_for_message(session_messages, db_message.message_id)
        if not is_partial_quote:
            if turn_number is not None:
                grouped = store.read_turns(db_message.session_id, [turn_number])
                turn_messages = grouped.get(turn_number) or []
                turn_context = _format_turn_context(turn_messages)
                if turn_context:
                    quoted_body = turn_context
                    source = "database_turn"
                elif (db_message.content or "").strip():
                    quoted_body = (db_message.content or "").strip()
                    source = "database_message"
            elif (db_message.content or "").strip():
                quoted_body = (db_message.content or "").strip()
                source = "database_message"
        elif source == "telegram_partial_quote":
            source = "telegram_partial_quote+database"

    active = store.get_active_session(user_id)
    active_session_id = active.session_id if active is not None else None
    is_cross_session = bool(
        db_message is not None
        and active_session_id is not None
        and db_message.session_id != active_session_id
    )

    turn_maybe_trimmed = False
    if (
        not is_cross_session
        and turn_number is not None
        and prompt_history is not None
    ):
        turn_maybe_trimmed = _turn_maybe_trimmed(
            prompt_history,
            turn_number=turn_number,
        )

    return ReplyContext(
        quoted_telegram_id=quoted_telegram_id,
        quoted_role=quoted_role,
        user_reply_text="",
        quoted_body=quoted_body,
        source=source,
        session_id=db_message.session_id if db_message is not None else None,
        session_status=session.status if session is not None else None,
        turn_number=turn_number,
        session_title=session.title if session is not None else None,
        session_summary=session.summary if session is not None else None,
        is_cross_session=is_cross_session,
        turn_maybe_trimmed=turn_maybe_trimmed,
        is_partial_quote=is_partial_quote,
    )


def _format_context_hint(ctx: ReplyContext, *, radius: int) -> list[str]:
    if ctx.session_id is None or ctx.turn_number is None:
        return []
    lo = max(1, ctx.turn_number - radius)
    hi = ctx.turn_number + radius
    lines = [
        "For surrounding context use "
        f"chat.turns.read({{'session_id': '{ctx.session_id}', 'turns': [{lo}, {hi}]}})"
    ]
    if ctx.is_cross_session or ctx.session_status == "archived":
        lines[0] += (
            f" and chat.session.summary({{'session_id': '{ctx.session_id}'}})"
        )
    return lines


def format_reply_block(ctx: ReplyContext, user_reply_text: str) -> str:
    settings = get_settings()
    radius = max(0, settings.telegram_reply_turn_radius)

    meta_parts = [
        f"role={ctx.quoted_role}",
        f"source={ctx.source}",
    ]
    if ctx.quoted_telegram_id is not None:
        meta_parts.insert(0, f"telegram_id={ctx.quoted_telegram_id}")
    if ctx.session_id:
        meta_parts.append(f"session_id={ctx.session_id}")
    if ctx.turn_number is not None:
        meta_parts.append(f"turn={ctx.turn_number}")
    if ctx.session_status:
        meta_parts.append(f"session_status={ctx.session_status}")
    if ctx.is_partial_quote:
        meta_parts.append("quote_scope=partial")

    label = "Quoted fragment" if ctx.is_partial_quote else "Quoted message"
    lines = [
        "[telegram-reply]",
        f"{label} ({', '.join(meta_parts)}):",
    ]
    body = ctx.quoted_body.strip()
    if body:
        for line in body.splitlines():
            lines.append(f"> {line}" if line else ">")
    else:
        lines.append("> (quoted message text unavailable)")

    lines.extend(["", "User reply:", user_reply_text])

    hint_lines: list[str] = []
    if ctx.is_partial_quote:
        hint_lines.append(
            "Hint: user quoted only a selected fragment from the parent message, "
            "not the full turn."
        )
        if ctx.session_id and ctx.turn_number is not None:
            hint_lines.extend(_format_context_hint(ctx, radius=radius))
        elif ctx.quoted_telegram_id is not None:
            hint_lines.append(
                "Parent telegram_id is known but session metadata was not found in storage. "
                "Use chat.search to locate the surrounding turn if needed."
            )
    elif ctx.is_cross_session and ctx.session_id and ctx.turn_number is not None:
        hint_lines.append(
            "Hint: quoted message is from a different session "
            f"({ctx.session_status or 'archived'})."
        )
        if ctx.session_title:
            hint_lines.append(f"Session title: {ctx.session_title}")
        if ctx.session_summary:
            summary = ctx.session_summary.strip()
            if len(summary) > _SESSION_SUMMARY_MAX_CHARS:
                summary = summary[: _SESSION_SUMMARY_MAX_CHARS - 1] + "…"
            hint_lines.append(f"Session summary: {summary}")
        hint_lines.extend(_format_context_hint(ctx, radius=radius))
    elif (
        ctx.session_id
        and ctx.turn_number is not None
        and ctx.turn_maybe_trimmed
    ):
        hint_lines.append(
            f"Hint: quoted turn {ctx.turn_number} may be outside the prompt window."
        )
        hint_lines.extend(_format_context_hint(ctx, radius=radius))

    if hint_lines:
        lines.append("")
        lines.extend(hint_lines)

    lines.append("[/telegram-reply]")
    return "\n".join(lines)


def apply_reply_context_prefix(
    user_text: str,
    *,
    telegram_message: Message | None,
    user_id: int,
    chat_store: ChatStore | None = None,
    prompt_history: list[dict[str, Any]] | None = None,
) -> str:
    if telegram_message is None:
        return user_text
    try:
        ctx = resolve_reply_context(
            telegram_message,
            user_id,
            chat_store,
            prompt_history=prompt_history,
        )
    except Exception:
        logger.exception(
            "telegram_reply_context failed user_id=%s message_id=%s",
            user_id,
            getattr(telegram_message, "message_id", None),
        )
        return user_text
    if ctx is None:
        return user_text
    return format_reply_block(ctx, user_reply_text=user_text)
