from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryConfig:
    ingest_enabled: bool
    db_path: str
    worker_enabled: bool
    worker_concurrency: int
    worker_poll_seconds: float
    job_lease_seconds: int
    job_max_attempts: int
    job_retry_base_seconds: float
    job_retry_max_seconds: float
    job_claim_batch_size: int
    # Text ingestion pipeline
    ingest_queue_maxsize: int = 1000
    ingest_scan_interval_seconds: float = 30.0
    ingest_scan_batch_size: int = 100
    ingest_failure_max_attempts: int = 10
    ingest_retry_base_seconds: float = 5.0
    ingest_retry_max_seconds: float = 900.0
    text_segment_chars: int = 4000
    text_segment_overlap: int = 200
    tool_reconcile_batch_size: int = 100
    ingest_shutdown_grace_seconds: float = 10.0
    # PR 3 text candidate extraction (shadow-only)
    extraction_enabled: bool = False
    extraction_model_profile: str = "extraction"
    extraction_max_tokens: int = 4096
    # PR 4 independent candidate verification (shadow-only)
    verification_enabled: bool = False
    verification_support_model_profile: str = "extraction"
    verification_adversarial_model_profile: str = "agent"
    verification_max_tokens: int = 2048
    verification_scan_interval_seconds: float = 30.0
    verification_scan_batch_size: int = 100
    verification_context_chars: int = 240
    verification_policy_version: str = "verification_policy_v2"
    # PR 5 entity/assertion resolution (shadow-only)
    resolution_enabled: bool = False
    resolution_scan_interval_seconds: float = 30.0
    resolution_scan_batch_size: int = 100
    required_verification_policy_version: str = "verification_policy_v2"
    resolution_link_support_model_profile: str = "extraction"
    resolution_link_adversarial_model_profile: str = "agent"
    resolution_max_tokens: int = 1536
    # PR 11 full entity resolution (opt-in; flag-off stays PR5-compatible)
    resolution_candidate_generation_enabled: bool = False
    resolution_fuzzy_blocking_enabled: bool = False
    resolution_fuzzy_min_trigram: float = 0.6
    resolution_cross_language_enabled: bool = False
    resolution_cluster_critic_enabled: bool = False
    resolution_merge_events_enabled: bool = False
    resolution_relink_on_invalidation: bool = False
    resolution_max_candidates: int = 8
    # PR 6 graph projection (shadow-only)
    graph_enabled: bool = False
    graph_scan_interval_seconds: float = 30.0
    graph_scan_batch_size: int = 100
    # PR 8 shadow retrieval (never mutates agent prompt)
    shadow_retrieval_enabled: bool = False
    shadow_retrieval_timeout_seconds: float = 2.0
    shadow_retrieval_token_budget: int = 4000
    shadow_retrieval_max_beliefs: int = 24
    shadow_retrieval_max_hops: int = 3
    # PR 9 documents (shadow structure + optional extraction)
    documents_enabled: bool = False
    # PR 12 graph summaries + communities (shadow-only)
    summaries_enabled: bool = False
    summaries_generation_enabled: bool = False
    summaries_verify_enabled: bool = True
    summaries_communities_enabled: bool = False
    summaries_shadow_pack_enabled: bool = False
    summaries_scan_interval_seconds: float = 30.0
    summaries_scan_batch_size: int = 50
    summaries_debounce_seconds: float = 120.0
    summaries_full_rebuild_every_n: int = 50
    summaries_model_profile: str = "summarize"
    summaries_verify_model_profile: str = "extraction"
    summaries_max_tokens: int = 2048
    summaries_community_label_enabled: bool = False
    # PR 14 attachment engine (shadow-only)
    attachment_enabled: bool = False
    attachment_generation_enabled: bool = False
    attachment_verify_enabled: bool = True
    attachment_two_generator_enabled: bool = False
    attachment_vector_enabled: bool = True
    attachment_curated_taxonomy_enabled: bool = True
    attachment_inferred_preference_enabled: bool = True
    attachment_write_graph_edges: bool = True
    attachment_write_possible_events: bool = False
    attachment_scan_interval_seconds: float = 30.0
    attachment_scan_batch_size: int = 20
    attachment_debounce_seconds: float = 2.0
    attachment_max_candidates: int = 12
    attachment_max_llm_calls: int = 6
    attachment_model_profile: str = "extraction"
    attachment_support_model_profile: str = "extraction"
    attachment_adversarial_model_profile: str = "agent"
    attachment_cluster_model_profile: str = "agent"
    attachment_max_tokens: int = 4096
    attachment_react_enabled: bool = False
    attachment_react_mode: str = "shadow"
    attachment_react_model_profile: str = "agent"
    attachment_react_max_actions: int = 10
    attachment_react_max_hops: int = 3
    attachment_react_max_results: int = 10
    attachment_react_max_nodes: int = 60
    attachment_react_max_tokens: int = 4096


