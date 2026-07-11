from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from memory.extraction.generation import ModelGeneration
from memory.ids import canonical_json
from memory.models import ProcessorContext, ProcessorOutput
from memory.structured_output import StructuredOutputModel
from memory.verification.adversarial import requires_adversarial_verification
from memory.verification.jobs import (
    CANDIDATE_VERIFY_STAGE,
    VERIFICATION_PROMPT_VERSION,
    VERIFIER_NAME,
    VERIFIER_VERSION,
    verification_input_hash,
    verification_payload_hash,
)
from memory.verification.json_schema import verification_output_schema
from memory.verification.parser import VerificationParseError, parse_verification_output
from memory.verification.prompts import build_adversarial_messages, build_support_messages
from memory.verification.schemas import (
    EvidenceDirectness,
    ParsedVerdict,
    VerificationVerdict,
    VerificationVerdictInput,
    VerifierRole,
)
from memory.verification.scoring import DEFAULT_POLICY_VERSION, score_and_route
from memory.verification.support import (
    candidate_view,
    deterministic_exact_tool_support,
    deterministic_preflight,
)

if TYPE_CHECKING:
    from memory.processors import ProcessorRegistry
    from memory.service import MemoryService


@runtime_checkable
class VerificationModel(Protocol):
    model_profile: str

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = "verification",
    ) -> str: ...


class LLMVerificationModel:
    def __init__(self, client: Any, *, model_profile: str, max_tokens: int = 2048) -> None:
        self._transport = StructuredOutputModel(
            client,
            model_profile=model_profile,
            max_tokens=max_tokens,
        )
        self.model_profile = model_profile

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = "verification",
    ) -> str:
        generated = await self.generate_with_trace(
            messages,
            structured_schema=structured_schema,
        )
        return generated.text

    async def generate_with_trace(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = "verification",
    ) -> ModelGeneration:
        if structured_schema not in (None, "verification"):
            raise ValueError(f"unsupported verification schema: {structured_schema!r}")
        generated = await self._transport.generate(
            messages,
            schema_name=structured_schema,
            schema=verification_output_schema() if structured_schema else None,
        )
        return ModelGeneration(text=generated.text, metadata=generated.metadata)


