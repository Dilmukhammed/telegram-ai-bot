from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from memory.config import MemoryConfig

ATTACHMENT_VERSION = "2"
ATTACHMENT_PROMPT_VERSION = "attachment_committee_v2"
ATTACHMENT_SCHEMA_VERSION = "1"
PROCESSOR_NAME = "attachment_analyzer"
PROCESSOR_VERSION = "4"

ATTACH_OPS = frozenset(
    {
        "alias_of",
        "instance_of",
        "subtype_of",
        "cuisine_of",
        "topic_of",
        "part_of",
        "located_in",
        "same_as",
        "inferred_preference",
        "corroborates",
        "add_to_group",
        "abstain",
    }
)

DOMAIN_PACKS = frozenset({"food", "geo", "org", "topic", "synonym", "software"})

DOMAIN_ALLOWED_OPS: dict[str, frozenset[str]] = {
    "food": frozenset({"cuisine_of", "instance_of", "alias_of", "topic_of", "inferred_preference", "add_to_group"}),
    "geo": frozenset({"located_in", "part_of", "instance_of", "alias_of", "add_to_group"}),
    "org": frozenset({"alias_of", "same_as", "instance_of", "part_of", "add_to_group"}),
    "topic": frozenset({"topic_of", "subtype_of", "instance_of", "part_of", "alias_of", "add_to_group"}),
    "software": frozenset({"subtype_of", "instance_of", "part_of", "alias_of", "topic_of", "add_to_group"}),
    "synonym": frozenset({"alias_of", "same_as", "add_to_group"}),
}

# Extraction kinds + concrete predicates (LLM emits likes_food, works_at, …).
TRIGGER_SCHEMAS = frozenset(
    {
        "preference",
        "product",
        "place",
        "organization",
        "project",
        "topic",
        "document_assertion",
        "prefers",
        "likes_food",
        "likes_music",
        "likes_cuisine",
        "works_at",
        "lives_in",
        "moves_to",
        "located_in",
    }
)

TRIGGER_SCHEMA_PREFIXES = (
    "likes_",
    "prefer",
    "works_",
    "lives_",
    "moves_",
    "located_",
)


def is_trigger_schema(schema_name: str, *, candidate_kind: str | None = None) -> bool:
    name = (schema_name or "").strip()
    kind = (candidate_kind or "").strip()
    if name in TRIGGER_SCHEMAS or kind in TRIGGER_SCHEMAS:
        return True
    lowered = name.casefold()
    return any(lowered.startswith(prefix) for prefix in TRIGGER_SCHEMA_PREFIXES)

TIER_CURATED = "curated"
TIER_HYBRID = "hybrid"
TIER_LLM_COMMITTEE = "llm_committee"

STATUS_ACTIVE = "active"
STATUS_REVERTED = "reverted"
STATUS_POSSIBLE = "possible"

UTILITY_DEFERRED = "deferred"
UTILITY_DURABLE = "durable"


@dataclass(frozen=True, slots=True)
class AttachmentConfig:
    enabled: bool
    generation_enabled: bool
    verify_enabled: bool
    two_generator_enabled: bool
    vector_enabled: bool
    curated_taxonomy_enabled: bool
    inferred_preference_enabled: bool
    write_graph_edges: bool
    write_possible_events: bool
    scan_interval_seconds: float
    scan_batch_size: int
    debounce_seconds: float
    max_candidates: int
    max_llm_calls: int
    model_profile: str
    support_model_profile: str
    adversarial_model_profile: str
    cluster_model_profile: str
    max_tokens: int
    react_enabled: bool = False
    react_mode: str = "shadow"
    react_model_profile: str = "agent"
    react_max_actions: int = 10
    react_max_hops: int = 3
    react_max_results: int = 10
    react_max_nodes: int = 60
    react_max_tokens: int = 4096


def attachment_config_from_memory_config(config: MemoryConfig) -> AttachmentConfig:
    return AttachmentConfig(
        enabled=config.attachment_enabled,
        generation_enabled=config.attachment_generation_enabled,
        verify_enabled=config.attachment_verify_enabled,
        two_generator_enabled=config.attachment_two_generator_enabled,
        vector_enabled=config.attachment_vector_enabled,
        curated_taxonomy_enabled=config.attachment_curated_taxonomy_enabled,
        inferred_preference_enabled=config.attachment_inferred_preference_enabled,
        write_graph_edges=config.attachment_write_graph_edges,
        write_possible_events=config.attachment_write_possible_events,
        scan_interval_seconds=config.attachment_scan_interval_seconds,
        scan_batch_size=config.attachment_scan_batch_size,
        debounce_seconds=config.attachment_debounce_seconds,
        max_candidates=config.attachment_max_candidates,
        max_llm_calls=config.attachment_max_llm_calls,
        model_profile=config.attachment_model_profile,
        support_model_profile=config.attachment_support_model_profile,
        adversarial_model_profile=config.attachment_adversarial_model_profile,
        cluster_model_profile=config.attachment_cluster_model_profile,
        max_tokens=config.attachment_max_tokens,
        react_enabled=config.attachment_react_enabled,
        react_mode=config.attachment_react_mode,
        react_model_profile=config.attachment_react_model_profile,
        react_max_actions=config.attachment_react_max_actions,
        react_max_hops=config.attachment_react_max_hops,
        react_max_results=config.attachment_react_max_results,
        react_max_nodes=config.attachment_react_max_nodes,
        react_max_tokens=config.attachment_react_max_tokens,
    )


@dataclass(frozen=True, slots=True)
class ShortlistCandidate:
    target_id: str
    label: str
    entity_type: str
    op_hint: str | None = None
    score: float = 0.0
    channel: str = ""
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AttachmentHypothesis:
    op: str
    target_id: str
    promote_preference: bool = False
    confidence: float = 0.0
    reason_codes: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LayerVerdict:
    layer: str
    verdict: str
    detail: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AttachmentAnalyzeResult:
    accepted: bool
    abstain_reason: str | None
    hypothesis: AttachmentHypothesis | None
    utility_class: str | None
    tier: str | None
    domain_pack: str | None
    shortlist: tuple[ShortlistCandidate, ...]
    layer_trace: tuple[LayerVerdict, ...]
    llm_calls: int
    source_entity_id: str | None
    source_belief_id: str | None
    risk_class: str | None = None
    accepted_hypotheses: tuple[AttachmentHypothesis, ...] = ()
