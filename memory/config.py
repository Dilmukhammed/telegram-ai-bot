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
    extraction_model_profile: str = "summarize"
    extraction_max_tokens: int = 4096


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
    if config.extraction_model_profile not in {"agent", "summarize", "checker"}:
        raise ValueError("memory extraction model profile must be agent, summarize, or checker")
    if config.extraction_max_tokens < 256:
        raise ValueError("memory extraction max tokens must be >= 256")
