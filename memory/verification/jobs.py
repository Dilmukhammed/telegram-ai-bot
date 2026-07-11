from __future__ import annotations

import hashlib

from memory.ids import canonical_json
from memory.models import JobRequest


CANDIDATE_VERIFY_STAGE = "candidate_verify"
VERIFIER_NAME = "independent_candidate_verifier"
VERIFIER_VERSION = "1"
VERIFICATION_PROMPT_VERSION = "candidate_verification_v3"


def verification_payload_hash(
    candidate_id: str,
    *,
    adversarial_profile: str,
) -> str:
    payload = canonical_json(
        {
            "candidate_id": candidate_id,
            "verifier_name": VERIFIER_NAME,
            "verifier_version": VERIFIER_VERSION,
            "prompt_version": VERIFICATION_PROMPT_VERSION,
            "adversarial_profile": adversarial_profile,
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verification_input_hash(
    candidate_id: str,
    *,
    policy_version: str,
    adversarial_profile: str,
) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "verification_payload_hash": verification_payload_hash(
                    candidate_id,
                    adversarial_profile=adversarial_profile,
                ),
                "policy_version": policy_version,
            }
        ).encode("utf-8")
    ).hexdigest()


def verification_job_request(
    candidate_id: str,
    *,
    model_profile: str,
    adversarial_profile: str,
    policy_version: str,
) -> JobRequest:
    input_hash = verification_input_hash(
        candidate_id,
        policy_version=policy_version,
        adversarial_profile=adversarial_profile,
    )
    config_hash = hashlib.sha256(
        canonical_json(
            {
                "support_profile": model_profile,
                "adversarial_profile": adversarial_profile,
                "policy_version": policy_version,
            }
        ).encode("utf-8")
    ).hexdigest()[:16]
    return JobRequest(
        stage=CANDIDATE_VERIFY_STAGE,
        processor_name=VERIFIER_NAME,
        processor_version=VERIFIER_VERSION,
        prompt_version=VERIFICATION_PROMPT_VERSION,
        model_profile=model_profile,
        input_hash=input_hash,
        config_hash=config_hash,
        target_kind="candidate",
        target_id=candidate_id,
    )
