from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, NoReturn, Sequence, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memory.eval.schemas import (
    CandidateArgument,
    CandidateKind,
    ChatMessageEvent,
    ChatRole,
    CoverageRequirements,
    Criticality,
    Epistemic,
    EpistemicMode,
    EpistemicScope,
    EventKind,
    EvidenceSpan,
    Expected,
    ExpectedSegment,
    ExpectedSource,
    Fixture,
    FixturePack,
    FixtureUser,
    ForbiddenArgument,
    ForbiddenCandidate,
    ForbiddenSegment,
    ForbiddenSource,
    GoldCandidate,
    GoldMention,
    Language,
    PackManifest,
    PayloadKind,
    Polarity,
    Review,
    ReviewStatus,
    SpeakerCommitment,
    SpanPointer,
    Temporal,
    Tier,
    ToolResultEvent,
)


SCHEMA_VERSION = "1"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_ENTITY_KEYS = {
    "canonical_entity_id",
    "canonical_entity_ids",
    "entity_id",
    "entity_ids",
}
_T = TypeVar("_T", bound=Enum)
_MISSING = object()


class FixtureValidationError(ValueError):
    """A fixture or pack failed strict structural or semantic validation."""


def _fail(path: str, message: str) -> NoReturn:
    raise FixtureValidationError(f"{path}: {message}")


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, "must be an object")
    return value