def memory_config_from_settings() -> MemoryConfig:
    from config import get_settings

    settings = get_settings()
    return MemoryConfig(
        ingest_enabled=settings.memory_ingest_enabled,
        db_path=settings.memory_db_path,
        worker_enabled=settings.memory_worker_enabled,
        worker_concurrency=settings.memory_worker_concurrency,
        worker_poll_seconds=settings.memory_worker_poll_seconds,
        job_lease_seconds=settings.memory_job_lease_seconds,
        job_max_attempts=settings.memory_job_max_attempts,
        job_retry_base_seconds=settings.memory_job_retry_base_seconds,
        job_retry_max_seconds=settings.memory_job_retry_max_seconds,
        job_claim_batch_size=settings.memory_job_claim_batch_size,
        ingest_queue_maxsize=settings.memory_ingest_queue_maxsize,
        ingest_scan_interval_seconds=settings.memory_ingest_scan_interval_seconds,
        ingest_scan_batch_size=settings.memory_ingest_scan_batch_size,
        ingest_failure_max_attempts=settings.memory_ingest_failure_max_attempts,
        ingest_retry_base_seconds=settings.memory_ingest_retry_base_seconds,
        ingest_retry_max_seconds=settings.memory_ingest_retry_max_seconds,
        text_segment_chars=settings.memory_text_segment_chars,
        text_segment_overlap=settings.memory_text_segment_overlap,
        tool_reconcile_batch_size=settings.memory_tool_reconcile_batch_size,
        ingest_shutdown_grace_seconds=settings.memory_ingest_shutdown_grace_seconds,
        extraction_enabled=settings.memory_extraction_enabled,
        extraction_model_profile=settings.memory_extraction_model_profile,
        extraction_max_tokens=settings.memory_extraction_max_tokens,
        verification_enabled=settings.memory_verification_enabled,
        verification_support_model_profile=settings.memory_verification_support_model_profile,
        verification_adversarial_model_profile=(
            settings.memory_verification_adversarial_model_profile
        ),
        verification_max_tokens=settings.memory_verification_max_tokens,
        verification_scan_interval_seconds=(
            settings.memory_verification_scan_interval_seconds
        ),
        verification_scan_batch_size=settings.memory_verification_scan_batch_size,
        verification_context_chars=settings.memory_verification_context_chars,
        verification_policy_version=settings.memory_verification_policy_version,
        resolution_enabled=settings.memory_resolution_enabled,
        resolution_scan_interval_seconds=settings.memory_resolution_scan_interval_seconds,
        resolution_scan_batch_size=settings.memory_resolution_scan_batch_size,
        required_verification_policy_version=(
            settings.memory_required_verification_policy_version
        ),
        resolution_link_support_model_profile=(
            settings.memory_resolution_link_support_model_profile
        ),
        resolution_link_adversarial_model_profile=(
            settings.memory_resolution_link_adversarial_model_profile
        ),
        resolution_max_tokens=settings.memory_resolution_max_tokens,
        resolution_candidate_generation_enabled=(
            settings.memory_resolution_candidate_generation_enabled
        ),
        resolution_fuzzy_blocking_enabled=settings.memory_resolution_fuzzy_blocking_enabled,
        resolution_fuzzy_min_trigram=settings.memory_resolution_fuzzy_min_trigram,
        resolution_cross_language_enabled=settings.memory_resolution_cross_language_enabled,
        resolution_cluster_critic_enabled=settings.memory_resolution_cluster_critic_enabled,
        resolution_merge_events_enabled=settings.memory_resolution_merge_events_enabled,
        resolution_relink_on_invalidation=settings.memory_resolution_relink_on_invalidation,
        resolution_max_candidates=settings.memory_resolution_max_candidates,
        graph_enabled=settings.memory_graph_enabled,
        graph_scan_interval_seconds=settings.memory_graph_scan_interval_seconds,
        graph_scan_batch_size=settings.memory_graph_scan_batch_size,
        shadow_retrieval_enabled=settings.memory_shadow_retrieval_enabled,
        shadow_retrieval_timeout_seconds=(
            settings.memory_shadow_retrieval_timeout_seconds
        ),
        shadow_retrieval_token_budget=settings.memory_shadow_retrieval_token_budget,
        shadow_retrieval_max_beliefs=settings.memory_shadow_retrieval_max_beliefs,
        shadow_retrieval_max_hops=settings.memory_shadow_retrieval_max_hops,
        documents_enabled=settings.memory_documents_enabled,
        summaries_enabled=settings.memory_summaries_enabled,
        summaries_generation_enabled=settings.memory_summaries_generation_enabled,
        summaries_verify_enabled=settings.memory_summaries_verify_enabled,
        summaries_communities_enabled=settings.memory_summaries_communities_enabled,
        summaries_shadow_pack_enabled=settings.memory_summaries_shadow_pack_enabled,
        summaries_scan_interval_seconds=settings.memory_summaries_scan_interval_seconds,
        summaries_scan_batch_size=settings.memory_summaries_scan_batch_size,
        summaries_debounce_seconds=settings.memory_summaries_debounce_seconds,
        summaries_full_rebuild_every_n=settings.memory_summaries_full_rebuild_every_n,
        summaries_model_profile=settings.memory_summaries_model_profile,
        summaries_verify_model_profile=settings.memory_summaries_verify_model_profile,
        summaries_max_tokens=settings.memory_summaries_max_tokens,
        summaries_community_label_enabled=settings.memory_summaries_community_label_enabled,
        attachment_enabled=settings.memory_attachment_enabled,
        attachment_generation_enabled=settings.memory_attachment_generation_enabled,
        attachment_verify_enabled=settings.memory_attachment_verify_enabled,
        attachment_two_generator_enabled=settings.memory_attachment_two_generator_enabled,
        attachment_vector_enabled=settings.memory_attachment_vector_enabled,
        attachment_curated_taxonomy_enabled=settings.memory_attachment_curated_taxonomy_enabled,
        attachment_inferred_preference_enabled=settings.memory_attachment_inferred_preference_enabled,
        attachment_write_graph_edges=settings.memory_attachment_write_graph_edges,
        attachment_write_possible_events=settings.memory_attachment_write_possible_events,
        attachment_scan_interval_seconds=settings.memory_attachment_scan_interval_seconds,
        attachment_scan_batch_size=settings.memory_attachment_scan_batch_size,
        attachment_debounce_seconds=settings.memory_attachment_debounce_seconds,
        attachment_max_candidates=settings.memory_attachment_max_candidates,
        attachment_max_llm_calls=settings.memory_attachment_max_llm_calls,
        attachment_model_profile=settings.memory_attachment_model_profile,
        attachment_support_model_profile=settings.memory_attachment_support_model_profile,
        attachment_adversarial_model_profile=settings.memory_attachment_adversarial_model_profile,
        attachment_cluster_model_profile=settings.memory_attachment_cluster_model_profile,
        attachment_max_tokens=settings.memory_attachment_max_tokens,
        attachment_react_enabled=settings.memory_attachment_react_enabled,
        attachment_react_mode=settings.memory_attachment_react_mode,
        attachment_react_model_profile=settings.memory_attachment_react_model_profile,
        attachment_react_max_actions=settings.memory_attachment_react_max_actions,
        attachment_react_max_hops=settings.memory_attachment_react_max_hops,
        attachment_react_max_results=settings.memory_attachment_react_max_results,
        attachment_react_max_nodes=settings.memory_attachment_react_max_nodes,
        attachment_react_max_tokens=settings.memory_attachment_react_max_tokens,
    )


