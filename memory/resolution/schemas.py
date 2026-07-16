from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


RESOLVER_NAME = "minimal_entity_assertion_resolver"
RESOLVER_VERSION = "2"
ER_POLICY_VERSION = "1"
ASSERTION_SCHEMA_VERSION = "1"
PROPOSITION_KEY_VERSION = "1"
RECONCILIATION_POLICY_VERSION = "temporal_belief_v1"
UTILITY_POLICY_VERSION = "minimal_utility_v1"
RESOLUTION_PROMPT_VERSION = "entity_link_verification_v1"
CRITIC_NAME = "entity_link_critic"
CRITIC_VERSION = "1"

EXACT_ALIAS_TYPES = frozenset({"organization", "place", "project"})
ALIAS_CRITIC_RISK = "support_and_adversarial"


@dataclass(frozen=True, slots=True)
class ResolvedArgument:
    role: str
    value_kind: str  # entity | literal
    entity_id: str | None = None
    literal: Any = None

    def to_mapping(self) -> dict[str, Any]:
        if self.value_kind == "entity":
            return {
                "role": self.role,
                "value_kind": "entity",
                "entity_id": self.entity_id,
            }
        return {
            "role": self.role,
            "value_kind": "literal",
            "literal": self.literal,
        }


@dataclass(frozen=True, slots=True)
class EntityRecord:
    entity_id: str
    entity_type: str
    identity_key: str
    canonical_label: str
    status: str  # active | provisional
    decision: str


@dataclass(frozen=True, slots=True)
class AliasRecord:
    alias_id: str
    entity_id: str
    source_mention_id: str | None
    alias: str
    normalized_alias: str
    language: str | None = None
    evidence_pointer_json: str | None = None


@dataclass(frozen=True, slots=True)
class MentionLinkRecord:
    link_id: str
    mention_id: str
    entity_id: str
    decision: str
    resolution_components: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ProposedExactAlias:
    """Deterministic candidate for reuse; requires critic confirmation."""

    mention_id: str
    mention_type: str
    surface_text: str
    normalized_alias: str
    proposed_entity: EntityRecord
    active_aliases: tuple[str, ...]
    role: str


@dataclass(frozen=True, slots=True)
class ResolutionVerdictRecord:
    resolution_verdict_id: str
    mention_id: str
    proposed_entity_id: str
    role: str  # support | adversarial
    verdict: str
    scope_errors: tuple[str, ...]
    ambiguities: tuple[str, ...]
    missing_context: tuple[str, ...]
    critic_name: str
    critic_version: str
    prompt_version: str
    model_profile: str | None
    model_name: str | None
    reasoning_effort: str | None
    input_hash: str
    output_json: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AssertionRecord:
    assertion_id: str
    candidate_id: str
    proposition_key: str
    cluster_key: str
    candidate_kind: str
    schema_name: str
    schema_version: str
    resolved_arguments: tuple[ResolvedArgument, ...]
    attributes: Mapping[str, Any]
    polarity: str
    epistemic: Mapping[str, Any]
    temporal: Mapping[str, Any] | None
    observed_at: str | None
    status: str


@dataclass(frozen=True, slots=True)
class BeliefSupportRecord:
    assertion_id: str
    relation: str
    weight_components: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class BeliefRevisionRecord:
    belief_revision_id: str
    belief_id: str
    proposition_key: str
    cluster_key: str
    schema_name: str
    input_set_hash: str
    resolved_arguments: tuple[ResolvedArgument, ...]
    resolved_value: Mapping[str, Any] | None
    polarity: str
    temporal: Mapping[str, Any] | None
    belief_status: str
    utility_class: str
    utility_reason_codes: tuple[str, ...]
    confidence_components: Mapping[str, Any]
    supersedes_revision_id: str | None
    support: tuple[BeliefSupportRecord, ...]


@dataclass(frozen=True, slots=True)
class ResolutionBatch:
    entities: tuple[EntityRecord, ...] = ()
    aliases: tuple[AliasRecord, ...] = ()
    mention_links: tuple[MentionLinkRecord, ...] = ()
    resolution_verdicts: tuple[ResolutionVerdictRecord, ...] = ()
    assertion: AssertionRecord | None = None
    belief_revision: BeliefRevisionRecord | None = None
    set_belief_head: bool = False
    additional_assertions: tuple[AssertionRecord, ...] = ()
    additional_belief_revisions: tuple[BeliefRevisionRecord, ...] = ()
    historicalize_assertion_ids: tuple[str, ...] = ()
    merge_events: tuple = ()  # MergeEventRecord items from er_types

    def __post_init__(self) -> None:
        object.__setattr__(self, "entities", tuple(self.entities))
        object.__setattr__(self, "aliases", tuple(self.aliases))
        object.__setattr__(self, "mention_links", tuple(self.mention_links))
        object.__setattr__(self, "resolution_verdicts", tuple(self.resolution_verdicts))
        object.__setattr__(self, "additional_assertions", tuple(self.additional_assertions))
        object.__setattr__(
            self, "additional_belief_revisions", tuple(self.additional_belief_revisions)
        )
        object.__setattr__(
            self, "historicalize_assertion_ids", tuple(self.historicalize_assertion_ids)
        )
        object.__setattr__(self, "merge_events", tuple(self.merge_events))
