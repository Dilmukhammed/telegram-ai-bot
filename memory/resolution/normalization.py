from __future__ import annotations

import re
import unicodedata
from typing import Any


_WHITESPACE = re.compile(r"\s+")


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def collapse_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def display_label(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return collapse_whitespace(nfkc(str(value)))


def lookup_key(value: Any) -> str:
    """Case-folded lookup key; preserves typed scalars via display then fold."""
    label = display_label(value)
    return label.casefold()


def typed_literal_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"type": "int", "value": value}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if value is None:
        return {"type": "null", "value": None}
    return {"type": "string", "value": display_label(value)}
