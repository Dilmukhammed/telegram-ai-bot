from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from memory.ids import canonical_json
from memory.verification.schemas import (
    CandidateScoreInput,
    CandidateStatusUpdate,
    VerificationVerdict,
    VerificationVerdictInput,
    VerifierRole,
)


DEFAULT_POLICY_VERSION = "verification_policy_v1"

_AUTHORITY_SCORES = {
    "authoritative_api_result": 1.0,
    "tool_api_result": 0.95,
    "user_direct_statement": 0.9,
    "user_supplied_document": 0.8,
    "model_visual_observation": 0.45,
    "assistant_generated_text": 0.1,
}


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    score: CandidateScoreInput
    update: CandidateStatusUpdate


def score_and_route(
    candidate: Mapping[str, Any],
    verdicts: Sequence[VerificationVerdictInput],
    *,
    policy_version: str = DEFAULT_POLICY_VERSION,
) -> RoutingDecision:
    by_role = {item.role: item for item in verdicts}
    deterministic = by_role.get(VerifierRole.DETERMINISTIC)
    support = by_role.get(VerifierRole.SUPPORT)
    adversarial = by_role.get(VerifierRole.ADVERSARIAL)
    if deterministic is None:
        raise ValueError("deterministic verdict is required")

    route_status: str
    if deterministic.verdict is VerificationVerdict.MALFORMED:
        route_status = "rejected"
    elif support is None:
        raise ValueError("support verdict is required after deterministic success")
    elif support.verdict is VerificationVerdict.MALFORMED:
        route_status = "rejected"
    elif support.verdict is VerificationVerdict.CONTRADICTED:
        route_status = "contradicted"
    elif support.verdict is VerificationVerdict.INSUFFICIENT:
        route_status = "insufficient"
    elif adversarial is not None and adversarial.verdict is VerificationVerdict.CONTRADICTED:
        route_status = "contradicted"
    elif adversarial is not None and adversarial.verdict in {
        VerificationVerdict.INSUFFICIENT,
        VerificationVerdict.MALFORMED,
    }:
        route_status = "needs_confirmation"
    else:
        route_status = "ready_for_resolution"

    evidence = candidate.get("evidence") or ()
    authorities = {
        str(item.get("authority_class", ""))
        for item in evidence
        if isinstance(item, Mapping)
    }
    source_authority = max((_AUTHORITY_SCORES.get(item, 0.0) for item in authorities), default=0.0)
    ambiguity_count = sum(len(item.ambiguities) + len(item.missing_context) for item in verdicts)
    model_verdicts = [
        item
        for item in verdicts
        if item.role in {VerifierRole.SUPPORT, VerifierRole.ADVERSARIAL}
    ]
    supported_count = sum(
        item.verdict is VerificationVerdict.SUPPORTED for item in model_verdicts
    )
    model_verdict_count = len(model_verdicts)
    components = {
        "extractor_agreement": None,
        "verifier_support": (
            supported_count / model_verdict_count if model_verdict_count else 0.0
        ),
        "source_authority": source_authority,
        "evidence_directness": _directness_score(verdicts),
        "temporal_specificity": 1.0 if candidate.get("temporal") else 0.0,
        "argument_completeness": 1.0,
        "ambiguity_penalty": min(1.0, ambiguity_count * 0.25),
        "cross_modal_agreement": None,
        "contradiction_signal": any(
            item.verdict is VerificationVerdict.CONTRADICTED for item in verdicts
        ),
        "verifier_roles": [item.role.value for item in verdicts],
    }
    verdict_payload = [
        {
            "role": item.role.value,
            "verdict": item.verdict.value,
            "directness": item.evidence_directness.value if item.evidence_directness else None,
            "scope_errors": list(item.scope_errors),
            "ambiguities": list(item.ambiguities),
            "missing_context": list(item.missing_context),
            "input_hash": item.input_hash,
        }
        for item in sorted(verdicts, key=lambda value: value.role.value)
    ]
    verdict_set_hash = hashlib.sha256(
        canonical_json(verdict_payload).encode("utf-8")
    ).hexdigest()
    candidate_id = str(candidate["candidate_id"])
    return RoutingDecision(
        score=CandidateScoreInput(
            candidate_id=candidate_id,
            policy_version=policy_version,
            verdict_set_hash=verdict_set_hash,
            components=components,
            route_status=route_status,
        ),
        update=CandidateStatusUpdate(
            candidate_id=candidate_id,
            from_statuses=("proposed", "needs_confirmation"),
            to_status=route_status,
            acceptance_policy=policy_version,
        ),
    )


def _directness_score(verdicts: Sequence[VerificationVerdictInput]) -> float:
    scores = {
        "direct": 1.0,
        "indirect": 0.6,
        "inferred": 0.25,
    }
    values = [
        scores[item.evidence_directness.value]
        for item in verdicts
        if item.evidence_directness is not None
    ]
    return min(values) if values else 0.0
