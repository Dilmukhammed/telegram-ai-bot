from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias


EXTRACTION_SCHEMA_VERSION = "1"

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


def freeze_json(value: Any) -> JsonValue:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def thaw_json(value: JsonValue) -> Any:
    if isinstance(value, Mapping):
        return {str(key): thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


class MentionType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    PLACE = "place"
    PRODUCT = "product"
    DOCUMENT = "document"
    ACCOUNT = "account"
    PROJECT = "project"
    EVENT = "event"
    DATE_OR_TIME = "date_or_time"
    QUANTITY = "quantity"
    CONCEPT = "concept"
    UNKNOWN_ENTITY = "unknown_entity"


class CandidateKind(StrEnum):
    ENTITY_ATTRIBUTE = "entity_attribute"
    PREFERENCE = "preference"
    RELATION = "relation"
    GOAL = "goal"
    TASK = "task"
    STATE = "state"
    CORRECTION = "correction"
    EVENT = "event"


class Polarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class EpistemicMode(StrEnum):
    ASSERTED = "asserted"
    QUOTED = "quoted"
    REPORTED = "reported"
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


class CandidateStatus(StrEnum):
    PROPOSED = "proposed"
    NEEDS_CONTEXT = "needs_context"
    NEEDS_CONFIRMATION = "needs_confirmation"
    INSUFFICIENT = "insufficient"
    READY_FOR_RESOLUTION = "ready_for_resolution"
    CONTRADICTED = "contradicted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


@dataclass(frozen=True, slots=True)
class MentionDraft:
    mention_ref: str
    mention_type: MentionType
    surface_text: str
    char_start: int
    char_end: int
    normalized_hint: str | None = None


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
    alternatives: tuple[JsonValue, ...] = ()
    needs_confirmation: bool = False
    speaker_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "alternatives", tuple(freeze_json(v) for v in self.alternatives))


@dataclass(frozen=True, slots=True)
class Temporal:
    original_text: str | None
    valid_from: str | None
    valid_to: str | None
    event_time: str | None
    precision: str
    timezone: str | None


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    relation: str
    exact_quote: str
    char_start: int
    char_end: int


@dataclass(frozen=True, slots=True)
class CandidateDraft:
    candidate_ref: str
    kind: CandidateKind
    schema_name: str
    schema_version: str
    arguments: tuple[CandidateArgument, ...]
    attributes: Mapping[str, JsonValue]
    polarity: Polarity
    epistemic: Epistemic
    temporal: Temporal | None
    status: CandidateStatus
    evidence: tuple[EvidenceSpan, ...]
    canonical_hint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", tuple(self.arguments))
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType({str(k): freeze_json(v) for k, v in self.attributes.items()}),
        )
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    schema_version: str
    abstain: bool
    mentions: tuple[MentionDraft, ...] = ()
    candidates: tuple[CandidateDraft, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != EXTRACTION_SCHEMA_VERSION:
            raise ValueError(f"unsupported extraction schema version: {self.schema_version!r}")
        object.__setattr__(self, "mentions", tuple(self.mentions))
        object.__setattr__(self, "candidates", tuple(self.candidates))


@dataclass(frozen=True, slots=True)
class SegmentExtraction:
    segment_id: str
    result: ExtractionResult


@dataclass(frozen=True, slots=True)
class ExtractionBatch:
    extractor_name: str
    extractor_version: str
    prompt_version: str
    segments: tuple[SegmentExtraction, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "segments", tuple(self.segments))
