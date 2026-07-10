"""Shared helpers for parsing JSON verdict payloads from meta-review LLMs.

The trajectory coach, tool checker, and checker arbiter all ask their model for a
single JSON object and previously each kept a private copy of these three helpers.
Keeping one implementation avoids the copies drifting apart.
"""

from __future__ import annotations

import re
from typing import Any

_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*")
_FENCE_CLOSE_RE = re.compile(r"\s*```$")
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _FENCE_OPEN_RE.sub("", stripped)
        stripped = _FENCE_CLOSE_RE.sub("", stripped)
    return stripped.strip()


def extract_json_payload(text: str) -> str:
    candidates: list[str] = []
    fenced = strip_json_fence(text)
    if fenced:
        candidates.append(fenced)
    match = _OBJECT_RE.search(text)
    if match:
        blob = match.group(0).strip()
        if blob not in candidates:
            candidates.append(blob)
    for candidate in candidates:
        if candidate.startswith("{"):
            return candidate
    return candidates[0] if candidates else ""


def as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
