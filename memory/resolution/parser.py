from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NoReturn


class ResolutionParseError(ValueError):
    pass


_FIELDS = {
    "schema_version",
    "verdict",
    "scope_errors",
    "ambiguities",
    "missing_context",
    "corrected_resolution",
}
_VERDICTS = frozenset({"supported", "contradicted", "insufficient", "malformed"})


@dataclass(frozen=True, slots=True)
class ParsedLinkVerdict:
    schema_version: str
    verdict: str
    scope_errors: tuple[str, ...]
    ambiguities: tuple[str, ...]
    missing_context: tuple[str, ...]


def parse_link_verdict(raw: str | Mapping[str, Any]) -> ParsedLinkVerdict:
    data = _loads_strict(raw) if isinstance(raw, str) else dict(raw)
    missing = _FIELDS - set(data)
    unknown = set(data) - _FIELDS
    if missing:
        _fail("$", f"missing fields: {sorted(missing)}")
    if unknown:
        _fail("$", f"unknown fields: {sorted(unknown)}")
    if data["schema_version"] != "1":
        _fail("$.schema_version", "unsupported version")
    verdict = _text(data["verdict"], "$.verdict")
    if verdict not in _VERDICTS:
        _fail("$.verdict", "unsupported verdict")
    if data["corrected_resolution"] is not None:
        _fail("$.corrected_resolution", "must be null")
    return ParsedLinkVerdict(
        schema_version="1",
        verdict=verdict,
        scope_errors=_text_array(data["scope_errors"], "$.scope_errors", maximum=9),
        ambiguities=_text_array(data["ambiguities"], "$.ambiguities", maximum=8),
        missing_context=_text_array(
            data["missing_context"], "$.missing_context", maximum=8
        ),
    )


def _loads_strict(raw: str) -> dict[str, Any]:
    def pairs(values: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ResolutionParseError(f"duplicate key: {key!r}")
            result[key] = value
        return result

    try:
        parsed = json.loads(raw, object_pairs_hook=pairs)
    except json.JSONDecodeError as exc:
        raise ResolutionParseError(f"invalid json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ResolutionParseError("root must be object")
    return parsed


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be non-empty string")
    return value


def _text_array(value: Any, path: str, *, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        _fail(path, "must be array")
    if len(value) > maximum:
        _fail(path, f"too many items (max {maximum})")
    return tuple(_text(item, f"{path}[{index}]") for index, item in enumerate(value))


def _fail(path: str, message: str) -> NoReturn:
    raise ResolutionParseError(f"{path}: {message}")
