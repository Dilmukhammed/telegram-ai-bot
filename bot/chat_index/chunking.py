from __future__ import annotations

import json
import re
from typing import Any

from bot.chat_store.models import ChatMessage, ChatSession
from config import get_settings

_TOKEN_RE = re.compile(r"[^\W_]+(?:[_-][^\W_]+)*", re.UNICODE)


def tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in _TOKEN_RE.findall(text.casefold()):
        tokens.add(match)
        if "_" in match or "-" in match:
            tokens.update(part for part in re.split(r"[_-]+", match) if part)
    return tokens


def token_list(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN_RE.findall(text.casefold()):
        tokens.append(match)
        if "_" in match or "-" in match:
            tokens.extend(part for part in re.split(r"[_-]+", match) if part)
    return tokens


def split_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_size)
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(cleaned):
            break
        start += step
    return chunks


def extract_tool_ref(content: str | None) -> int | None:
    if not content:
        return None
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    ref = payload.get("ref")
    if isinstance(ref, int):
        return ref
    if isinstance(ref, str) and ref.isdigit():
        return int(ref)
    return None


def searchable_text_from_message(message: ChatMessage) -> str:
    parts = [f"role={message.role}"]
    if message.tool_name:
        parts.append(f"tool={message.tool_name}")
    content = message.content or ""
    if message.content_type == "tool_result":
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            payload = None
        if isinstance(payload, dict) and payload.get("archived"):
            summary = str(payload.get("summary") or "").strip()
            tool_name = payload.get("tool_name")
            if tool_name:
                parts.append(f"tool={tool_name}")
            if summary:
                parts.append(summary)
            return " ".join(parts)
    parts.append(content)
    return " ".join(parts)


def session_metadata(session: ChatSession) -> dict[str, Any]:
    started_at = session.started_at.isoformat() if session.started_at else None
    return {
        "session_started_at": started_at,
        "session_title": session.title,
        "session_summary": session.summary,
    }


def chunk_message(
    message: ChatMessage,
    session: ChatSession,
    *,
    turn_number: int | None,
    seq_start: int | None,
    seq_end: int | None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    text = searchable_text_from_message(message)
    if not text.strip():
        return []

    meta = session_metadata(session)
    source_at = message.source_at.isoformat() if message.source_at else None
    tool_ref = extract_tool_ref(message.content)
    chunks: list[dict[str, Any]] = []
    for index, piece in enumerate(
        split_text(
            text,
            chunk_size=settings.chat_search_chunk_chars,
            overlap=settings.chat_search_chunk_overlap,
        )
    ):
        chunks.append(
            {
                "user_id": message.user_id,
                "session_id": message.session_id,
                "source_type": "message",
                "source_key": f"msg:{message.message_id}:{index}",
                "turn_number": turn_number,
                "seq_start": seq_start or message.seq,
                "seq_end": seq_end or message.seq,
                "tool_ref": tool_ref,
                "chunk_index": index,
                "text": piece,
                "source_at": source_at,
                **meta,
            }
        )
    return chunks


def chunk_tool_result_summary(
    *,
    user_id: int,
    session_id: str,
    session: ChatSession | None,
    display_ref: int,
    tool_name: str,
    summary: str,
) -> list[dict[str, Any]]:
    settings = get_settings()
    text = f"tool_result tool={tool_name} ref={display_ref} {summary.strip()}"
    meta = session_metadata(session) if session is not None else {
        "session_started_at": None,
        "session_title": None,
        "session_summary": None,
    }
    chunks: list[dict[str, Any]] = []
    for index, piece in enumerate(
        split_text(
            text,
            chunk_size=settings.chat_search_chunk_chars,
            overlap=settings.chat_search_chunk_overlap,
        )
    ):
        chunks.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "source_type": "tool_result",
                "source_key": f"ref:{display_ref}:{index}",
                "turn_number": None,
                "seq_start": None,
                "seq_end": None,
                "tool_ref": display_ref,
                "chunk_index": index,
                "text": piece,
                **meta,
            }
        )
    return chunks


def _payload_excerpt(payload_json: str) -> str:
    settings = get_settings()
    limit = max(500, settings.chat_index_payload_max_chars)
    text = payload_json.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def chunk_tool_result_payload(
    *,
    user_id: int,
    session_id: str,
    session: ChatSession | None,
    display_ref: int,
    tool_name: str,
    payload_json: str,
) -> list[dict[str, Any]]:
    excerpt = _payload_excerpt(payload_json)
    if not excerpt.strip():
        return []
    settings = get_settings()
    text = f"tool_result_payload tool={tool_name} ref={display_ref} {excerpt}"
    meta = session_metadata(session) if session is not None else {
        "session_started_at": None,
        "session_title": None,
        "session_summary": None,
    }
    chunks: list[dict[str, Any]] = []
    for index, piece in enumerate(
        split_text(
            text,
            chunk_size=settings.chat_search_chunk_chars,
            overlap=settings.chat_search_chunk_overlap,
        )
    ):
        chunks.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "source_type": "tool_result_payload",
                "source_key": f"ref:{display_ref}:payload:{index}",
                "turn_number": None,
                "seq_start": None,
                "seq_end": None,
                "tool_ref": display_ref,
                "chunk_index": index,
                "text": piece,
                **meta,
            }
        )
    return chunks


def chunks_for_tool_result(
    *,
    user_id: int,
    session_id: str,
    session: ChatSession | None,
    display_ref: int,
    tool_name: str,
    summary: str | None,
    payload_json: str,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    if summary and summary.strip():
        chunks.extend(
            chunk_tool_result_summary(
                user_id=user_id,
                session_id=session_id,
                session=session,
                display_ref=display_ref,
                tool_name=tool_name,
                summary=summary,
            )
        )
    chunks.extend(
        chunk_tool_result_payload(
            user_id=user_id,
            session_id=session_id,
            session=session,
            display_ref=display_ref,
            tool_name=tool_name,
            payload_json=payload_json,
        )
    )
    return chunks


def chunk_session_summary(session: ChatSession) -> list[dict[str, Any]]:
    summary = (session.summary or "").strip()
    if not summary:
        return []
    settings = get_settings()
    meta = session_metadata(session)
    chunks: list[dict[str, Any]] = []
    for index, piece in enumerate(
        split_text(
            f"session_summary {summary}",
            chunk_size=settings.chat_search_chunk_chars,
            overlap=settings.chat_search_chunk_overlap,
        )
    ):
        chunks.append(
            {
                "user_id": session.user_id,
                "session_id": session.session_id,
                "source_type": "session_summary",
                "source_key": f"session:{session.session_id}:{index}",
                "turn_number": None,
                "seq_start": None,
                "seq_end": None,
                "tool_ref": None,
                "chunk_index": index,
                "text": piece,
                **meta,
            }
        )
    return chunks
