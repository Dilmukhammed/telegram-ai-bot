from __future__ import annotations

from typing import Any

from agent.coach_dialog import (
    COACH_REPLY_TOOL_NAME,
    _coach_reply_dispatch_meta,
    record_coach_worker_reply,
)
from tools.context import get_run_context
from tools.schema import ToolSpec


async def _coach_reply_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    message = str(arguments.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")

    ctx = get_run_context()
    meta = _coach_reply_dispatch_meta()

    entry = record_coach_worker_reply(
        message=message,
        turn=ctx.turn,
        tool_calls_at=meta["tool_calls_at"],
        tool_step_index=meta["tool_step_index"],
    )
    return {
        "recorded": True,
        "chars": len(entry.message),
        "tool_calls_at": entry.tool_calls_at,
    }


COACH_REPLY_TOOL = ToolSpec(
    name=COACH_REPLY_TOOL_NAME,
    description=(
        "Send a correction or status update to the trajectory coach (internal only). "
        "Use when a coaching hint misstates your progress — e.g. you already finished a unit "
        "and moved to the next. Not shown to the user. Does not count toward coach review intervals."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": (
                    "Plain-language status for the coach: what is done, what you are doing now, "
                    "why the last coaching hint is wrong or outdated."
                ),
            },
        },
        "required": ["message"],
    },
    handler=_coach_reply_handler,
    tags=("coach", "agent", "internal"),
    cache_ttl_seconds=None,
    rate_limit=None,
    parallel_safe=False,
    examples=(
        "tell coach austrian gp tab is complete",
        "correct trajectory coach about current progress",
    ),
)
