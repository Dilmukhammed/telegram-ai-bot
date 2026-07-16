from __future__ import annotations

import hashlib
from typing import Any

from memory.ids import canonical_json
from memory.models import JobRequest
from memory.resolution.schemas import (
    ASSERTION_SCHEMA_VERSION,
    ER_POLICY_VERSION,
    PROPOSITION_KEY_VERSION,
    RECONCILIATION_POLICY_VERSION,
    RESOLUTION_PROMPT_VERSION,
    RESOLVER_NAME,
    RESOLVER_VERSION,
    UTILITY_POLICY_VERSION,
)


CANDIDATE_RESOLVE_STAGE = "candidate_resolve"


def _er_hash_fields(
    *,
    candidate_generation_enabled: bool = False,
    fuzzy_blocking_enabled: bool = False,
    fuzzy_min_trigram: float = 0.6,
    cross_language_enabled: bool = False,
    cluster_critic_enabled: bool = False,
    merge_events_enabled: bool = False,
    max_candidates: int = 8,
) -> dict[str, Any]:
    if not any(
        (
            candidate_generation_enabled,
            fuzzy_blocking_enabled,
            cross_language_enabled,
            cluster_critic_enabled,
            merge_events_enabled,
        )
    ):
        return {}
    return {
        "er_policy_version": ER_POLICY_VERSION,
        "resolution_candidate_generation_enabled": candidate_generation_enabled,
        "resolution_fuzzy_blocking_enabled": fuzzy_blocking_enabled,
        "resolution_fuzzy_min_trigram": fuzzy_min_trigram,
        "resolution_cross_language_enabled": cross_language_enabled,
        "resolution_cluster_critic_enabled": cluster_critic_enabled,
        "resolution_merge_events_enabled": merge_events_enabled,
        "resolution_max_candidates": max_candidates,
    }


def resolution_input_hash(
    candidate_id: str,
    *,
    score_id: str,
    verdict_set_hash: str,
    required_verification_policy: str,
    support_profile: str = "extraction",
    adversarial_profile: str = "agent",
    candidate_generation_enabled: bool = False,
    fuzzy_blocking_enabled: bool = False,
    fuzzy_min_trigram: float = 0.6,
    cross_language_enabled: bool = False,
    cluster_critic_enabled: bool = False,
    merge_events_enabled: bool = False,
    max_candidates: int = 8,
) -> str:
    payload: dict[str, Any] = {
        "candidate_id": candidate_id,
        "score_id": score_id,
        "verdict_set_hash": verdict_set_hash,
        "required_verification_policy": required_verification_policy,
        "resolver_name": RESOLVER_NAME,
        "resolver_version": RESOLVER_VERSION,
        "assertion_schema_version": ASSERTION_SCHEMA_VERSION,
        "proposition_key_version": PROPOSITION_KEY_VERSION,
        "reconciliation_policy_version": RECONCILIATION_POLICY_VERSION,
        "utility_policy_version": UTILITY_POLICY_VERSION,
        "prompt_version": RESOLUTION_PROMPT_VERSION,
        "support_profile": support_profile,
        "adversarial_profile": adversarial_profile,
    }
    payload.update(
        _er_hash_fields(
            candidate_generation_enabled=candidate_generation_enabled,
            fuzzy_blocking_enabled=fuzzy_blocking_enabled,
            fuzzy_min_trigram=fuzzy_min_trigram,
            cross_language_enabled=cross_language_enabled,
            cluster_critic_enabled=cluster_critic_enabled,
            merge_events_enabled=merge_events_enabled,
            max_candidates=max_candidates,
        )
    )
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def resolution_job_request(
    candidate_id: str,
    *,
    score_id: str,
    verdict_set_hash: str,
    required_verification_policy: str,
    support_profile: str = "extraction",
    adversarial_profile: str = "agent",
    candidate_generation_enabled: bool = False,
    fuzzy_blocking_enabled: bool = False,
    fuzzy_min_trigram: float = 0.6,
    cross_language_enabled: bool = False,
    cluster_critic_enabled: bool = False,
    merge_events_enabled: bool = False,
    max_candidates: int = 8,
) -> JobRequest:
    input_hash = resolution_input_hash(
        candidate_id,
        score_id=score_id,
        verdict_set_hash=verdict_set_hash,
        required_verification_policy=required_verification_policy,
        support_profile=support_profile,
        adversarial_profile=adversarial_profile,
        candidate_generation_enabled=candidate_generation_enabled,
        fuzzy_blocking_enabled=fuzzy_blocking_enabled,
        fuzzy_min_trigram=fuzzy_min_trigram,
        cross_language_enabled=cross_language_enabled,
        cluster_critic_enabled=cluster_critic_enabled,
        merge_events_enabled=merge_events_enabled,
        max_candidates=max_candidates,
    )
    config_payload: dict[str, Any] = {
        "resolver_version": RESOLVER_VERSION,
        "required_verification_policy": required_verification_policy,
        "prompt_version": RESOLUTION_PROMPT_VERSION,
        "support_profile": support_profile,
        "adversarial_profile": adversarial_profile,
    }
    config_payload.update(
        _er_hash_fields(
            candidate_generation_enabled=candidate_generation_enabled,
            fuzzy_blocking_enabled=fuzzy_blocking_enabled,
            fuzzy_min_trigram=fuzzy_min_trigram,
            cross_language_enabled=cross_language_enabled,
            cluster_critic_enabled=cluster_critic_enabled,
            merge_events_enabled=merge_events_enabled,
            max_candidates=max_candidates,
        )
    )
    config_hash = hashlib.sha256(
        canonical_json(config_payload).encode("utf-8")
    ).hexdigest()[:16]
    return JobRequest(
        stage=CANDIDATE_RESOLVE_STAGE,
        processor_name=RESOLVER_NAME,
        processor_version=RESOLVER_VERSION,
        prompt_version=RESOLUTION_PROMPT_VERSION,
        model_profile=support_profile,
        input_hash=input_hash,
        config_hash=config_hash,
        target_kind="candidate",
        target_id=candidate_id,
    )
