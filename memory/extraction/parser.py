from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn, TypeVar

from memory.extraction.enrich import enrich_extraction_payload, is_slim_extraction_payload
from memory.extraction.schemas import (
    EXTRACTION_SCHEMA_VERSION,
    CandidateArgument,
    CandidateDraft,
    CandidateKind,
    CandidateStatus,
    Epistemic,
    EpistemicMode,
    EpistemicScope,
    EvidenceSpan,
    ExtractionResult,
    MentionDraft,
    MentionType,
    Polarity,
    SpeakerCommitment,
    Temporal,
)


class ExtractionParseError(ValueError):
    """The model returned malformed or evidence-inconsistent extraction JSON."""


_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_T = TypeVar("_T")


def _fail(path: str, message: str) -> NoReturn:
    raise ExtractionParseError(f"{path}: {message}")


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return dict(value)


def _strict(value: Any, path: str, required: set[str], optional: set[str] | None = None) -> dict[str, Any]:
    data = _object(value, path)
    optional = optional or set()
    missing = required - set(data)
    unknown = set(data) - required - optional
    if missing:
        _fail(path, f"missing fields: {sorted(missing)}")
    if unknown:
        _fail(path, f"unknown fields: {sorted(unknown)}")
    return data


def _text(value: Any, path: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        _fail(path, "must be a string")
    if nonempty and not value.strip():
        _fail(path, "must be non-empty")
    return value


def _name(value: Any, path: str) -> str:
    result = _text(value, path)
    if _NAME.fullmatch(result) is None:
        _fail(path, "must be a lowercase snake_case identifier")
    return result


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(path, "must be a non-negative integer")
    return value


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail(path, "must be a boolean")
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    return value


def _enum(enum_type: type[_T], value: Any, path: str) -> _T:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = sorted(str(item.value) for item in enum_type)  # type: ignore[attr-defined]
        raise ExtractionParseError(f"{path}: expected one of {allowed}") from exc


def _json_value(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(path, "must be finite")
        return value
    if isinstance(value, list):
        return [_json_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Mapping):
        return {
            _text(key, f"{path}.<key>"): _json_value(item, f"{path}.{key}")
            for key, item in value.items()
        }
    _fail(path, "must be JSON-compatible")


def _loads_strict(raw: str) -> Mapping[str, Any]:
    def pairs(values: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ExtractionParseError(f"duplicate JSON key: {key!r}")
            result[key] = value
        return result

    def constant(value: str) -> NoReturn:
        raise ExtractionParseError(f"non-finite JSON number: {value}")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as exc:
        raise ExtractionParseError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(value, Mapping):
        raise ExtractionParseError("$: root must be an object")
    return value


def parse_extraction_output(
    raw: str | Mapping[str, Any],
    *,
    segment_text: str,
    allow_candidates: bool = True,
    timezone: str | None = None,
) -> ExtractionResult:
    payload = _loads_strict(raw) if isinstance(raw, str) else dict(raw)
    if is_slim_extraction_payload(payload):
        try:
            payload = enrich_extraction_payload(
                payload,
                segment_text=segment_text,
                timezone=timezone,
            )
        except ValueError as exc:
            raise ExtractionParseError(str(exc)) from exc
    data = _strict(
        payload,
        "$",
        {"schema_version", "abstain", "mentions", "candidates"},
    )
    version = _text(data["schema_version"], "$.schema_version")
    if version != EXTRACTION_SCHEMA_VERSION:
        _fail("$.schema_version", f"unsupported version {version!r}")
    abstain = _boolean(data["abstain"], "$.abstain")

    mentions = tuple(
        _parse_mention(value, f"$.mentions[{index}]", segment_text)
        for index, value in enumerate(_array(data["mentions"], "$.mentions"))
    )
    mention_refs = [item.mention_ref for item in mentions]
    if len(set(mention_refs)) != len(mention_refs):
        _fail("$.mentions", "mention_ref values must be unique")

    candidates = tuple(
        _parse_candidate(
            value,
            f"$.candidates[{index}]",
            segment_text=segment_text,
            mention_refs=frozenset(mention_refs),
        )
        for index, value in enumerate(_array(data["candidates"], "$.candidates"))
    )
    candidate_refs = [item.candidate_ref for item in candidates]
    if len(set(candidate_refs)) != len(candidate_refs):
        _fail("$.candidates", "candidate_ref values must be unique")
    if abstain and candidates:
        _fail("$", "abstain=true requires an empty candidates array")
    if not abstain and not candidates:
        _fail("$", "an empty candidates array requires abstain=true")
    if not allow_candidates and candidates:
        _fail("$.candidates", "candidates are forbidden for this source authority")
    if _contains_canonical_entity_id(payload):
        _fail("$", "canonical entity IDs are forbidden during extraction")
    return ExtractionResult(
        schema_version=version,
        abstain=abstain,
        mentions=mentions,
        candidates=candidates,
    )


def _parse_mention(value: Any, path: str, segment_text: str) -> MentionDraft:
    data = _strict(
        value,
        path,
        {"mention_ref", "mention_type", "surface_text", "char_start", "char_end", "normalized_hint"},
    )
    start = _integer(data["char_start"], f"{path}.char_start")
    end = _integer(data["char_end"], f"{path}.char_end")
    surface = _text(data["surface_text"], f"{path}.surface_text")
    _validate_span(segment_text, start, end, surface, path)
    hint_raw = data["normalized_hint"]
    hint = None if hint_raw is None else _text(hint_raw, f"{path}.normalized_hint")
    return MentionDraft(
        mention_ref=_name(data["mention_ref"], f"{path}.mention_ref"),
        mention_type=_enum(MentionType, data["mention_type"], f"{path}.mention_type"),
        surface_text=surface,
        char_start=start,
        char_end=end,
        normalized_hint=hint,
    )


def _parse_candidate(
    value: Any,
    path: str,
    *,
    segment_text: str,
    mention_refs: frozenset[str],
) -> CandidateDraft:
    data = _strict(
        value,
        path,
        {
            "candidate_ref", "kind", "schema_name", "schema_version", "arguments",
            "attributes", "polarity", "epistemic", "temporal", "status", "evidence",
            "canonical_hint",
        },
    )
    arguments = tuple(
        _parse_argument(item, f"{path}.arguments[{index}]", mention_refs)
        for index, item in enumerate(_array(data["arguments"], f"{path}.arguments"))
    )
    if not arguments:
        _fail(f"{path}.arguments", "must contain at least one argument")
    attributes = _object(data["attributes"], f"{path}.attributes")
    attributes = {str(k): _json_value(v, f"{path}.attributes.{k}") for k, v in attributes.items()}
    epistemic = _parse_epistemic(data["epistemic"], f"{path}.epistemic", mention_refs)
    polarity = _enum(Polarity, data["polarity"], f"{path}.polarity")
    status = _enum(CandidateStatus, data["status"], f"{path}.status")
    if (
        epistemic.speaker_commitment in {SpeakerCommitment.UNCERTAIN, SpeakerCommitment.UNKNOWN}
        or epistemic.needs_confirmation
        or status in {CandidateStatus.NEEDS_CONFIRMATION, CandidateStatus.INSUFFICIENT}
    ) and polarity is not Polarity.UNKNOWN:
        _fail(path, "unresolved uncertainty must use polarity=unknown")
    evidence = tuple(
        _parse_evidence(item, f"{path}.evidence[{index}]", segment_text)
        for index, item in enumerate(_array(data["evidence"], f"{path}.evidence"))
    )
    if not evidence:
        _fail(f"{path}.evidence", "must contain at least one exact evidence span")
    temporal = (
        None
        if data["temporal"] is None
        else _parse_temporal(data["temporal"], f"{path}.temporal")
    )
    hint_raw = data["canonical_hint"]
    hint = None if hint_raw is None else _text(hint_raw, f"{path}.canonical_hint")
    schema_version = _text(data["schema_version"], f"{path}.schema_version")
    if schema_version != "1":
        _fail(f"{path}.schema_version", "only proposition schema version '1' is supported")
    return CandidateDraft(
        candidate_ref=_name(data["candidate_ref"], f"{path}.candidate_ref"),
        kind=_enum(CandidateKind, data["kind"], f"{path}.kind"),
        schema_name=_name(data["schema_name"], f"{path}.schema_name"),
        schema_version=schema_version,
        arguments=arguments,
        attributes=attributes,
        polarity=polarity,
        epistemic=epistemic,
        temporal=temporal,
        status=status,
        evidence=evidence,
        canonical_hint=hint,
    )


def _parse_argument(value: Any, path: str, mention_refs: frozenset[str]) -> CandidateArgument:
    data = _strict(value, path, {"role"}, {"mention_ref", "literal"})
    has_mention = "mention_ref" in data
    has_literal = "literal" in data
    if has_mention == has_literal:
        _fail(path, "exactly one of mention_ref or literal is required")
    role = _name(data["role"], f"{path}.role")
    if has_mention:
        mention_ref = _name(data["mention_ref"], f"{path}.mention_ref")
        if mention_ref not in mention_refs:
            _fail(f"{path}.mention_ref", "references an undeclared mention")
        return CandidateArgument(role=role, mention_ref=mention_ref)
    return CandidateArgument(
        role=role,
        literal=_json_value(data["literal"], f"{path}.literal"),
        has_literal=True,
    )


def _parse_epistemic(value: Any, path: str, mention_refs: frozenset[str]) -> Epistemic:
    data = _strict(
        value,
        path,
        {"mode", "speaker_commitment", "scope", "alternatives", "needs_confirmation", "speaker_ref"},
    )
    speaker_raw = data["speaker_ref"]
    speaker_ref = None if speaker_raw is None else _text(speaker_raw, f"{path}.speaker_ref")
    if speaker_ref not in (None, "self") and speaker_ref not in mention_refs:
        _fail(f"{path}.speaker_ref", "references an undeclared mention")
    alternatives = tuple(
        _json_value(item, f"{path}.alternatives[{index}]")
        for index, item in enumerate(_array(data["alternatives"], f"{path}.alternatives"))
    )
    return Epistemic(
        mode=_enum(EpistemicMode, data["mode"], f"{path}.mode"),
        speaker_commitment=_enum(
            SpeakerCommitment,
            data["speaker_commitment"],
            f"{path}.speaker_commitment",
        ),
        scope=_enum(EpistemicScope, data["scope"], f"{path}.scope"),
        alternatives=alternatives,
        needs_confirmation=_boolean(data["needs_confirmation"], f"{path}.needs_confirmation"),
        speaker_ref=speaker_ref,
    )


def _parse_temporal(value: Any, path: str) -> Temporal:
    data = _strict(
        value,
        path,
        {"original_text", "valid_from", "valid_to", "event_time", "precision", "timezone"},
    )
    optional_text: dict[str, str | None] = {}
    for field in ("original_text", "valid_from", "valid_to", "event_time", "timezone"):
        raw = data[field]
        optional_text[field] = None if raw is None else _text(raw, f"{path}.{field}")
    return Temporal(
        original_text=optional_text["original_text"],
        valid_from=optional_text["valid_from"],
        valid_to=optional_text["valid_to"],
        event_time=optional_text["event_time"],
        precision=_name(data["precision"], f"{path}.precision"),
        timezone=optional_text["timezone"],
    )


def _parse_evidence(value: Any, path: str, segment_text: str) -> EvidenceSpan:
    data = _strict(value, path, {"relation", "exact_quote", "char_start", "char_end"})
    start = _integer(data["char_start"], f"{path}.char_start")
    end = _integer(data["char_end"], f"{path}.char_end")
    quote = _text(data["exact_quote"], f"{path}.exact_quote")
    _validate_span(segment_text, start, end, quote, path)
    return EvidenceSpan(
        relation=_name(data["relation"], f"{path}.relation"),
        exact_quote=quote,
        char_start=start,
        char_end=end,
    )


def _validate_span(text: str, start: int, end: int, expected: str, path: str) -> None:
    if end < start or end > len(text):
        _fail(path, f"invalid span [{start}, {end}) for text length {len(text)}")
    if text[start:end] != expected:
        _fail(path, "span does not exactly match the supplied text")


def _contains_canonical_entity_id(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in {"entity_id", "canonical_entity_id", "canonical_id"}:
                return True
            if _contains_canonical_entity_id(item):
                return True
    elif isinstance(value, list):
        return any(_contains_canonical_entity_id(item) for item in value)
    return False
