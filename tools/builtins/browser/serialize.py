from __future__ import annotations

import re
from typing import Any

_DEBUG_URL_RE = re.compile(
    r"https?://[^\s\"']*(?:steel\.dev|session-viewer|debug)[^\s\"']*",
    re.IGNORECASE,
)
_WS_URL_RE = re.compile(r"wss?://[^\s\"']+", re.IGNORECASE)
_API_KEY_RE = re.compile(r"(api[_-]?key|steel[_-]?api[_-]?key)\s*[:=]\s*[^\s\"']+", re.IGNORECASE)


def redact_secrets(value: str) -> str:
    text = _DEBUG_URL_RE.sub("[redacted_debug_url]", value)
    text = _WS_URL_RE.sub("[redacted_ws_url]", text)
    text = _API_KEY_RE.sub(r"\1=[redacted]", text)
    return text


def redact_browser_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        return redact_secrets(payload)
    if isinstance(payload, list):
        return [redact_browser_payload(item) for item in payload]
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered in {
                "debug_url",
                "debugurl",
                "websocket_url",
                "websocketurl",
                "session_viewer_url",
                "sessionviewerurl",
                "api_key",
                "apikey",
            }:
                out[key] = "[redacted]"
            else:
                out[key] = redact_browser_payload(value)
        return out
    return payload


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True
