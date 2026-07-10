from __future__ import annotations

import contextvars
from dataclasses import dataclass

COACH_REPLY_TOOL_NAME = "coach.reply"
MAX_COACH_REPLY_CHARS = 4000


@dataclass
class CoachWorkerReply:
    message: str
    turn: int
    tool_calls_at: int
    tool_step_index: int = 0

    def to_dict(self) -> dict[str, str | int]:
        return {
            "message": self.message,
            "turn": self.turn,
            "tool_calls_at": self.tool_calls_at,
            "tool_step_index": self.tool_step_index,
        }


_replies: contextvars.ContextVar[list[CoachWorkerReply] | None] = contextvars.ContextVar(
    "coach_worker_replies",
    default=None,
)

_reply_dispatch: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "coach_reply_dispatch",
    default=None,
)


def bind_coach_reply_dispatch(*, tool_calls_at: int, tool_step_index: int) -> None:
    _reply_dispatch.set(
        {"tool_calls_at": tool_calls_at, "tool_step_index": tool_step_index},
    )


def clear_coach_reply_dispatch() -> None:
    _reply_dispatch.set(None)


def _coach_reply_dispatch_meta() -> dict[str, int]:
    meta = _reply_dispatch.get()
    if not meta:
        return {"tool_calls_at": 0, "tool_step_index": 0}
    return meta


def reset_coach_dialog() -> None:
    _replies.set([])


def record_coach_worker_reply(
    *,
    message: str,
    turn: int,
    tool_calls_at: int,
    tool_step_index: int,
) -> CoachWorkerReply:
    text = message.strip()
    if len(text) > MAX_COACH_REPLY_CHARS:
        text = f"{text[: MAX_COACH_REPLY_CHARS - 1]}…"
    entry = CoachWorkerReply(
        message=text,
        turn=turn,
        tool_calls_at=tool_calls_at,
        tool_step_index=tool_step_index,
    )
    replies = list(_replies.get() or [])
    replies.append(entry)
    _replies.set(replies)
    return entry


def get_coach_worker_replies() -> list[CoachWorkerReply]:
    stored = _replies.get()
    return list(stored) if stored is not None else []


def is_coach_reply_tool(tool_name: str | None) -> bool:
    return tool_name == COACH_REPLY_TOOL_NAME


def is_billable_meta_tool_call(meta_tool: str, target_tool: str | None = None) -> bool:
    if meta_tool == "use_tool" and is_coach_reply_tool(target_tool):
        return False
    return True
