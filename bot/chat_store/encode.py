from __future__ import annotations

import json
from typing import Any

from bot.chat_store.models import ChatMessage, ContentType


def infer_content_type(message: dict[str, Any]) -> ContentType:
    role = message.get("role")
    if role == "tool":
        return "tool_result"
    if role == "assistant" and message.get("tool_calls"):
        return "tool_calls"
    if role == "user" and "[image]" in str(message.get("content") or ""):
        return "image_placeholder"
    return "text"


def normalize_content(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    if content is None:
        return None
    if isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def extract_tool_name(message: dict[str, Any]) -> str | None:
    if message.get("role") != "tool":
        return None
    content = message.get("content")
    if not isinstance(content, str):
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    tool_name = payload.get("tool_name")
    return str(tool_name) if tool_name else None


def build_metadata(
    message: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    tool_calls = message.get("tool_calls")
    if tool_calls:
        metadata["tool_calls"] = tool_calls
    if extra:
        metadata.update(extra)
    return metadata


def message_to_row_fields(
    message: dict[str, Any],
    *,
    metadata_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = build_metadata(message, metadata_extra)
    return {
        "role": str(message.get("role") or ""),
        "content": normalize_content(message),
        "content_type": infer_content_type(message),
        "tool_call_id": message.get("tool_call_id"),
        "tool_name": extract_tool_name(message),
        "metadata_json": json.dumps(metadata, ensure_ascii=False) if metadata else None,
    }


def row_to_message_dict(row: ChatMessage) -> dict[str, Any]:
    result: dict[str, Any] = {"role": row.role}
    if row.content is not None:
        if row.content_type == "text" and row.content.startswith("[") and row.role == "user":
            try:
                parsed = json.loads(row.content)
                if isinstance(parsed, list):
                    result["content"] = parsed
                else:
                    result["content"] = row.content
            except json.JSONDecodeError:
                result["content"] = row.content
        else:
            result["content"] = row.content
    elif row.content_type != "tool_calls":
        result["content"] = ""

    if row.tool_call_id:
        result["tool_call_id"] = row.tool_call_id

    tool_calls = row.metadata.get("tool_calls")
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result