def er_config_from_memory_config(config: MemoryConfig) -> "ErConfig":
    from memory.resolution.er_types import ErConfig

    return ErConfig(
        candidate_generation_enabled=config.resolution_candidate_generation_enabled,
        fuzzy_blocking_enabled=config.resolution_fuzzy_blocking_enabled,
        fuzzy_min_trigram=config.resolution_fuzzy_min_trigram,
        cross_language_enabled=config.resolution_cross_language_enabled,
        cluster_critic_enabled=config.resolution_cluster_critic_enabled,
        merge_events_enabled=config.resolution_merge_events_enabled,
        max_candidates=config.resolution_max_candidates,
    )


def validate_memory_config(config: MemoryConfig) -> None:
    if config.worker_concurrency < 1:
        raise ValueError("memory worker concurrency must be >= 1")
    if config.worker_poll_seconds <= 0:
        raise ValueError("memory worker poll seconds must be > 0")
    if config.job_lease_seconds < 1:
        raise ValueError("memory job lease seconds must be >= 1")
    if config.job_max_attempts < 1:
        raise ValueError("memory job max attempts must be >= 1")
    if config.job_retry_base_seconds <= 0:
        raise ValueError("memory job retry base seconds must be > 0")
    if config.job_retry_max_seconds < config.job_retry_base_seconds:
        raise ValueError("memory job retry max must be >= retry base")
    if config.job_claim_batch_size < 1:
        raise ValueError("memory job claim batch size must be >= 1")
    if config.ingest_queue_maxsize < 1:
        raise ValueError("memory ingest queue maxsize must be >= 1")
    if config.ingest_scan_batch_size < 1:
        raise ValueError("memory ingest scan batch size must be >= 1")
    if config.ingest_failure_max_attempts < 1:
        raise ValueError("memory ingest failure max attempts must be >= 1")
    if config.ingest_retry_base_seconds <= 0:
        raise ValueError("memory ingest retry base seconds must be > 0")
    if config.ingest_retry_max_seconds < config.ingest_retry_base_seconds:
        raise ValueError("memory ingest retry max must be >= retry base")
    if config.text_segment_chars < 1:
        raise ValueError("memory text segment chars must be >= 1")
    if config.text_segment_overlap < 0:
        raise ValueError("memory text segment overlap must be >= 0")
    if config.text_segment_overlap >= config.text_segment_chars:
        raise ValueError("memory text segment overlap must be < text segment chars")
    if config.tool_reconcile_batch_size < 1:
        raise ValueError("memory tool reconcile batch size must be >= 1")
    if config.ingest_scan_interval_seconds <= 0:
        raise ValueError("memory ingest scan interval seconds must be > 0")
    if config.ingest_shutdown_grace_seconds <= 0:
        raise ValueError("memory ingest shutdown grace seconds must be > 0")
    if not config.extraction_model_profile.strip():
        raise ValueError("memory extraction model profile must be non-empty")
    if config.extraction_model_profile not in {"agent", "summarize", "checker", "extraction"}:
        raise ValueError(
            "memory extraction model profile must be agent, summarize, checker, or extraction"
        )
    if config.extraction_max_tokens < 256:
        raise ValueError("memory extraction max tokens must be >= 256")
    profiles = {"agent", "summarize", "checker", "extraction"}
    if config.verification_support_model_profile not in profiles:
        raise ValueError("invalid memory verification support model profile")
    if config.verification_adversarial_model_profile not in profiles:
        raise ValueError("invalid memory verification adversarial model profile")
    if config.verification_max_tokens < 256:
        raise ValueError("memory verification max tokens must be >= 256")
    if config.verification_scan_interval_seconds <= 0:
        raise ValueError("memory verification scan interval must be > 0")
    if config.verification_scan_batch_size < 1:
        raise ValueError("memory verification scan batch size must be >= 1")
    if config.verification_context_chars < 0:
        raise ValueError("memory verification context chars must be >= 0")
    if not config.verification_policy_version.strip():
        raise ValueError("memory verification policy version must be non-empty")
    if config.resolution_scan_interval_seconds <= 0:
        raise ValueError("memory resolution scan interval must be > 0")
    if config.resolution_scan_batch_size < 1:
        raise ValueError("memory resolution scan batch size must be >= 1")
    if not config.required_verification_policy_version.strip():
        raise ValueError("memory required verification policy version must be non-empty")
    profiles = {"agent", "summarize", "checker", "extraction"}
    if config.resolution_link_support_model_profile not in profiles:
        raise ValueError("invalid memory resolution link support model profile")
    if config.resolution_link_adversarial_model_profile not in profiles:
        raise ValueError("invalid memory resolution link adversarial model profile")
    if config.resolution_max_tokens < 256:
        raise ValueError("memory resolution max tokens must be >= 256")
    if config.resolution_candidate_generation_enabled and not config.resolution_merge_events_enabled:
        raise ValueError(
            "MEMORY_RESOLUTION_MERGE_EVENTS_ENABLED=1 is required when "
            "candidate generation is enabled"
        )
    if (
        config.resolution_fuzzy_blocking_enabled
        or config.resolution_cross_language_enabled
        or config.resolution_cluster_critic_enabled
    ) and not config.resolution_candidate_generation_enabled:
        raise ValueError(
            "MEMORY_RESOLUTION_CANDIDATE_GENERATION_ENABLED=1 is required when "
            "fuzzy, cross-language, or cluster-critic ER flags are enabled"
        )
    if config.resolution_fuzzy_min_trigram < 0 or config.resolution_fuzzy_min_trigram > 1:
        raise ValueError("memory resolution fuzzy min trigram must be between 0 and 1")
    if config.resolution_max_candidates < 1:
        raise ValueError("memory resolution max candidates must be >= 1")
    if config.graph_scan_interval_seconds <= 0:
        raise ValueError("memory graph scan interval must be > 0")
    if config.graph_scan_batch_size < 1:
        raise ValueError("memory graph scan batch size must be >= 1")

    pipeline_stages = (
        config.extraction_enabled
        or config.verification_enabled
        or config.resolution_enabled
    )
    if pipeline_stages and not config.worker_enabled:
        raise ValueError(
            "MEMORY_WORKER_ENABLED=1 is required when extraction, verification, "
            "or resolution is enabled (jobs will not drain otherwise)"
        )
    if config.resolution_enabled and not config.verification_enabled:
        raise ValueError(
            "MEMORY_VERIFICATION_ENABLED=1 is required when resolution is enabled"
        )
    if (
        config.resolution_enabled
        and config.verification_policy_version.strip()
        != config.required_verification_policy_version.strip()
    ):
        raise ValueError(
            "MEMORY_VERIFICATION_POLICY_VERSION must match "
            "MEMORY_REQUIRED_VERIFICATION_POLICY_VERSION when resolution is enabled "
            f"(got {config.verification_policy_version!r} vs "
            f"{config.required_verification_policy_version!r})"
        )
    if config.graph_enabled and not config.resolution_enabled:
        raise ValueError(
            "MEMORY_RESOLUTION_ENABLED=1 is required when graph is enabled "
            "(graph projects belief heads from resolution)"
        )
    if config.shadow_retrieval_timeout_seconds <= 0:
        raise ValueError("memory shadow retrieval timeout must be > 0")
    if config.shadow_retrieval_token_budget < 256:
        raise ValueError("memory shadow retrieval token budget must be >= 256")
    if config.shadow_retrieval_max_beliefs < 1:
        raise ValueError("memory shadow retrieval max beliefs must be >= 1")
    if config.shadow_retrieval_max_hops < 1 or config.shadow_retrieval_max_hops > 5:
        raise ValueError("memory shadow retrieval max hops must be 1..5")
    if config.shadow_retrieval_enabled and not (
        config.resolution_enabled or config.graph_enabled
    ):
        raise ValueError(
            "MEMORY_RESOLUTION_ENABLED=1 or MEMORY_GRAPH_ENABLED=1 is required "
            "when shadow retrieval is enabled"
        )
    if config.documents_enabled and not config.worker_enabled:
        raise ValueError(
            "MEMORY_WORKER_ENABLED=1 is required when documents are enabled "
            "(structure jobs will not drain otherwise)"
        )
    profiles = {"agent", "summarize", "checker", "extraction"}
    if config.summaries_enabled and not config.graph_enabled:
        raise ValueError(
            "MEMORY_GRAPH_ENABLED=1 is required when summaries are enabled"
        )
    if config.summaries_enabled and not config.worker_enabled:
        raise ValueError(
            "MEMORY_WORKER_ENABLED=1 is required when summaries are enabled"
        )
    if config.summaries_generation_enabled and not config.summaries_enabled:
        raise ValueError(
            "MEMORY_SUMMARIES_ENABLED=1 is required when summary generation is enabled"
        )
    if (
        config.summaries_enabled
        and config.summaries_verify_enabled
        and not config.summaries_generation_enabled
    ):
        raise ValueError(
            "MEMORY_SUMMARIES_GENERATION_ENABLED=1 is required when summary "
            "verification is enabled"
        )
    if config.summaries_communities_enabled and not config.summaries_enabled:
        raise ValueError(
            "MEMORY_SUMMARIES_ENABLED=1 is required when communities are enabled"
        )
    if config.summaries_shadow_pack_enabled and not config.summaries_enabled:
        raise ValueError(
            "MEMORY_SUMMARIES_ENABLED=1 is required when summary shadow pack is enabled"
        )
    if config.summaries_shadow_pack_enabled and not config.shadow_retrieval_enabled:
        raise ValueError(
            "MEMORY_SHADOW_RETRIEVAL_ENABLED=1 is required when summary shadow "
            "pack is enabled"
        )
    if config.summaries_scan_interval_seconds <= 0:
        raise ValueError("memory summaries scan interval must be > 0")
    if config.summaries_scan_batch_size < 1:
        raise ValueError("memory summaries scan batch size must be >= 1")
    if config.summaries_debounce_seconds < 0:
        raise ValueError("memory summaries debounce seconds must be >= 0")
    if config.summaries_full_rebuild_every_n < 1:
        raise ValueError("memory summaries full rebuild every N must be >= 1")
    if config.summaries_model_profile not in profiles:
        raise ValueError("invalid memory summaries model profile")
    if config.summaries_verify_model_profile not in profiles:
        raise ValueError("invalid memory summaries verify model profile")
    if config.summaries_max_tokens < 256:
        raise ValueError("memory summaries max tokens must be >= 256")
    if config.attachment_enabled and not config.graph_enabled:
        raise ValueError(
            "MEMORY_GRAPH_ENABLED=1 is required when attachment is enabled"
        )
    if config.attachment_enabled and not config.worker_enabled:
        raise ValueError(
            "MEMORY_WORKER_ENABLED=1 is required when attachment is enabled"
        )
    if config.attachment_enabled and not config.resolution_enabled:
        raise ValueError(
            "MEMORY_RESOLUTION_ENABLED=1 is required when attachment is enabled"
        )
    if config.attachment_generation_enabled and not config.attachment_enabled:
        raise ValueError(
            "MEMORY_ATTACHMENT_ENABLED=1 is required when attachment generation is enabled"
        )
    if (
        config.attachment_enabled
        and config.attachment_verify_enabled
        and not config.attachment_generation_enabled
    ):
        raise ValueError(
            "MEMORY_ATTACHMENT_GENERATION_ENABLED=1 is required when attachment "
            "verification is enabled"
        )
    if (
        config.attachment_enabled
        and config.attachment_inferred_preference_enabled
        and not config.attachment_generation_enabled
    ):
        raise ValueError(
            "MEMORY_ATTACHMENT_GENERATION_ENABLED=1 is required when inferred "
            "preference attachment is enabled"
        )
    if config.attachment_scan_interval_seconds <= 0:
        raise ValueError("memory attachment scan interval must be > 0")
    if config.attachment_scan_batch_size < 1:
        raise ValueError("memory attachment scan batch size must be >= 1")
    if config.attachment_debounce_seconds < 0:
        raise ValueError("memory attachment debounce seconds must be >= 0")
    if config.attachment_max_candidates < 1:
        raise ValueError("memory attachment max candidates must be >= 1")
    if config.attachment_max_llm_calls < 0:
        raise ValueError("memory attachment max llm calls must be >= 0")
    profiles = {"agent", "summarize", "checker", "extraction"}
    if config.attachment_model_profile not in profiles:
        raise ValueError("invalid memory attachment model profile")
    if config.attachment_support_model_profile not in profiles:
        raise ValueError("invalid memory attachment support model profile")
    if config.attachment_adversarial_model_profile not in profiles:
        raise ValueError("invalid memory attachment adversarial model profile")
    if config.attachment_cluster_model_profile not in profiles:
        raise ValueError("invalid memory attachment cluster model profile")
    if config.attachment_max_tokens < 256:
        raise ValueError("memory attachment max tokens must be >= 256")
    if config.attachment_react_enabled and not config.attachment_enabled:
        raise ValueError("MEMORY_ATTACHMENT_ENABLED=1 is required when attachment ReAct is enabled")
    if config.attachment_react_mode not in {"shadow", "expand", "propose"}:
        raise ValueError("invalid memory attachment ReAct mode")
    if config.attachment_react_model_profile not in profiles:
        raise ValueError("invalid memory attachment ReAct model profile")
    if config.attachment_react_max_actions < 1 or config.attachment_react_max_actions > 20:
        raise ValueError("memory attachment ReAct max actions must be 1..20")
    if config.attachment_react_max_hops < 1 or config.attachment_react_max_hops > 3:
        raise ValueError("memory attachment ReAct max hops must be 1..3")
    if config.attachment_react_max_results < 1 or config.attachment_react_max_results > 20:
        raise ValueError("memory attachment ReAct max results must be 1..20")
    if config.attachment_react_max_nodes < config.attachment_react_max_results:
        raise ValueError("memory attachment ReAct max nodes must cover max results")
    if config.attachment_react_max_tokens < 256:
        raise ValueError("memory attachment ReAct max tokens must be >= 256")
