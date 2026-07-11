from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn

from memory.verification.json_schema import SCOPE_ERROR_CODES
from memory.verification.schemas import (
    VERIFICATION_SCHEMA_VERSION,
    EvidenceDirectness,
    ParsedVerdict,
    VerificationVerdict,
)


class VerificationParseError(ValueError):
    pass


_FIELDS = {
    "schema_version",
    "verdict",
    "evidence_directness",
    "scope_errors",
    "ambiguities",
    "missing_context",
    "corrected_candidate",
}


def parse_verification_output(raw: str | Mapping[str, Any]) -> ParsedVerdict:
    data = _loads_strict(raw) if isinstance(raw, str) else dict(raw)
    missing = _FIELDS - set(data)
    unknown = set(data) - _FIELDS
    if missing:
        _fail("$", f"missing fields: {sorted(missing)}")
    if unknown:
        _fail("$", f"unknown fields: {sorted(unknown)}")
    if data["schema_version"] != VERIFICATION_SCHEMA_VERSION:
        _fail("$.schema_version", "unsupported version")
    try:
        verdict = VerificationVerdict(_text(data["verdict"], "$.verdict"))
    except ValueError as exc:
        raise VerificationParseError("$.verdict: unsupported verdict") from exc
    directness_raw = data["evidence_directness"]
    directness: EvidenceDirectness | None = None
    if directness_raw is not None:
        try:
            directness = EvidenceDirectness(
                _text(directness_raw, "$.evidence_directness")
            )
        except ValueError as exc:
            raise VerificationParseError(
                "$.evidence_directness: unsupported value"
            ) from exc
    if verdict is VerificationVerdict.SUPPORTED and directness is None:
        _fail("$.evidence_directness", "supported verdict requires directness")
    scope_errors = _text_array(data["scope_errors"], "$.scope_errors", maximum=9)
    unknown_scope = set(scope_errors) - set(SCOPE_ERROR_CODES)
    if unknown_scope:
        _fail("$.scope_errors", f"unknown codes: {sorted(unknown_scope)}")
    ambiguities = _text_array(data["ambiguities"], "$.ambiguities", maximum=8)
    missing_context = _text_array(
        data["missing_context"], "$.missing_context", maximum=8
    )
    if data["corrected_candidate"] is not None:
        _fail("$.corrected_candidate", "v1 requires null")
    return ParsedVerdict(
        schema_version=VERIFICATION_SCHEMA_VERSION,
        verdict=verdict,
        evidence_directness=directness,
        scope_errors=scope_errors,
        ambiguities=ambiguities,
        missing_context=missing_context,
    )


def _loads_strict(raw: str) -> dict[str, Any]:
    def pairs(values: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise VerificationParseError(f"duplicate JSON key: {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=_bad_constant)
    except json.JSONDecodeError as exc:
        raise VerificationParseError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(value, Mapping):
        _fail("$", "root must be an object")
    return dict(value)


def _bad_constant(value: str) -> NoReturn:
    raise VerificationParseError(f"non-finite JSON number: {value}")


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be a non-empty string")
    if len(value) > 500:
        _fail(path, "must be at most 500 characters")
    return value


def _text_array(value: Any, path: str, *, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    if len(value) > maximum:
        _fail(path, f"must contain at most {maximum} items")
    return tuple(_text(item, f"{path}[{index}]") for index, item in enumerate(value))


def _fail(path: str, message: str) -> NoReturn:
    raise VerificationParseError(f"{path}: {message}")
