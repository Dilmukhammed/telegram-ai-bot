from __future__ import annotations

import json
from typing import Any

from tools.tool_results.store import StoredToolResult

ARCHIVED_FLAG = "archived"
RECALL_TOOL_NAME = "tool_results.get"


def is_archived_tool_content(content: str) -> bool:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(payload, dict) and payload.get(ARCHIVED_FLAG) is True


def should_archive_tool_content(content: str, *, min_chars: int) -> bool:
    if len(content) <= min_chars:
        return False
    if is_archived_tool_content(content):
        return False
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return len(content) > min_chars
    if not isinstance(payload, dict):
        return len(content) > min_chars
    tool_name = str(payload.get("tool_name") or "")
    if tool_name == RECALL_TOOL_NAME:
        return False
    return True


def parse_tool_results_get_display_ref(
    content: str,
    *,
    tool_name: str | None = None,
) -> int | None:
    """Display ref from a full tool_results.get response, if any."""
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    name = tool_name or payload.get("tool_name")
    if name != RECALL_TOOL_NAME:
        return None
    if not payload.get("ok", True):
        return None
    inner = payload.get("result")
    if not isinstance(inner, dict) or not inner.get("ok"):
        return None
    if "result" not in inner:
        return None
    ref = inner.get("ref")
    if isinstance(ref, bool):
        return None
    if isinstance(ref, int):
        return ref
    text = str(ref).strip()
    if text.isdigit():
        return int(text)
    return None


def should_collapse_tool_results_get(content: str, *, min_chars: int, tool_name: str | None = None) -> bool:
    if len(content) <= min_chars:
        return False
    return parse_tool_results_get_display_ref(content, tool_name=tool_name) is not None


def extract_tool_meta(content: str) -> tuple[str | None, bool, bool, str | None]:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None, True, False, None
    if not isinstance(payload, dict):
        return None, True, False, None
    tool_name = payload.get("tool_name")
    return (
        str(tool_name) if tool_name else None,
        bool(payload.get("ok", True)),
        bool(payload.get("cached", False)),
        json.dumps(payload.get("arguments") or {}, ensure_ascii=False, sort_keys=True)
        if payload.get("arguments") is not None
        else None,
    )


def build_archived_tool_content(record: StoredToolResult) -> dict[str, Any]:
    return {
        ARCHIVED_FLAG: True,
        "ref": record.display_ref,
        "tool_name": record.tool_name,
        "ok": record.ok,
        "summary": record.summary,
    }


def archived_content_json(record: StoredToolResult) -> str:
    return json.dumps(build_archived_tool_content(record), ensure_ascii=False)