class CandidateVerificationProcessor:
    name = VERIFIER_NAME
    version = VERIFIER_VERSION
    stages = frozenset({CANDIDATE_VERIFY_STAGE})

    def __init__(
        self,
        *,
        service: "MemoryService",
        support_model: VerificationModel,
        adversarial_model: VerificationModel,
        policy_version: str = DEFAULT_POLICY_VERSION,
        context_chars: int = 240,
    ) -> None:
        if context_chars < 0:
            raise ValueError("verification context_chars must be >= 0")
        self._service = service
        self._support_model = support_model
        self._adversarial_model = adversarial_model
        self._policy_version = policy_version
        self._context_chars = context_chars

    async def process(self, context: ProcessorContext) -> ProcessorOutput:
        job = context.job
        if job.prompt_version != VERIFICATION_PROMPT_VERSION:
            raise ValueError(
                f"unsupported verification prompt version: {job.prompt_version!r}"
            )
        if job.target_kind != "candidate" or not job.target_id:
            raise ValueError("candidate verification job requires candidate target")
        if job.model_profile != self._support_model.model_profile:
            raise ValueError(
                "verification support model profile does not match scheduled job"
            )
        candidate = self._service.verification.load_candidate(
            job.target_id,
            user_id=job.user_id,
        )
        if candidate is None:
            raise ValueError(f"unknown verification candidate: {job.target_id}")
        if candidate["primary_source_version_id"] != job.source_version_id:
            raise ValueError("verification candidate source version mismatch")
        if candidate["status"] in {"superseded", "invalidated"}:
            raise ValueError(
                f"candidate is no longer verifiable: {candidate['status']!r}"
            )
        actual_input_hash = verification_input_hash(
            job.target_id,
            policy_version=self._policy_version,
            adversarial_profile=self._adversarial_model.model_profile,
        )
        if actual_input_hash != job.input_hash:
            raise RuntimeError(
                "verification input hash mismatch: "
                f"expected {job.input_hash!r}, got {actual_input_hash!r}"
            )

        verdict_input_hash = verification_payload_hash(
            job.target_id,
            adversarial_profile=self._adversarial_model.model_profile,
        )
        verdicts = list(
            self._service.verification.load_verdict_inputs(
                candidate_id=job.target_id,
                user_id=job.user_id,
                verifier_version=VERIFIER_VERSION,
                prompt_version=VERIFICATION_PROMPT_VERSION,
                input_hash=verdict_input_hash,
            )
        )
        view = candidate_view(candidate, context_chars=self._context_chars)
        deterministic = next(
            (item for item in verdicts if item.role is VerifierRole.DETERMINISTIC),
            None,
        )
        support = next(
            (item for item in verdicts if item.role is VerifierRole.SUPPORT),
            None,
        )
        if deterministic is None:
            preflight_errors = deterministic_preflight(candidate)
            deterministic = VerificationVerdictInput(
                candidate_id=job.target_id,
                role=VerifierRole.DETERMINISTIC,
                verdict=(
                    VerificationVerdict.MALFORMED
                    if preflight_errors
                    else VerificationVerdict.SUPPORTED
                ),
                evidence_directness=(
                    None if preflight_errors else EvidenceDirectness.DIRECT
                ),
                scope_errors=preflight_errors,
                ambiguities=(),
                missing_context=(),
                verifier_name=f"{VERIFIER_NAME}_preflight",
                verifier_version=VERIFIER_VERSION,
                prompt_version=VERIFICATION_PROMPT_VERSION,
                model_profile=None,
                model_name=None,
                input_hash=verdict_input_hash,
                raw_output={
                    "verdict": "malformed" if preflight_errors else "supported",
                    "scope_errors": list(preflight_errors),
                    "rule_based": True,
                },
            )
            verdicts.append(deterministic)
        if (
            deterministic.verdict is not VerificationVerdict.MALFORMED
            and support is None
        ):
            if deterministic_exact_tool_support(candidate):
                support = VerificationVerdictInput(
                    candidate_id=job.target_id,
                    role=VerifierRole.SUPPORT,
                    verdict=VerificationVerdict.SUPPORTED,
                    evidence_directness=EvidenceDirectness.DIRECT,
                    scope_errors=(),
                    ambiguities=(),
                    missing_context=(),
                    verifier_name=f"{VERIFIER_NAME}_exact_tool",
                    verifier_version=VERIFIER_VERSION,
                    prompt_version=VERIFICATION_PROMPT_VERSION,
                    model_profile=None,
                    model_name=None,
                    input_hash=verdict_input_hash,
                    raw_output={
                        "verdict": "supported",
                        "scope_errors": [],
                        "rule_based": True,
                        "rule": "exact_tool_task",
                    },
                )
            else:
                support = await _run_verifier(
                    self._support_model,
                    role=VerifierRole.SUPPORT,
                    candidate_id=job.target_id,
                    messages=build_support_messages(view),
                    input_hash=verdict_input_hash,
                )
            verdicts.append(support)
        adversarial = next(
            (item for item in verdicts if item.role is VerifierRole.ADVERSARIAL),
            None,
        )
        if (
            support is not None
            and support.verdict is VerificationVerdict.SUPPORTED
            and requires_adversarial_verification(candidate)
            and adversarial is None
        ):
            adversarial = await _run_verifier(
                self._adversarial_model,
                role=VerifierRole.ADVERSARIAL,
                candidate_id=job.target_id,
                messages=build_adversarial_messages(
                    view,
                    support_verdict=_verdict_payload(support),
                ),
                input_hash=verdict_input_hash,
            )
            verdicts.append(adversarial)

        routing = score_and_route(
            candidate,
            verdicts,
            policy_version=self._policy_version,
        )
        routing = replace(
            routing,
            update=replace(
                routing.update,
                from_statuses=(str(candidate["status"]),),
            ),
        )
        output_payload = {
            "schema_version": "1",
            "candidate_id": job.target_id,
            "verdicts": [_verdict_payload(item) for item in verdicts],
            "policy_version": self._policy_version,
            "route_status": routing.update.to_status,
            "components": dict(routing.score.components),
        }
        output_hash = hashlib.sha256(
            canonical_json(output_payload).encode("utf-8")
        ).hexdigest()
        return ProcessorOutput(
            output_hash=output_hash,
            output_json=output_payload,
            new_verdicts=tuple(verdicts),
            new_candidate_scores=(routing.score,),
            candidate_updates=(routing.update,),
        )


