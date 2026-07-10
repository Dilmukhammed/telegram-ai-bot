from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

SessionStatus = Literal["active", "archived"]
SummaryStatus = Literal["pending", "done", "failed"]
PeriodType = Literal["day", "week", "month"]
ContentType = Literal["text", "tool_calls", "tool_result", "image_placeholder"]


@dataclass(frozen=True)
class ChatSession:
    session_id: str
    user_id: int
    status: SessionStatus
    summary: str | None
    summary_status: SummaryStatus | None
    title: str | None
    message_count: int
    created_at: datetime
    started_at: datetime | None
    last_message_at: datetime | None
    updated_at: datetime
    archived_at: datetime | None
    summary_started_at: datetime | None
    summary_completed_at: datetime | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ChatMessage:
    message_id: int
    session_id: str
    user_id: int
    seq: int
    role: str
    content: str | None
    content_type: ContentType
    tool_call_id: str | None
    tool_name: str | None
    source_at: datetime
    created_at: datetime
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ChatSessionTrace:
    trace_row_id: int
    session_id: str
    user_id: int
    turn_seq: int
    user_message: str
    assistant_reply: str
    trace: dict[str, Any]
    source_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class ChatPeriodSummary:
    period_id: str
    user_id: int
    period_type: PeriodType
    period_key: str
    title: str | None
    summary: str | None
    summary_status: SummaryStatus | None
    session_count: int
    source_session_ids: tuple[str, ...]
    coverage_start: datetime | None
    coverage_end: datetime | None
    summary_started_at: datetime | None
    summary_completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]
