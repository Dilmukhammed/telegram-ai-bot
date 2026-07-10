from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from bot.chat_store.models import ChatMessage
from memory.ingestion.models import ChatEvidenceRecord

if TYPE_CHECKING:
    from bot.chat_store.store import ChatStore
    from memory.ingestion.protocols import TextIngestSink

logger = logging.getLogger(__name__)

_sink: TextIngestSink | None = None


def set_text_ingest_sink(sink: TextIngestSink | None) -> None:
    global _sink
    _sink = sink


def notify_chat_ingested(*, user_id: int, message_ids: Sequence[int]) -> None:
    if not message_ids or _sink is None:
        return
    try:
        _sink.notify_chat_messages(user_id=user_id, message_ids=message_ids)
    except Exception:
        logger.exception(
            "memory_chat_ingest_notify_failed",
            extra={"event": "memory_chat_ingest_notify_failed", "user_id": user_id},
        )


def message_to_evidence_record(message: ChatMessage) -> ChatEvidenceRecord:
    return ChatEvidenceRecord(
        message_id=message.message_id,
        session_id=message.session_id,
        user_id=message.user_id,
        seq=message.seq,
        role=message.role,
        content=message.content,
        content_type=str(message.content_type),
        tool_call_id=message.tool_call_id,
        tool_name=message.tool_name,
        source_at=message.source_at,
        created_at=message.created_at,
        metadata=dict(message.metadata),
    )


class ChatEvidenceAdapter:
    def __init__(self, chat_store: ChatStore) -> None:
        self._chat_store = chat_store

    def max_message_id(self) -> int:
        return self._chat_store.max_message_id()

    def read_messages_after_id(self, message_id: int, *, limit: int) -> Sequence[ChatEvidenceRecord]:
        messages = self._chat_store.read_messages_after_id(message_id, limit=limit)
        return [message_to_evidence_record(message) for message in messages]

    def get_message_for_user(self, message_id: int, user_id: int) -> ChatEvidenceRecord | None:
        message = self._chat_store.get_message_for_user(message_id, user_id)
        if message is None:
            return None
        return message_to_evidence_record(message)
