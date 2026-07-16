from __future__ import annotations

import hashlib

from memory.ids import canonical_json
from memory.models import JobRequest
from memory.attachment.schemas import (
    ATTACHMENT_PROMPT_VERSION,
    ATTACHMENT_VERSION,
    PROCESSOR_NAME,
    PROCESSOR_VERSION,
)

ATTACH_ANALYZE_STAGE = "attach_analyze"


def attach_job_input_hash(
    *,
    user_id: int,
    belief_id: str,
    generation_enabled: bool,
    verify_enabled: bool,
    model_profile: str,
    react_enabled: bool = False,
    react_mode: str = "shadow",
    react_model_profile: str = "agent",
) -> str:
    payload = {
        "user_id": user_id,
        "belief_id": belief_id,
        "processor_name": PROCESSOR_NAME,
        "processor_version": PROCESSOR_VERSION,
        "prompt_version": ATTACHMENT_PROMPT_VERSION,
        "attachment_version": ATTACHMENT_VERSION,
        "generation_enabled": generation_enabled,
        "verify_enabled": verify_enabled,
        "model_profile": model_profile,
        "react_enabled": react_enabled,
        "react_mode": react_mode,
        "react_model_profile": react_model_profile,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def attach_job_request(
    *,
    user_id: int,
    belief_id: str,
    generation_enabled: bool,
    verify_enabled: bool,
    model_profile: str,
    react_enabled: bool = False,
    react_mode: str = "shadow",
    react_model_profile: str = "agent",
) -> JobRequest:
    job_input_hash = attach_job_input_hash(
        user_id=user_id,
        belief_id=belief_id,
        generation_enabled=generation_enabled,
        verify_enabled=verify_enabled,
        model_profile=model_profile,
        react_enabled=react_enabled,
        react_mode=react_mode,
        react_model_profile=react_model_profile,
    )
    config_hash = hashlib.sha256(
        canonical_json(
            {
                "generation_enabled": generation_enabled,
                "verify_enabled": verify_enabled,
                "model_profile": model_profile,
                "attachment_version": ATTACHMENT_VERSION,
                "react_enabled": react_enabled,
                "react_mode": react_mode,
                "react_model_profile": react_model_profile,
            }
        ).encode("utf-8")
    ).hexdigest()[:16]
    return JobRequest(
        stage=ATTACH_ANALYZE_STAGE,
        processor_name=PROCESSOR_NAME,
        processor_version=PROCESSOR_VERSION,
        prompt_version=ATTACHMENT_PROMPT_VERSION,
        model_profile=model_profile,
        input_hash=job_input_hash,
        config_hash=config_hash,
        target_kind="belief",
        target_id=belief_id,
    )
