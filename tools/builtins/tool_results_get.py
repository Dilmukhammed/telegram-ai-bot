from __future__ import annotations

import json
from typing import Any

from tools.context import get_run_context
from tools.schema import ToolSpec
from tools.tool_results.families import SUMMARY_RELIABILITY_WARNING
from tools.tool_results.store import get_tool_result_store


def _parse_ref_argument(raw: Any) -> str | int:
    if raw is None:
        raise ValueError("Missing required argument: ref")
    if isinstance(raw, bool):
        raise ValueError("Invalid ref")
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if not text:
        raise ValueError("Missing required argument: ref")
    if text.isdigit():
        return int(text)
    return text


async def _tool_results_get_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    ref = _parse_ref_argument(arguments.get("ref"))
    mode = str(arguments.get("mode", "full")).strip().lower()
    if mode not in {"full", "summary"}:
        raise ValueError("mode must be 'full' or 'summary'")

    ctx = get_run_context()
    if ctx.user_id is None:
        raise RuntimeError("tool_results.get requires an authenticated Telegram user context")

    record = get_tool_result_store().get(ref, user_id=ctx.user_id)
    if record is None:
        return {
            "ok": False,
            "error": f"Unknown ref: {ref}",
        }

    if mode == "summary":
        return {
            "ok": True,
            "ref": record.display_ref,
            "tool_name": record.tool_name,
            "summary": record.summary,
            "reliability_warning": SUMMARY_RELIABILITY_WARNING,
        }

    try:
        payload = json.loads(record.payload_json)
    except json.JSONDecodeError:
        payload = record.payload_json

    return {
        "ok": True,
        "ref": record.display_ref,
        "tool_name": record.tool_name,
        "created_at": record.created_at.isoformat(),
        "result": payload,
    }


TOOL_RESULTS_GET = ToolSpec(
    name="tool_results.get",
    description=(
        "Retrieve a previously archived tool result by ref. Use when you need exact data "
        "(quotes, IDs, counts, full JSON) — summaries in collapsed tool messages are "
        "approximate only. mode=full returns the stored payload; mode=summary returns "
        "the short summary."
    ),
    parameters={
        "type": "object",
        "properties": {
            "ref": {
                "type": "integer",
                "description": (
                    "Numeric ref from a collapsed archived tool result "
                    "(shown as ref in the archived stub)."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["full", "summary"],
                "default": "full",
                "description": "full = stored payload; summary = short summary only.",
            },
        },
        "required": ["ref"],
    },
    handler=_tool_results_get_handler,
    tags=("agent", "archive", "memory", "tool_results"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=True,
    examples=(
        "retrieve full archived tool result by ref",
        "get exact stored search results",
    ),
)
