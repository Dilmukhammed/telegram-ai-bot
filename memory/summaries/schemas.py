from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from memory.config import MemoryConfig

SUMMARY_POLICY_VERSION = "summaries_v1"
GENERATOR_NAME = "belief_snapshot_summarizer"
GENERATOR_VERSION = "1"
SUMMARY_PROMPT_VERSION = "summary_generation_v1"
VERIFIER_NAME = "summary_sentence_verifier"
VERIFIER_VERSION = "1"
VERIFY_PROMPT_VERSION = "summary_verify_v1"
DETECTOR_VERSION = "typed_domain_v1"

SUMMARY_TYPE_CORE_PROFILE = "core_profile"
SUMMARY_TYPE_ENTITY = "entity"
SUMMARY_TYPE_TIMELINE_USER = "timeline_user"
SUMMARY_TYPE_TIMELINE_ENTITY = "timeline_entity"
SUMMARY_TYPE_ACTIVE_STATE = "active_state"
SUMMARY_TYPE_COMMUNITY = "community"

ALL_SUMMARY_TYPES = (
    SUMMARY_TYPE_CORE_PROFILE,
    SUMMARY_TYPE_ENTITY,
    SUMMARY_TYPE_TIMELINE_USER,
    SUMMARY_TYPE_TIMELINE_ENTITY,
    SUMMARY_TYPE_ACTIVE_STATE,
    SUMMARY_TYPE_COMMUNITY,
)

STATUS_ACTIVE = "active"
STATUS_REJECTED = "rejected"
STATUS_SUPERSEDED = "superseded"
STATUS_STALE = "stale"

COMMUNITY_FAMILY = "family"
COMMUNITY_WORK = "work"
COMMUNITY_PROJECT = "project"
COMMUNITY_TRIP_PLACE = "trip_place"
COMMUNITY_DOCUMENTS_TASKS = "documents_tasks"
COMMUNITY_INTERESTS = "interests"

ALL_COMMUNITY_TYPES = (
    COMMUNITY_FAMILY,
    COMMUNITY_WORK,
    COMMUNITY_PROJECT,
    COMMUNITY_TRIP_PLACE,
    COMMUNITY_DOCUMENTS_TASKS,
    COMMUNITY_INTERESTS,
)


@dataclass(frozen=True, slots=True)
class SummaryConfig:
    summaries_enabled: bool
    generation_enabled: bool
    verify_enabled: bool
    communities_enabled: bool
    shadow_pack_enabled: bool
    scan_interval_seconds: float
    scan_batch_size: int
    debounce_seconds: float
    full_rebuild_every_n: int
    model_profile: str
    verify_model_profile: str
    max_tokens: int
    community_label_enabled: bool


@dataclass(frozen=True, slots=True)
class BeliefSnapshot:
    belief_id: str
    schema_name: str
    statement: str
    belief_status: str
    utility_class: str
    polarity: str
    entity_ids: tuple[str, ...]
    temporal: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class SummarySentence:
    text: str
    belief_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SummaryDraft:
    sentences: tuple[SummarySentence, ...]
    content: str
    belief_ids: tuple[str, ...]
    sentence_support: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class SentenceVerdict:
    sentence_index: int
    verdict: str  # supported | unsupported | uncertain
    belief_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VerificationResult:
    accepted: bool
    sentence_verdicts: tuple[SentenceVerdict, ...]
    reject_reason: str | None = None


def summary_config_from_memory_config(config: "MemoryConfig") -> SummaryConfig:
    return SummaryConfig(
        summaries_enabled=config.summaries_enabled,
        generation_enabled=config.summaries_generation_enabled,
        verify_enabled=config.summaries_verify_enabled,
        communities_enabled=config.summaries_communities_enabled,
        shadow_pack_enabled=config.summaries_shadow_pack_enabled,
        scan_interval_seconds=config.summaries_scan_interval_seconds,
        scan_batch_size=config.summaries_scan_batch_size,
        debounce_seconds=config.summaries_debounce_seconds,
        full_rebuild_every_n=config.summaries_full_rebuild_every_n,
        model_profile=config.summaries_model_profile,
        verify_model_profile=config.summaries_verify_model_profile,
        max_tokens=config.summaries_max_tokens,
        community_label_enabled=config.summaries_community_label_enabled,
    )


def user_target_id(user_id: int) -> str:
    return f"user:{user_id}"
