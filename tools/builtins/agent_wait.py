from __future__ import annotations

import asyncio
from typing import Any

from tools.schema import ToolSpec

_MIN_SECONDS = 0.5
_MAX_SECONDS = 120.0
_DEFAULT_SECONDS = 5.0


async def _wait_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    raw = arguments.get("seconds", _DEFAULT_SECONDS)
    try:
        seconds = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("seconds must be a number") from exc

    seconds = max(_MIN_SECONDS, min(seconds, _MAX_SECONDS))
    reason = str(arguments.get("reason") or "").strip() or None

    await asyncio.sleep(seconds)
    return {
        "ok": True,
        "waited_seconds": seconds,
        "capped_max": _MAX_SECONDS,
        "reason": reason,
    }


AGENT_WAIT_TOOL = ToolSpec(
    name="agent.wait",
    description=(
        "Pause the agent for a fixed number of seconds (wall-clock sleep), then continue. "
        "Use when you need to wait for something external: file upload/processing, user action, "
        "a slow side effect, or a short backoff before retrying. "
        "Not for browser DOM readiness — use browser.wait for selectors/text. "
        "Not a substitute for polling tools with their own wait args. "
        f"Clamped to {_MIN_SECONDS:g}–{_MAX_SECONDS:g} seconds per call."
    ),
    parameters={
        "type": "object",
        "properties": {
            "seconds": {
                "type": "number",
                "description": (
                    f"How long to sleep (default {_DEFAULT_SECONDS:g}, "
                    f"max {_MAX_SECONDS:g})."
                ),
                "default": _DEFAULT_SECONDS,
            },
            "reason": {
                "type": "string",
                "description": "Short note why you are waiting (for logs / your next step).",
            },
        },
        "required": [],
    },
    handler=_wait_handler,
    tags=("agent", "util", "wait"),
    cache_ttl_seconds=None,
    rate_limit=(40, 60),
    parallel_safe=False,
    handler_timeout_seconds=_MAX_SECONDS + 5.0,
    checker_enabled=False,
    examples=(
        "wait a few seconds",
        "sleep before retry",
        "pause for file upload",
        "wait for user to finish",
    ),
)