def _strict(
    value: Any,
    path: str,
    *,
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> dict[str, Any]:
    obj = _object(value, path)
    required_set = set(required)
    allowed = required_set | set(optional)
    unknown = set(obj) - allowed
    missing = required_set - set(obj)
    if unknown:
        _fail(path, f"unknown fields: {sorted(unknown)}")
    if missing:
        _fail(path, f"missing fields: {sorted(missing)}")
    return obj


def _string(value: Any, path: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        _fail(path, "must be a string")
    if nonempty and not value.strip():
        _fail(path, "must be non-empty")
    return value


def _name(value: Any, path: str) -> str:
    result = _string(value, path)
    if not _NAME_RE.fullmatch(result):
        _fail(path, "must contain only letters, digits, dot, underscore, or hyphen")
    return result


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(path, "must be an integer")
    if value < minimum:
        _fail(path, f"must be at least {minimum}")
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
    raw = _string(value, path)
    try:
        return enum_type(raw)
    except ValueError:
        _fail(path, f"unknown value {raw!r}")


def _datetime(value: Any, path: str) -> datetime:
    raw = _string(value, path)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        _fail(path, "must be an ISO-8601 datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(path, "must include a UTC offset")
    return parsed


def _json_value(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(path, "must not contain NaN or infinity")
        return value
    if isinstance(value, list):
        return [_json_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(path, "object keys must be strings")
            result[key] = _json_value(item, f"{path}.{key}")
        return result
    _fail(path, f"contains unsupported JSON type {type(value).__name__}")


def _string_tuple(value: Any, path: str, *, nonempty: bool = False) -> tuple[str, ...]:
    result = tuple(
        _string(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path))
    )
    if nonempty and not result:
        _fail(path, "must contain at least one item")
    if len(result) != len(set(result)):
        _fail(path, "must not contain duplicates")
    return result


def _name_tuple(value: Any, path: str, *, nonempty: bool = False) -> tuple[str, ...]:
    result = tuple(
        _name(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path))
    )
    if nonempty and not result:
        _fail(path, "must contain at least one item")
    if len(result) != len(set(result)):
        _fail(path, "must not contain duplicates")
    return result


def _pointer(value: Any, path: str) -> SpanPointer:
    obj = _strict(
        value,
        path,
        required={"source_event"},
        optional={"char_start", "char_end"},
    )
    has_start = "char_start" in obj
    has_end = "char_end" in obj
    if has_start != has_end:
        _fail(path, "char_start and char_end must be provided together")
    start = _integer(obj["char_start"], f"{path}.char_start") if has_start else None
    end = _integer(obj["char_end"], f"{path}.char_end") if has_end else None
    if start is not None and end is not None and end <= start:
        _fail(path, "char_end must be greater than char_start")
    return SpanPointer(
        source_event=_name(obj["source_event"], f"{path}.source_event"),
        char_start=start,
        char_end=end,
    )


def _user(value: Any, path: str) -> FixtureUser:
    obj = _strict(
        value,
        path,
        required={"user_alias", "user_id"},
        optional={"display_name", "metadata"},
    )
    display_name = obj.get("display_name")
    if display_name is not None:
        display_name = _string(display_name, f"{path}.display_name")
    metadata = _json_value(obj.get("metadata", {}), f"{path}.metadata")
    return FixtureUser(
        user_alias=_name(obj["user_alias"], f"{path}.user_alias"),
        user_id=_integer(obj["user_id"], f"{path}.user_id", minimum=1),
        display_name=display_name,
        metadata=metadata,
    )


def _event(value: Any, path: str) -> ChatMessageEvent | ToolResultEvent:
    obj = _object(value, path)
    kind = _enum(EventKind, obj.get("kind"), f"{path}.kind")
    common = {"event_id", "kind", "user_alias", "occurred_at"}
    if kind is EventKind.CHAT_MESSAGE:
        obj = _strict(
            obj,
            path,
            required=common | {"role", "content", "content_type", "metadata"},
        )
        return ChatMessageEvent(
            event_id=_name(obj["event_id"], f"{path}.event_id"),
            kind=kind,
            user_alias=_name(obj["user_alias"], f"{path}.user_alias"),
            role=_enum(ChatRole, obj["role"], f"{path}.role"),
            content=_string(obj["content"], f"{path}.content", nonempty=False),
            content_type=_name(obj["content_type"], f"{path}.content_type"),
            occurred_at=_datetime(obj["occurred_at"], f"{path}.occurred_at"),
            metadata=_json_value(obj["metadata"], f"{path}.metadata"),
        )
    obj = _strict(
        obj,
        path,
        required=common
        | {"tool_name", "payload_kind", "payload_json", "ok", "cached"},
    )
    payload = _string(obj["payload_json"], f"{path}.payload_json", nonempty=False)
    try:
        _json_value(json.loads(payload), f"{path}.payload_json")
    except json.JSONDecodeError:
        _fail(f"{path}.payload_json", "must encode valid JSON")
    return ToolResultEvent(
        event_id=_name(obj["event_id"], f"{path}.event_id"),
        kind=kind,
        user_alias=_name(obj["user_alias"], f"{path}.user_alias"),
        tool_name=_name(obj["tool_name"], f"{path}.tool_name"),
        payload_kind=_enum(PayloadKind, obj["payload_kind"], f"{path}.payload_kind"),
        payload_json=payload,
        ok=_boolean(obj["ok"], f"{path}.ok"),
        cached=_boolean(obj["cached"], f"{path}.cached"),
        occurred_at=_datetime(obj["occurred_at"], f"{path}.occurred_at"),
    )


def _expected_source(value: Any, path: str) -> ExpectedSource:
    obj = _strict(
        value,
        path,
        required={
            "source_event",
            "source_type",
            "source_ref_alias",
            "authority_class",
            "content_hash_rule",
            "source_version_count",
        },
        optional={"pointer", "normalization_job_status"},
    )
    pointer = obj.get("pointer")
    status = obj.get("normalization_job_status")
    return ExpectedSource(
        source_event=_name(obj["source_event"], f"{path}.source_event"),
        source_type=_name(obj["source_type"], f"{path}.source_type"),
        source_ref_alias=_name(obj["source_ref_alias"], f"{path}.source_ref_alias"),
        authority_class=_name(obj["authority_class"], f"{path}.authority_class"),
        content_hash_rule=_name(obj["content_hash_rule"], f"{path}.content_hash_rule"),
        source_version_count=_integer(
            obj["source_version_count"], f"{path}.source_version_count", minimum=1
        ),
        pointer=None if pointer is None else _pointer(pointer, f"{path}.pointer"),
        normalization_job_status=(
            None if status is None else _name(status, f"{path}.normalization_job_status")
        ),
    )


def _expected_segment(value: Any, path: str) -> ExpectedSegment:
    obj = _strict(
        value,
        path,
        required={
            "source_event",
            "segment_type",
            "ordinal",
            "text",
            "normalizer_version",
            "pointer",
        },
    )
    return ExpectedSegment(
        source_event=_name(obj["source_event"], f"{path}.source_event"),
        segment_type=_name(obj["segment_type"], f"{path}.segment_type"),
        ordinal=_integer(obj["ordinal"], f"{path}.ordinal"),
        text=_string(obj["text"], f"{path}.text", nonempty=False),
        normalizer_version=_name(
            obj["normalizer_version"], f"{path}.normalizer_version"
        ),
        pointer=_pointer(obj["pointer"], f"{path}.pointer"),
    )


def _mention(value: Any, path: str) -> GoldMention:
    obj = _strict(
        value,
        path,
        required={
            "mention_id",
            "source_event",
            "mention_type",
            "surface_text",
            "char_start",
            "char_end",
            "normalized_hint",
            "pointer",
        },
    )
    start = _integer(obj["char_start"], f"{path}.char_start")
    end = _integer(obj["char_end"], f"{path}.char_end")
    if end <= start:
        _fail(path, "char_end must be greater than char_start")
    hint = obj["normalized_hint"]
    if hint is not None:
        hint = _string(hint, f"{path}.normalized_hint")
    return GoldMention(
        mention_id=_name(obj["mention_id"], f"{path}.mention_id"),
        source_event=_name(obj["source_event"], f"{path}.source_event"),
        mention_type=_name(obj["mention_type"], f"{path}.mention_type"),
        surface_text=_string(obj["surface_text"], f"{path}.surface_text"),
        char_start=start,
        char_end=end,
        normalized_hint=hint,
        pointer=_pointer(obj["pointer"], f"{path}.pointer"),
    )


def _argument(value: Any, path: str) -> CandidateArgument:
    obj = _strict(value, path, required={"role"}, optional={"mention_ref", "literal"})
    has_mention = "mention_ref" in obj
    has_literal = "literal" in obj
    if has_mention == has_literal:
        _fail(path, "must contain exactly one of mention_ref or literal")
    return CandidateArgument(
        role=_name(obj["role"], f"{path}.role"),
        mention_ref=(
            _name(obj["mention_ref"], f"{path}.mention_ref") if has_mention else None
        ),
        literal=_json_value(obj.get("literal"), f"{path}.literal"),
        has_literal=has_literal,
    )


def _epistemic(value: Any, path: str) -> Epistemic:
    obj = _strict(
        value,
        path,
        required={
            "mode",
            "speaker_commitment",
            "scope",
            "alternatives",
            "needs_confirmation",
        },
        optional={"speaker_ref"},
    )
    alternatives = tuple(
        _json_value(item, f"{path}.alternatives[{index}]")
        for index, item in enumerate(_array(obj["alternatives"], f"{path}.alternatives"))
    )
    return Epistemic(
        mode=_enum(EpistemicMode, obj["mode"], f"{path}.mode"),
        speaker_commitment=_enum(
            SpeakerCommitment,
            obj["speaker_commitment"],
            f"{path}.speaker_commitment",
        ),
        scope=_enum(EpistemicScope, obj["scope"], f"{path}.scope"),
        alternatives=alternatives,
        needs_confirmation=_boolean(
            obj["needs_confirmation"], f"{path}.needs_confirmation"
        ),
        speaker_ref=(
            _name(obj["speaker_ref"], f"{path}.speaker_ref")
            if obj.get("speaker_ref") is not None
            else None
        ),
    )


def _evidence(value: Any, path: str) -> EvidenceSpan:
    obj = _strict(
        value,
        path,
        required={
            "source_event",
            "relation",
            "exact_quote",
            "char_start",
            "char_end",
        },
    )
    start = _integer(obj["char_start"], f"{path}.char_start")
    end = _integer(obj["char_end"], f"{path}.char_end")
    if end <= start:
        _fail(path, "char_end must be greater than char_start")
    return EvidenceSpan(
        source_event=_name(obj["source_event"], f"{path}.source_event"),
        relation=_name(obj["relation"], f"{path}.relation"),
        exact_quote=_string(obj["exact_quote"], f"{path}.exact_quote"),
        char_start=start,
        char_end=end,
    )


def _temporal(value: Any, path: str) -> Temporal | None:
    if value is None:
        return None
    obj = _strict(
        value,
        path,
        required={
            "original_text",
            "valid_from",
            "valid_to",
            "event_time",
            "precision",
            "timezone",
        },
    )

    def nullable_string(key: str) -> str | None:
        item = obj[key]
        return None if item is None else _string(item, f"{path}.{key}")

    timezone_name = nullable_string("timezone")
    if timezone_name is not None:
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            _fail(f"{path}.timezone", "must be a valid IANA timezone")
    return Temporal(
        original_text=nullable_string("original_text"),
        valid_from=nullable_string("valid_from"),
        valid_to=nullable_string("valid_to"),
        event_time=nullable_string("event_time"),
        precision=_name(obj["precision"], f"{path}.precision"),
        timezone=timezone_name,
    )


def _candidate(value: Any, path: str) -> GoldCandidate:
    obj = _strict(
        value,
        path,
        required={
            "candidate_ref",
            "kind",
            "schema_name",
            "schema_version",
            "arguments",
            "attributes",
            "polarity",
            "epistemic",
            "temporal",
            "status",
            "evidence",
        },
        optional={"allow_extra_attributes"},
    )
    return GoldCandidate(
        candidate_ref=_name(obj["candidate_ref"], f"{path}.candidate_ref"),
        kind=_enum(CandidateKind, obj["kind"], f"{path}.kind"),
        schema_name=_name(obj["schema_name"], f"{path}.schema_name"),
        schema_version=_name(obj["schema_version"], f"{path}.schema_version"),
        arguments=tuple(
            _argument(item, f"{path}.arguments[{index}]")
            for index, item in enumerate(_array(obj["arguments"], f"{path}.arguments"))
        ),
        attributes=_json_value(obj["attributes"], f"{path}.attributes"),
        polarity=_enum(Polarity, obj["polarity"], f"{path}.polarity"),
        epistemic=_epistemic(obj["epistemic"], f"{path}.epistemic"),
        temporal=_temporal(obj["temporal"], f"{path}.temporal"),
        status=_name(obj["status"], f"{path}.status"),
        evidence=tuple(
            _evidence(item, f"{path}.evidence[{index}]")
            for index, item in enumerate(_array(obj["evidence"], f"{path}.evidence"))
        ),
        allow_extra_attributes=_boolean(
            obj.get("allow_extra_attributes", False),
            f"{path}.allow_extra_attributes",
        ),
    )


def _forbidden_argument(value: Any, path: str) -> ForbiddenArgument:
    obj = _strict(
        value,
        path,
        required={"role"},
        optional={"mention_ref", "surface_text", "literal"},
    )
    choices = [key for key in ("mention_ref", "surface_text", "literal") if key in obj]
    if len(choices) != 1:
        _fail(path, "must contain exactly one reference, surface_text, or literal")
    return ForbiddenArgument(
        role=_name(obj["role"], f"{path}.role"),
        mention_ref=(
            _name(obj["mention_ref"], f"{path}.mention_ref")
            if "mention_ref" in obj
            else None
        ),
        surface_text=(
            _string(obj["surface_text"], f"{path}.surface_text")
            if "surface_text" in obj
            else None
        ),
        literal=_json_value(obj.get("literal"), f"{path}.literal"),
        has_literal="literal" in obj,
    )


def _forbidden_candidate(value: Any, path: str) -> ForbiddenCandidate:
    obj = _strict(
        value,
        path,
        required=set(),
        optional={
            "kind",
            "schema_name",
            "schema_version",
            "polarity",
            "arguments",
            "attributes",
        },
    )
    if not obj:
        _fail(path, "must constrain at least one field")
    return ForbiddenCandidate(
        kind=(
            _enum(CandidateKind, obj["kind"], f"{path}.kind")
            if "kind" in obj
            else None
        ),
        schema_name=(
            _name(obj["schema_name"], f"{path}.schema_name")
            if "schema_name" in obj
            else None
        ),
        schema_version=(
            _name(obj["schema_version"], f"{path}.schema_version")
            if "schema_version" in obj
            else None
        ),
        polarity=(
            _enum(Polarity, obj["polarity"], f"{path}.polarity")
            if "polarity" in obj
            else None
        ),
        arguments=tuple(
            _forbidden_argument(item, f"{path}.arguments[{index}]")
            for index, item in enumerate(_array(obj.get("arguments", []), f"{path}.arguments"))
        ),
        attributes=_json_value(obj.get("attributes", {}), f"{path}.attributes"),
    )


def _forbidden_source(value: Any, path: str) -> ForbiddenSource:
    obj = _strict(
        value,
        path,
        required=set(),
        optional={"source_event", "source_type", "authority_class"},
    )
    if not obj:
        _fail(path, "must constrain at least one field")
    return ForbiddenSource(
        source_event=(
            _name(obj["source_event"], f"{path}.source_event")
            if "source_event" in obj
            else None
        ),
        source_type=(
            _name(obj["source_type"], f"{path}.source_type")
            if "source_type" in obj
            else None
        ),
        authority_class=(
            _name(obj["authority_class"], f"{path}.authority_class")
            if "authority_class" in obj
            else None
        ),
    )


def _forbidden_segment(value: Any, path: str) -> ForbiddenSegment:
    obj = _strict(
        value,
        path,
        required=set(),
        optional={"source_event", "segment_type", "text"},
    )
    if not obj:
        _fail(path, "must constrain at least one field")
    return ForbiddenSegment(
        source_event=(
            _name(obj["source_event"], f"{path}.source_event")
            if "source_event" in obj
            else None
        ),
        segment_type=(
            _name(obj["segment_type"], f"{path}.segment_type")
            if "segment_type" in obj
            else None
        ),
        text=(
            _string(obj["text"], f"{path}.text", nonempty=False)
            if "text" in obj
            else None
        ),
    )


def _expected(value: Any, path: str) -> Expected:
    obj = _strict(
        value,
        path,
        required={"mentions", "candidates", "expect_abstention"},
        optional={
            "sources",
            "segments",
            "forbidden_candidates",
            "forbidden_sources",
            "forbidden_segments",
        },
    )
    return Expected(
        sources=tuple(
            _expected_source(item, f"{path}.sources[{index}]")
            for index, item in enumerate(_array(obj.get("sources", []), f"{path}.sources"))
        ),
        segments=tuple(
            _expected_segment(item, f"{path}.segments[{index}]")
            for index, item in enumerate(_array(obj.get("segments", []), f"{path}.segments"))
        ),
        mentions=tuple(
            _mention(item, f"{path}.mentions[{index}]")
            for index, item in enumerate(_array(obj["mentions"], f"{path}.mentions"))
        ),
        candidates=tuple(
            _candidate(item, f"{path}.candidates[{index}]")
            for index, item in enumerate(_array(obj["candidates"], f"{path}.candidates"))
        ),
        forbidden_candidates=tuple(
            _forbidden_candidate(item, f"{path}.forbidden_candidates[{index}]")
            for index, item in enumerate(
                _array(obj.get("forbidden_candidates", []), f"{path}.forbidden_candidates")
            )
        ),
        forbidden_sources=tuple(
            _forbidden_source(item, f"{path}.forbidden_sources[{index}]")
            for index, item in enumerate(
                _array(obj.get("forbidden_sources", []), f"{path}.forbidden_sources")
            )
        ),
        forbidden_segments=tuple(
            _forbidden_segment(item, f"{path}.forbidden_segments[{index}]")
            for index, item in enumerate(
                _array(obj.get("forbidden_segments", []), f"{path}.forbidden_segments")
            )
        ),
        expect_abstention=_boolean(
            obj["expect_abstention"], f"{path}.expect_abstention"
        ),
    )


def _review(value: Any, path: str) -> Review:
    obj = _strict(
        value,
        path,
        required={"status", "reviewed_by", "reviewed_at", "notes"},
    )
    status = _enum(ReviewStatus, obj["status"], f"{path}.status")
    reviewer = obj["reviewed_by"]
    reviewed_at = obj["reviewed_at"]
    if reviewer is not None:
        reviewer = _string(reviewer, f"{path}.reviewed_by")
    if reviewed_at is not None:
        reviewed_at = _datetime(reviewed_at, f"{path}.reviewed_at")
    if status is ReviewStatus.REVIEWED and (reviewer is None or reviewed_at is None):
        _fail(path, "reviewed fixtures require reviewed_by and reviewed_at")
    if status is ReviewStatus.DRAFT and (reviewer is not None or reviewed_at is not None):
        _fail(path, "draft fixtures cannot carry review approval")
    return Review(
        status=status,
        reviewed_by=reviewer,
        reviewed_at=reviewed_at,
        notes=_string_tuple(obj["notes"], f"{path}.notes"),
    )


def parse_fixture(value: Any, *, source: str = "<fixture>") -> Fixture:
    obj = _strict(
        value,
        source,
        required={
            "schema_version",
            "fixture_id",
            "title",
            "tier",
            "language",
            "criticality",
            "slice_tags",
            "reference_time",
            "timezone",
            "users",
            "events",
            "expected",
            "review",
        },
    )
    version = _string(obj["schema_version"], f"{source}.schema_version")
    if version != SCHEMA_VERSION:
        _fail(f"{source}.schema_version", f"unsupported version {version!r}")
    timezone_name = _string(obj["timezone"], f"{source}.timezone")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        _fail(f"{source}.timezone", "must be a valid IANA timezone")
    reference_time = _datetime(obj["reference_time"], f"{source}.reference_time")
    if reference_time.utcoffset() != reference_time.astimezone(timezone).utcoffset():
        _fail(f"{source}.reference_time", "UTC offset does not match timezone")
    fixture = Fixture(
        schema_version=version,
        fixture_id=_name(obj["fixture_id"], f"{source}.fixture_id"),
        title=_string(obj["title"], f"{source}.title"),
        tier=_enum(Tier, obj["tier"], f"{source}.tier"),
        language=_enum(Language, obj["language"], f"{source}.language"),
        criticality=_enum(Criticality, obj["criticality"], f"{source}.criticality"),
        slice_tags=_name_tuple(
            obj["slice_tags"], f"{source}.slice_tags", nonempty=True
        ),
        reference_time=reference_time,
        timezone=timezone_name,
        users=tuple(
            _user(item, f"{source}.users[{index}]")
            for index, item in enumerate(_array(obj["users"], f"{source}.users"))
        ),
        events=tuple(
            _event(item, f"{source}.events[{index}]")
            for index, item in enumerate(_array(obj["events"], f"{source}.events"))
        ),
        expected=_expected(obj["expected"], f"{source}.expected"),
        review=_review(obj["review"], f"{source}.review"),
    )
    _validate_fixture(fixture, source)
    return fixture


def _unique(values: Sequence[str], path: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        _fail(path, f"duplicate symbolic references: {sorted(duplicates)}")


def _event_text(event: ChatMessageEvent | ToolResultEvent) -> str:
    return event.content if isinstance(event, ChatMessageEvent) else event.payload_json


def _validate_span(
    source_event: str,
    start: int,
    end: int,
    expected_text: str,
    events: Mapping[str, ChatMessageEvent | ToolResultEvent],
    path: str,
) -> None:
    event = events.get(source_event)
    if event is None:
        _fail(path, f"dangling source_event {source_event!r}")
    text = _event_text(event)
    if end > len(text):
        _fail(path, f"span ends at {end}, beyond source length {len(text)}")
    if text[start:end] != expected_text:
        _fail(path, "span does not exactly match annotated text")


def _contains_entity_id(value: Any) -> bool:
    if is_dataclass(value):
        return any(
            _contains_entity_id(getattr(value, field_info.name))
            for field_info in fields(value)
        )
    if isinstance(value, Mapping):
        return any(
            key.lower() in _CANONICAL_ENTITY_KEYS
            or key.lower().endswith("_entity_id")
            or _contains_entity_id(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_entity_id(item) for item in value)
    return False


def _argument_surface(
    argument: CandidateArgument | ForbiddenArgument,
    mentions: Mapping[str, GoldMention],
) -> Any:
    if argument.mention_ref is not None:
        mention = mentions.get(argument.mention_ref)
        return ("surface", None if mention is None else mention.surface_text)
    if isinstance(argument, ForbiddenArgument) and argument.surface_text is not None:
        return ("surface", argument.surface_text)
    return ("literal", _canonical_primitive(argument.literal))


def _semantic_overlap(
    candidate: GoldCandidate,
    forbidden: ForbiddenCandidate,
    mentions: Mapping[str, GoldMention],
) -> bool:
    if forbidden.kind is not None and forbidden.kind != candidate.kind:
        return False
    if forbidden.schema_name is not None and forbidden.schema_name != candidate.schema_name:
        return False
    if (
        forbidden.schema_version is not None
        and forbidden.schema_version != candidate.schema_version
    ):
        return False
    if forbidden.polarity is not None and forbidden.polarity != candidate.polarity:
        return False
    expected_args = sorted(
        (
            argument.role,
            canonical_json_bytes(_argument_surface(argument, mentions)),
        )
        for argument in candidate.arguments
    )
    forbidden_args = sorted(
        (
            argument.role,
            canonical_json_bytes(_argument_surface(argument, mentions)),
        )
        for argument in forbidden.arguments
    )
    if forbidden_args and forbidden_args != expected_args:
        return False
    return all(candidate.attributes.get(key, _MISSING) == item for key, item in forbidden.attributes.items())


def _validate_fixture(fixture: Fixture, path: str) -> None:
    if not fixture.users:
        _fail(f"{path}.users", "must declare at least one synthetic user")
    if not fixture.events:
        _fail(f"{path}.events", "must declare at least one symbolic source event")
    _unique([user.user_alias for user in fixture.users], f"{path}.users")
    _unique([str(user.user_id) for user in fixture.users], f"{path}.users.user_id")
    _unique([event.event_id for event in fixture.events], f"{path}.events")
    users = {user.user_alias for user in fixture.users}
    events = {event.event_id: event for event in fixture.events}
    for index, event in enumerate(fixture.events):
        if event.user_alias not in users:
            _fail(
                f"{path}.events[{index}].user_alias",
                f"dangling user alias {event.user_alias!r}",
            )

    expected = fixture.expected
    _unique([item.mention_id for item in expected.mentions], f"{path}.expected.mentions")
    _unique(
        [item.candidate_ref for item in expected.candidates],
        f"{path}.expected.candidates",
    )
    _unique(
        [item.source_ref_alias for item in expected.sources],
        f"{path}.expected.sources",
    )
    mentions = {mention.mention_id: mention for mention in expected.mentions}

    for index, item in enumerate(expected.sources):
        if item.source_event not in events:
            _fail(
                f"{path}.expected.sources[{index}].source_event",
                f"dangling source event {item.source_event!r}",
            )
        if item.pointer is not None and item.pointer.source_event != item.source_event:
            _fail(f"{path}.expected.sources[{index}].pointer", "source_event mismatch")

    for index, segment in enumerate(expected.segments):
        segment_path = f"{path}.expected.segments[{index}]"
        if segment.pointer.source_event != segment.source_event:
            _fail(f"{segment_path}.pointer", "source_event mismatch")
        if segment.pointer.char_start is not None and segment.pointer.char_end is not None:
            _validate_span(
                segment.source_event,
                segment.pointer.char_start,
                segment.pointer.char_end,
                segment.text,
                events,
                segment_path,
            )

    for collection_name, records in (
        ("forbidden_sources", expected.forbidden_sources),
        ("forbidden_segments", expected.forbidden_segments),
    ):
        for index, record in enumerate(records):
            source_event = record.source_event
            if source_event is not None and source_event not in events:
                _fail(
                    f"{path}.expected.{collection_name}[{index}].source_event",
                    f"dangling source event {source_event!r}",
                )

    for index, mention in enumerate(expected.mentions):
        mention_path = f"{path}.expected.mentions[{index}]"
        if (
            mention.pointer.source_event != mention.source_event
            or mention.pointer.char_start != mention.char_start
            or mention.pointer.char_end != mention.char_end
        ):
            _fail(f"{mention_path}.pointer", "must equal the mention source and span")
        _validate_span(
            mention.source_event,
            mention.char_start,
            mention.char_end,
            mention.surface_text,
            events,
            mention_path,
        )

    for index, candidate in enumerate(expected.candidates):
        candidate_path = f"{path}.expected.candidates[{index}]"
        if _contains_entity_id(candidate):
            _fail(candidate_path, "canonical entity IDs are forbidden")
        referenced_events: set[str] = set()
        for argument_index, argument in enumerate(candidate.arguments):
            if argument.mention_ref is not None:
                mention = mentions.get(argument.mention_ref)
                if mention is None:
                    _fail(
                        f"{candidate_path}.arguments[{argument_index}].mention_ref",
                        f"dangling mention {argument.mention_ref!r}",
                    )
                referenced_events.add(mention.source_event)
        for evidence_index, evidence in enumerate(candidate.evidence):
            evidence_path = f"{candidate_path}.evidence[{evidence_index}]"
            _validate_span(
                evidence.source_event,
                evidence.char_start,
                evidence.char_end,
                evidence.exact_quote,
                events,
                evidence_path,
            )
            referenced_events.add(evidence.source_event)
        event_users = {events[event_id].user_alias for event_id in referenced_events}
        if len(event_users) > 1:
            _fail(candidate_path, "candidate contains cross-user evidence references")
        unresolved = (
            candidate.epistemic.needs_confirmation
            or candidate.epistemic.speaker_commitment
            in {
                SpeakerCommitment.PROBABLE,
                SpeakerCommitment.POSSIBLE,
                SpeakerCommitment.UNCERTAIN,
                SpeakerCommitment.UNKNOWN,
            }
        )
        if unresolved and candidate.polarity is not Polarity.UNKNOWN:
            _fail(candidate_path, "unresolved uncertainty requires unknown polarity")
        if candidate.epistemic.speaker_ref is not None:
            speaker = mentions.get(candidate.epistemic.speaker_ref)
            if speaker is None:
                _fail(
                    f"{candidate_path}.epistemic.speaker_ref",
                    f"dangling mention {candidate.epistemic.speaker_ref!r}",
                )

    for index, forbidden in enumerate(expected.forbidden_candidates):
        forbidden_path = f"{path}.expected.forbidden_candidates[{index}]"
        if _contains_entity_id(forbidden):
            _fail(forbidden_path, "canonical entity IDs are forbidden")
        for argument_index, argument in enumerate(forbidden.arguments):
            if argument.mention_ref is not None and argument.mention_ref not in mentions:
                _fail(
                    f"{forbidden_path}.arguments[{argument_index}].mention_ref",
                    f"dangling mention {argument.mention_ref!r}",
                )
        if any(
            _semantic_overlap(candidate, forbidden, mentions)
            for candidate in expected.candidates
        ):
            _fail(forbidden_path, "duplicates an expected candidate semantic signature")

    if expected.expect_abstention and expected.candidates:
        _fail(
            f"{path}.expected.expect_abstention",
            "cannot be true when expected candidates are present",
        )


def load_fixture(path: str | Path) -> Fixture:
    fixture_path = Path(path)
    try:
        with fixture_path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureValidationError(f"{fixture_path}: cannot load JSON: {exc}") from exc
    return parse_fixture(value, source=str(fixture_path))


def _coverage(value: Any, path: str) -> CoverageRequirements:
    obj = _strict(
        value,
        path,
        required={
            "fixture_count",
            "smoke_count",
            "language_minimums",
            "slice_minimums",
        },
        optional={
            "smoke_slice_minimums",
            "multi_turn_minimum",
            "hard_negative_minimum",
            "require_reviewed",
        },
    )
    languages_obj = _object(obj["language_minimums"], f"{path}.language_minimums")
    language_minimums: dict[Language, int] = {}
    for key, item in languages_obj.items():
        language = _enum(Language, key, f"{path}.language_minimums.{key}")
        language_minimums[language] = _integer(
            item, f"{path}.language_minimums.{key}"
        )
    slices_obj = _object(obj["slice_minimums"], f"{path}.slice_minimums")
    slice_minimums = {
        _name(key, f"{path}.slice_minimums key"): _integer(
            item, f"{path}.slice_minimums.{key}"
        )
        for key, item in slices_obj.items()
    }
    smoke_slices_obj = _object(
        obj.get("smoke_slice_minimums", {}),
        f"{path}.smoke_slice_minimums",
    )
    smoke_slice_minimums = {
        _name(key, f"{path}.smoke_slice_minimums key"): _integer(
            item, f"{path}.smoke_slice_minimums.{key}"
        )
        for key, item in smoke_slices_obj.items()
    }
    return CoverageRequirements(
        fixture_count=_integer(obj["fixture_count"], f"{path}.fixture_count"),
        smoke_count=_integer(obj["smoke_count"], f"{path}.smoke_count"),
        language_minimums=language_minimums,
        slice_minimums=slice_minimums,
        smoke_slice_minimums=smoke_slice_minimums,
        multi_turn_minimum=_integer(
            obj.get("multi_turn_minimum", 0), f"{path}.multi_turn_minimum"
        ),
        hard_negative_minimum=_integer(
            obj.get("hard_negative_minimum", 0), f"{path}.hard_negative_minimum"
        ),
        require_reviewed=_boolean(
            obj.get("require_reviewed", True), f"{path}.require_reviewed"
        ),
    )


def parse_manifest(value: Any, *, source: str = "<manifest>") -> PackManifest:
    obj = _strict(
        value,
        source,
        required={
            "schema_version",
            "pack_id",
            "pack_version",
            "fixtures",
            "coverage",
        },
        optional={"pack_hash"},
    )
    version = _string(obj["schema_version"], f"{source}.schema_version")
    if version != SCHEMA_VERSION:
        _fail(f"{source}.schema_version", f"unsupported version {version!r}")
    fixture_paths = _string_tuple(obj["fixtures"], f"{source}.fixtures")
    if not fixture_paths:
        _fail(f"{source}.fixtures", "must contain at least one fixture")
    pack_hash = obj.get("pack_hash")
    if pack_hash is not None:
        pack_hash = _string(pack_hash, f"{source}.pack_hash")
        if not _HASH_RE.fullmatch(pack_hash):
            _fail(f"{source}.pack_hash", "must be a lowercase SHA-256 digest")
    return PackManifest(
        schema_version=version,
        pack_id=_name(obj["pack_id"], f"{source}.pack_id"),
        pack_version=_name(obj["pack_version"], f"{source}.pack_version"),
        fixtures=fixture_paths,
        coverage=_coverage(obj["coverage"], f"{source}.coverage"),
        pack_hash=pack_hash,
    )


def validate_pack_coverage(
    fixtures: Sequence[Fixture],
    requirements: CoverageRequirements,
) -> None:
    if len(fixtures) != requirements.fixture_count:
        _fail(
            "pack.coverage.fixture_count",
            f"expected exactly {requirements.fixture_count}, got {len(fixtures)}",
        )
    smoke_count = sum(fixture.tier is Tier.SMOKE for fixture in fixtures)
    if smoke_count != requirements.smoke_count:
        _fail(
            "pack.coverage.smoke_count",
            f"expected exactly {requirements.smoke_count}, got {smoke_count}",
        )
    for language, minimum in requirements.language_minimums.items():
        actual = sum(fixture.language is language for fixture in fixtures)
        if actual < minimum:
            _fail(
                f"pack.coverage.language_minimums.{language.value}",
                f"requires at least {minimum}, got {actual}",
            )
    for tag, minimum in requirements.slice_minimums.items():
        actual = sum(tag in fixture.slice_tags for fixture in fixtures)
        if actual < minimum:
            _fail(
                f"pack.coverage.slice_minimums.{tag}",
                f"requires at least {minimum}, got {actual}",
            )
    for tag, minimum in requirements.smoke_slice_minimums.items():
        actual = sum(
            fixture.tier is Tier.SMOKE and tag in fixture.slice_tags
            for fixture in fixtures
        )
        if actual < minimum:
            _fail(
                f"pack.coverage.smoke_slice_minimums.{tag}",
                f"requires at least {minimum}, got {actual}",
            )
    multi_turn = sum(len(fixture.events) > 1 for fixture in fixtures)
    if multi_turn < requirements.multi_turn_minimum:
        _fail(
            "pack.coverage.multi_turn_minimum",
            f"requires at least {requirements.multi_turn_minimum}, got {multi_turn}",
        )
    hard_negative = sum("hard_negative" in fixture.slice_tags for fixture in fixtures)
    if hard_negative < requirements.hard_negative_minimum:
        _fail(
            "pack.coverage.hard_negative_minimum",
            f"requires at least {requirements.hard_negative_minimum}, got {hard_negative}",
        )
    if requirements.require_reviewed:
        drafts = [
            fixture.fixture_id
            for fixture in fixtures
            if fixture.review.status is not ReviewStatus.REVIEWED
        ]
        if drafts:
            _fail("pack.coverage.require_reviewed", f"draft fixtures: {drafts}")


def _canonical_primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {
            field_info.name: _canonical_primitive(getattr(value, field_info.name))
            for field_info in fields(value)
            if not (
                field_info.name == "pack_hash"
                and isinstance(value, PackManifest)
            )
        }
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_primitive(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_primitive(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical_primitive(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_pack_hash(
    manifest: PackManifest,
    fixtures: Sequence[Fixture],
) -> str:
    payload = {
        "manifest": {
            "schema_version": manifest.schema_version,
            "pack_id": manifest.pack_id,
            "pack_version": manifest.pack_version,
            "fixtures": sorted(manifest.fixtures),
            "coverage": manifest.coverage,
        },
        "fixtures": sorted(fixtures, key=lambda fixture: fixture.fixture_id),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def load_pack(path: str | Path) -> FixturePack:
    supplied_path = Path(path)
    manifest_path = supplied_path / "manifest.json" if supplied_path.is_dir() else supplied_path
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest_value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureValidationError(f"{manifest_path}: cannot load JSON: {exc}") from exc
    manifest = parse_manifest(manifest_value, source=str(manifest_path))
    base = manifest_path.parent.resolve()
    fixtures: list[Fixture] = []
    for index, relative in enumerate(manifest.fixtures):
        relative_path = Path(relative)
        if relative_path.is_absolute():
            _fail(f"{manifest_path}.fixtures[{index}]", "must be a relative path")
        fixture_path = (base / relative_path).resolve()
        try:
            fixture_path.relative_to(base)
        except ValueError:
            _fail(f"{manifest_path}.fixtures[{index}]", "must stay inside the pack directory")
        fixtures.append(load_fixture(fixture_path))
    _unique([fixture.fixture_id for fixture in fixtures], f"{manifest_path}.fixtures")
    validate_pack_coverage(fixtures, manifest.coverage)
    digest = canonical_pack_hash(manifest, fixtures)
    if manifest.pack_hash is not None and manifest.pack_hash != digest:
        _fail(
            f"{manifest_path}.pack_hash",
            f"does not match canonical pack hash {digest}",
        )
    return FixturePack(manifest=manifest, fixtures=tuple(fixtures), pack_hash=digest)
