from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class ChatEvidenceRecord:
    message_id: int
    session_id: str
    user_id: int
    seq: int
    role: str
    content: str | None
    content_type: str
    tool_call_id: str | None
    tool_name: str | None
    source_at: datetime
    created_at: datetime
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class ToolEvidenceRecord:
    ref: str
    display_ref: int
    user_id: int
    run_id: str | None
    tool_name: str
    turn: int
    payload_kind: str  # result | arguments | unknown_legacy
    payload_json: str
    args_json: str | None
    ok: bool
    cached: bool
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ChatCursor:
    last_message_id: int


@dataclass(frozen=True)
class ToolCursor:
    created_at: str
    ref: str


@dataclass(frozen=True)
class ReconcileCursor:
    last_source_id: str


class QueueEventKind(StrEnum):
    CHAT_MESSAGES = "chat_messages"
    TOOL_INSERTED = "tool_inserted"
    TOOL_DELETED = "tool_deleted"


@dataclass(frozen=True)
class QueueEvent:
    stream: str
    item_key: str
    user_id: int
    event_kind: QueueEventKind


class TextIngestionStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass(frozen=True)
class IngestionRuntimeStatus:
    status: TextIngestionStatus
    queue_size: int
    queue_maxsize: int
    streams_seen: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "streams_seen", MappingProxyType(dict(self.streams_seen)))