async def _run_verifier(
    model: VerificationModel,
    *,
    role: VerifierRole,
    candidate_id: str,
    messages: list[dict[str, str]],
    input_hash: str,
) -> VerificationVerdictInput:
    generated = await _model_generate(model, messages)
    raw = generated.text
    try:
        parsed = parse_verification_output(raw)
        repair_metadata: dict[str, Any] | None = None
    except VerificationParseError as first_error:
        repair_messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "The strict verifier parser rejected the JSON: "
                    f"{first_error}. Return the complete corrected JSON object only."
                ),
            },
        ]
        repaired = await _model_generate(model, repair_messages)
        parsed = parse_verification_output(repaired.text)
        raw = repaired.text
        repair_metadata = dict(repaired.metadata)
    return _verdict_input(
        candidate_id=candidate_id,
        role=role,
        parsed=parsed,
        model=model,
        input_hash=input_hash,
        raw=raw,
        generation_metadata=dict(generated.metadata),
        repair_metadata=repair_metadata,
    )


async def _model_generate(
    model: VerificationModel,
    messages: list[dict[str, str]],
) -> ModelGeneration:
    generate_with_trace = getattr(model, "generate_with_trace", None)
    if callable(generate_with_trace):
        generated = await generate_with_trace(
            messages,
            structured_schema="verification",
        )
        if isinstance(generated, ModelGeneration):
            return generated
    text = await model.generate(messages, structured_schema="verification")
    return ModelGeneration(
        text=text,
        metadata={
            "model_profile": getattr(model, "model_profile", None),
            "model": None,
            "response_format": "unknown",
        },
    )


def _verdict_input(
    *,
    candidate_id: str,
    role: VerifierRole,
    parsed: ParsedVerdict,
    model: VerificationModel,
    input_hash: str,
    raw: str,
    generation_metadata: dict[str, Any],
    repair_metadata: dict[str, Any] | None,
) -> VerificationVerdictInput:
    return VerificationVerdictInput(
        candidate_id=candidate_id,
        role=role,
        verdict=parsed.verdict,
        evidence_directness=parsed.evidence_directness,
        scope_errors=parsed.scope_errors,
        ambiguities=parsed.ambiguities,
        missing_context=parsed.missing_context,
        verifier_name=VERIFIER_NAME,
        verifier_version=VERIFIER_VERSION,
        prompt_version=VERIFICATION_PROMPT_VERSION,
        model_profile=str(
            generation_metadata.get("model_profile")
            or getattr(model, "model_profile", "")
        ),
        model_name=(
            str(generation_metadata["model"])
            if generation_metadata.get("model")
            else None
        ),
        input_hash=input_hash,
        raw_output={
            **_parsed_payload(parsed),
            "raw_response": raw,
            "generation": generation_metadata,
            "repair": repair_metadata,
        },
    )


def _parsed_payload(parsed: ParsedVerdict) -> dict[str, Any]:
    return {
        "schema_version": parsed.schema_version,
        "verdict": parsed.verdict.value,
        "evidence_directness": (
            parsed.evidence_directness.value if parsed.evidence_directness else None
        ),
        "scope_errors": list(parsed.scope_errors),
        "ambiguities": list(parsed.ambiguities),
        "missing_context": list(parsed.missing_context),
        "corrected_candidate": None,
    }


def _verdict_payload(item: VerificationVerdictInput) -> dict[str, Any]:
    return {
        "role": item.role.value,
        "verdict": item.verdict.value,
        "evidence_directness": (
            item.evidence_directness.value if item.evidence_directness else None
        ),
        "scope_errors": list(item.scope_errors),
        "ambiguities": list(item.ambiguities),
        "missing_context": list(item.missing_context),
        "model_profile": item.model_profile,
        "model_name": item.model_name,
    }


def register_candidate_verifier(
    registry: "ProcessorRegistry",
    *,
    service: "MemoryService",
    support_model: VerificationModel,
    adversarial_model: VerificationModel,
    policy_version: str = DEFAULT_POLICY_VERSION,
    context_chars: int = 240,
) -> CandidateVerificationProcessor:
    processor = CandidateVerificationProcessor(
        service=service,
        support_model=support_model,
        adversarial_model=adversarial_model,
        policy_version=policy_version,
        context_chars=context_chars,
    )
    registry.register(processor)
    return processor
