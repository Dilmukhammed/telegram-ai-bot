from __future__ import annotations

import hashlib

from memory.ids import canonical_json
from memory.models import JobRequest
from memory.summaries.schemas import (
    GENERATOR_NAME,
    GENERATOR_VERSION,
    SUMMARY_PROMPT_VERSION,
)

SUMMARY_GENERATE_STAGE = "summary_generate"


def encode_summary_target(*, summary_type: str, target_id: str) -> str:
    return f"{summary_type}|{target_id}"


def decode_summary_target(target_id: str) -> tuple[str, str]:
    if "|" not in target_id:
        raise ValueError(f"invalid summary target: {target_id!r}")
    summary_type, raw_target = target_id.split("|", 1)
    if not summary_type or not raw_target:
        raise ValueError(f"invalid summary target: {target_id!r}")
    return summary_type, raw_target


def summary_job_input_hash(
    *,
    user_id: int,
    summary_type: str,
    target_id: str,
    input_hash: str,
    generation_enabled: bool,
    verify_enabled: bool,
    model_profile: str,
    verify_model_profile: str,
) -> str:
    payload = {
        "user_id": user_id,
        "summary_type": summary_type,
        "target_id": target_id,
        "belief_input_hash": input_hash,
        "generator_name": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "prompt_version": SUMMARY_PROMPT_VERSION,
        "generation_enabled": generation_enabled,
        "verify_enabled": verify_enabled,
        "model_profile": model_profile,
        "verify_model_profile": verify_model_profile,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def summary_job_request(
    *,
    user_id: int,
    summary_type: str,
    target_id: str,
    input_hash: str,
    generation_enabled: bool,
    verify_enabled: bool,
    model_profile: str,
    verify_model_profile: str,
) -> JobRequest:
    encoded = encode_summary_target(summary_type=summary_type, target_id=target_id)
    job_input_hash = summary_job_input_hash(
        user_id=user_id,
        summary_type=summary_type,
        target_id=target_id,
        input_hash=input_hash,
        generation_enabled=generation_enabled,
        verify_enabled=verify_enabled,
        model_profile=model_profile,
        verify_model_profile=verify_model_profile,
    )
    config_hash = hashlib.sha256(
        canonical_json(
            {
                "generation_enabled": generation_enabled,
                "verify_enabled": verify_enabled,
                "model_profile": model_profile,
                "verify_model_profile": verify_model_profile,
            }
        ).encode("utf-8")
    ).hexdigest()[:16]
    return JobRequest(
        stage=SUMMARY_GENERATE_STAGE,
        processor_name=GENERATOR_NAME,
        processor_version=GENERATOR_VERSION,
        prompt_version=SUMMARY_PROMPT_VERSION,
        model_profile=model_profile,
        input_hash=job_input_hash,
        config_hash=config_hash,
        target_kind="summary",
        target_id=encoded,
    )
