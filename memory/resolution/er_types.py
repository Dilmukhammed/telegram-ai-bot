from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from memory.resolution.schemas import (
    AliasRecord,
    EntityRecord,
    MentionLinkRecord,
    ResolutionVerdictRecord,
    ResolvedArgument,
)


@dataclass(frozen=True, slots=True)
class EntityCandidate:
    entity_id: str
    entity_type: str
    identity_key: str
    canonical_label: str
    status: str
    tier: str  # stable_id | exact_alias | fuzzy | cross_language
    blocking_reason: str
    stable_id: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateSet:
    mention_id: str
    mention_type: str
    candidates: tuple[EntityCandidate, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))


@dataclass(frozen=True, slots=True)
class PairVerdict:
    entity_id: str
    accepted: bool
    reason: str
    tier: str
    decided_by: str  # deterministic | critic


@dataclass(frozen=True, slots=True)
class ClusterVerdict:
    accepted: bool
    reason: str
    decided_by: str  # deterministic | critic


@dataclass(frozen=True, slots=True)
class MergeEventRecord:
    event_id: str
    op: str  # merge | split
    winner_entity_id: str
    loser_entity_id: str
    cluster_key: str | None
    tier: str
    evidence_json: Mapping[str, Any]
    evidence_hash: str
    reason: str
    decided_by: str
    supersedes_event_id: str | None = None
    status: str = "active"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_json", dict(self.evidence_json))


@dataclass(frozen=True, slots=True)
class AliasEquivalenceRecord:
    equivalence_id: str
    normalized_alias_a: str
    language_a: str | None
    normalized_alias_b: str
    language_b: str | None
    entity_type: str
    source: str


@dataclass(frozen=True, slots=True)
class ErConfig:
    candidate_generation_enabled: bool = False
    fuzzy_blocking_enabled: bool = False
    fuzzy_min_trigram: float = 0.6
    cross_language_enabled: bool = False
    cluster_critic_enabled: bool = False
    merge_events_enabled: bool = False
    max_candidates: int = 8


@dataclass(frozen=True, slots=True)
class ErMentionResult:
    resolved: ResolvedArgument
    entity: EntityRecord
    alias: AliasRecord | None
    link: MentionLinkRecord
    verdicts: tuple[ResolutionVerdictRecord, ...]
    merge_events: tuple[MergeEventRecord, ...]
    provisional_entity: EntityRecord | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "verdicts", tuple(self.verdicts))
        object.__setattr__(self, "merge_events", tuple(self.merge_events))
