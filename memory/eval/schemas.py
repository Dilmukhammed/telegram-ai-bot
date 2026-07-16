from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


def freeze_json(value: Any) -> JsonValue:
    """Return a recursively immutable JSON value."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): freeze_json(item) for key, item in value.items()}
        )
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, JsonValue]:
    frozen = freeze_json(value)
    assert isinstance(frozen, Mapping)
    return frozen


class Tier(StrEnum):
    SMOKE = "smoke"
    FULL = "full"


class Language(StrEnum):
    RU = "ru"
    EN = "en"
    MIXED = "mixed"


class Criticality(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"


class ReviewStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"


class EventKind(StrEnum):
    CHAT_MESSAGE = "chat_message"
    TOOL_RESULT = "tool_result"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class PayloadKind(StrEnum):
    RESULT = "result"
    ARGUMENTS = "arguments"


class CandidateKind(StrEnum):
    ENTITY_ATTRIBUTE = "entity_attribute"
    RELATION = "relation"
    PREFERENCE = "preference"
    GOAL = "goal"
    TASK = "task"
    STATE = "state"
    OBSERVATION = "observation"
    CORRECTION = "correction"
    ALIAS = "alias"
    DOCUMENT_ASSERTION = "document_assertion"
    EVENT = "event"


class Polarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class EpistemicMode(StrEnum):
    ASSERTED = "asserted"
    QUOTED = "quoted"
    REPORTED = "reported"
    OBSERVED = "observed"
    INFERRED = "inferred"
    RETRIEVED = "retrieved"


class SpeakerCommitment(StrEnum):
    CERTAIN = "certain"
    PROBABLE = "probable"
    POSSIBLE = "possible"
    UNCERTAIN = "uncertain"
    UNKNOWN = "unknown"


class EpistemicScope(StrEnum):
    PROPOSITION = "proposition"
    ARGUMENT = "argument"
    TIME = "time"
    VALUE = "value"


@dataclass(frozen=True, slots=True)
class FixtureUser:
    user_alias: str
    user_id: int
    display_name: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ChatMessageEvent:
    event_id: str
    kind: EventKind
    user_alias: str
    role: ChatRole
    content: str
    content_type: str
    occurred_at: datetime
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ToolResultEvent:
    event_id: str
    kind: EventKind
    user_alias: str
    tool_name: str
    payload_kind: PayloadKind
    payload_json: str
    ok: bool
    cached: bool
    occurred_at: datetime


SourceEvent: TypeAlias = ChatMessageEvent | ToolResultEvent


@dataclass(frozen=True, slots=True)
class SpanPointer:
    source_event: str
    char_start: int | None = None
    char_end: int | None = None


@dataclass(frozen=True, slots=True)
class ExpectedSource:
    source_event: str
    source_type: str
    source_ref_alias: str
    authority_class: str
    content_hash_rule: str
    source_version_count: int
    pointer: SpanPointer | None = None
    normalization_job_status: str | None = None


@dataclass(frozen=True, slots=True)
class ExpectedSegment:
    source_event: str
    segment_type: str
    ordinal: int
    text: str
    normalizer_version: str
    pointer: SpanPointer


@dataclass(frozen=True, slots=True)
class GoldMention:
    mention_id: str
    source_event: str
    mention_type: str
    surface_text: str
    char_start: int
    char_end: int
    normalized_hint: str | None
    pointer: SpanPointer


@dataclass(frozen=True, slots=True)
class CandidateArgument:
    role: str
    mention_ref: str | None = None
    literal: JsonValue = None
    has_literal: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "literal", freeze_json(self.literal))


@dataclass(frozen=True, slots=True)
class Epistemic:
    mode: EpistemicMode
    speaker_commitment: SpeakerCommitment
    scope: EpistemicScope
    alternatives: tuple[JsonValue, ...]
    needs_confirmation: bool
    speaker_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "alternatives", tuple(freeze_json(item) for item in self.alternatives)
        )


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    source_event: str
    relation: str
    exact_quote: str
    char_start: int
    char_end: int


@dataclass(frozen=True, slots=True)
class Temporal:
    original_text: str | None
    valid_from: str | None
    valid_to: str | None
    event_time: str | None
    precision: str
    timezone: str | None


@dataclass(frozen=True, slots=True)
class GoldCandidate:
    candidate_ref: str
    kind: str
    schema_name: str
    schema_version: str
    arguments: tuple[CandidateArgument, ...]
    attributes: Mapping[str, JsonValue]
    polarity: Polarity
    epistemic: Epistemic
    temporal: Temporal | None
    status: str
    evidence: tuple[EvidenceSpan, ...]
    allow_extra_attributes: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", tuple(self.arguments))
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True, slots=True)
class ForbiddenArgument:
    role: str
    mention_ref: str | None = None
    surface_text: str | None = None
    literal: JsonValue = None
    has_literal: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "literal", freeze_json(self.literal))


@dataclass(frozen=True, slots=True)
class ForbiddenCandidate:
    kind: str | None = None
    schema_name: str | None = None
    schema_version: str | None = None
    polarity: Polarity | None = None
    arguments: tuple[ForbiddenArgument, ...] = ()
    attributes: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", tuple(self.arguments))
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))


@dataclass(frozen=True, slots=True)
class ForbiddenSource:
    source_event: str | None = None
    source_type: str | None = None
    authority_class: str | None = None


@dataclass(frozen=True, slots=True)
class ForbiddenSegment:
    source_event: str | None = None
    segment_type: str | None = None
    text: str | None = None


@dataclass(frozen=True, slots=True)
class Expected:
    sources: tuple[ExpectedSource, ...] = ()
    segments: tuple[ExpectedSegment, ...] = ()
    mentions: tuple[GoldMention, ...] = ()
    candidates: tuple[GoldCandidate, ...] = ()
    forbidden_candidates: tuple[ForbiddenCandidate, ...] = ()
    forbidden_sources: tuple[ForbiddenSource, ...] = ()
    forbidden_segments: tuple[ForbiddenSegment, ...] = ()
    expect_abstention: bool = False

    def __post_init__(self) -> None:
        for name in (
            "sources",
            "segments",
            "mentions",
            "candidates",
            "forbidden_candidates",
            "forbidden_sources",
            "forbidden_segments",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class Review:
    status: ReviewStatus
    reviewed_by: str | None
    reviewed_at: datetime | None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "notes", tuple(self.notes))


@dataclass(frozen=True, slots=True)
class Fixture:
    schema_version: str
    fixture_id: str
    title: str
    tier: Tier
    language: Language
    criticality: Criticality
    slice_tags: tuple[str, ...]
    reference_time: datetime
    timezone: str
    users: tuple[FixtureUser, ...]
    events: tuple[SourceEvent, ...]
    expected: Expected
    review: Review

    def __post_init__(self) -> None:
        object.__setattr__(self, "slice_tags", tuple(self.slice_tags))
        object.__setattr__(self, "users", tuple(self.users))
        object.__setattr__(self, "events", tuple(self.events))


@dataclass(frozen=True, slots=True)
class CoverageRequirements:
    fixture_count: int
    smoke_count: int
    language_minimums: Mapping[Language, int]
    slice_minimums: Mapping[str, int]
    smoke_slice_minimums: Mapping[str, int] = field(default_factory=dict)
    multi_turn_minimum: int = 0
    hard_negative_minimum: int = 0
    require_reviewed: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "language_minimums", MappingProxyType(dict(self.language_minimums))
        )
        object.__setattr__(
            self, "slice_minimums", MappingProxyType(dict(self.slice_minimums))
        )
        object.__setattr__(
            self,
            "smoke_slice_minimums",
            MappingProxyType(dict(self.smoke_slice_minimums)),
        )


@dataclass(frozen=True, slots=True)
class PackManifest:
    schema_version: str
    pack_id: str
    pack_version: str
    fixtures: tuple[str, ...]
    coverage: CoverageRequirements
    pack_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fixtures", tuple(self.fixtures))


@dataclass(frozen=True, slots=True)
class FixturePack:
    manifest: PackManifest
    fixtures: tuple[Fixture, ...]
    pack_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "fixtures", tuple(self.fixtures))
