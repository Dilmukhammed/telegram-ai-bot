from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Any, Protocol, Sequence, runtime_checkable

from memory.extraction.candidates import CandidateEvidenceInput, CandidateInput
from memory.extraction.mentions import MentionInput
from memory.extraction.parser import parse_extraction_output
from memory.extraction.prompts import PROMPT_VERSION, build_extraction_messages
from memory.extraction.schemas import CandidateDraft, ExtractionResult, MentionDraft, thaw_json
from memory.ids import canonical_json
from memory.models import JobRequest, MemorySegment, ProcessorContext, ProcessorOutput
from memory.pointers import POINTER_VERSION, EvidencePointer

if TYPE_CHECKING:
    from memory.processors import ProcessorRegistry
    from memory.service import MemoryService


CANDIDATE_EXTRACT_STAGE = "candidate_extract"
TEXT_EXTRACTOR_NAME = "text_candidate_extractor"
TEXT_EXTRACTOR_VERSION = "1"
SUPPORTED_SEGMENT_TYPES = frozenset({"chat_text", "tool_payload"})
ALLOWED_CANDIDATE_AUTHORITIES = frozenset(
    {
        "user_direct_statement",
        "tool_api_result",
        "authoritative_api_result",
    }
)


@runtime_checkable
class ExtractionModel(Protocol):
    model_profile: str

    async def generate(self, messages: list[dict[str, str]]) -> str: ...


class LLMExtractionModel:
    """Small adapter around the repository LLM client; construction is opt-in."""

    def __init__(self, client: Any, *, model_profile: str, max_tokens: int = 4096) -> None:
        if not model_profile.strip():
            raise ValueError("model_profile must be non-empty")
        if max_tokens < 256:
            raise ValueError("max_tokens must be >= 256")
        self._client = client
        self.model_profile = model_profile
        self._max_tokens = max_tokens

    async def generate(self, messages: list[dict[str, str]]) -> str:
        return await self._client.chat_without_reasoning(
            messages,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
        )


class TextExtractionProcessor:
    name = TEXT_EXTRACTOR_NAME
    version = TEXT_EXTRACTOR_VERSION
    stages = frozenset({CANDIDATE_EXTRACT_STAGE})

    def __init__(
        self,
        *,
        service: "MemoryService",
        model: ExtractionModel,
        timezone: str,
    ) -> None:
        if not timezone.strip():
            raise ValueError("timezone must be non-empty")
        self._service = service
        self._model = model
        self._timezone = timezone

    async def process(self, context: ProcessorContext) -> ProcessorOutput:
        if context.job.prompt_version != PROMPT_VERSION:
            raise ValueError(
                f"unsupported extraction prompt version: {context.job.prompt_version!r}"
            )
        segments = await asyncio.to_thread(
            self._service.segments.list_for_source_version,
            context.source_version.source_version_id,
            user_id=context.job.user_id,
        )
        selected = tuple(
            segment
            for segment in segments
            if segment.segment_type in SUPPORTED_SEGMENT_TYPES and segment.text
        )
        actual_input_hash = normalized_segments_hash(selected)
        if actual_input_hash != context.job.input_hash:
            raise RuntimeError(
                "normalized segment hash changed before extraction: "
                f"expected {context.job.input_hash!r}, got {actual_input_hash!r}"
            )

        # Assistant prose is derived text and is not primary evidence for personal facts.
        # PR 3 safely abstains instead of relying on a prompt-only policy.
        if context.source.authority_class not in ALLOWED_CANDIDATE_AUTHORITIES:
            return ProcessorOutput(
                output_hash=_hash_payload([]),
                output_json={
                    "schema_version": "1",
                    "source_version_id": context.source_version.source_version_id,
                    "segment_count": len(selected),
                    "mention_count": 0,
                    "candidate_count": 0,
                    "abstained": True,
                    "reason": "source_authority_forbids_candidates",
                },
            )

        mention_inputs: list[MentionInput] = []
        candidate_inputs: list[CandidateInput] = []
        result_payloads: list[dict[str, Any]] = []
        for segment in selected:
            messages = build_extraction_messages(
                segment_text=segment.text or "",
                source_type=context.source.source_type,
                authority_class=context.source.authority_class,
                occurred_at=(
                    context.source_version.occurred_at.isoformat()
                    if context.source_version.occurred_at is not None
                    else None
                ),
                timezone=self._timezone,
            )
            raw = await self._model.generate(messages)
            result = parse_extraction_output(
                raw,
                segment_text=segment.text or "",
                allow_candidates=True,
            )
            result_payloads.append(
                {"segment_id": segment.segment_id, "result": extraction_result_to_mapping(result)}
            )
            mention_inputs.extend(
                _mention_input(context, segment, mention)
                for mention in result.mentions
            )
            candidate_inputs.extend(
                _candidate_input(context, segment, candidate)
                for candidate in result.candidates
            )

        return ProcessorOutput(
            output_hash=_hash_payload(result_payloads),
            output_json={
                "schema_version": "1",
                "source_version_id": context.source_version.source_version_id,
                "segment_count": len(selected),
                "mention_count": len(mention_inputs),
                "candidate_count": len(candidate_inputs),
                "abstained": not candidate_inputs,
                "segments": result_payloads,
            },
            new_mentions=tuple(mention_inputs),
            new_candidates=tuple(candidate_inputs),
        )


def extraction_job_request(
    input_hash: str,
    *,
    model_profile: str,
    config_hash: str = "",
) -> JobRequest:
    return JobRequest(
        stage=CANDIDATE_EXTRACT_STAGE,
        processor_name=TEXT_EXTRACTOR_NAME,
        processor_version=TEXT_EXTRACTOR_VERSION,
        prompt_version=PROMPT_VERSION,
        model_profile=model_profile,
        input_hash=input_hash,
        config_hash=config_hash,
    )


def register_text_extractor(
    registry: "ProcessorRegistry",
    *,
    service: "MemoryService",
    model: ExtractionModel,
    timezone: str,
) -> TextExtractionProcessor:
    processor = TextExtractionProcessor(service=service, model=model, timezone=timezone)
    registry.register(processor)
    return processor


def normalized_segments_hash(segments: Sequence[MemorySegment]) -> str:
    payload = canonical_json(
        [
            {
                "segment_type": segment.segment_type,
                "ordinal": segment.ordinal,
                "input_hash": segment.input_hash,
            }
            for segment in segments
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _mention_input(
    context: ProcessorContext,
    segment: MemorySegment,
    mention: MentionDraft,
) -> MentionInput:
    return MentionInput(
        local_ref=mention.mention_ref,
        segment_id=segment.segment_id,
        mention_type=mention.mention_type.value,
        surface_text=mention.surface_text,
        normalized_hint=mention.normalized_hint,
        pointer=_span_pointer(segment.pointer, mention.char_start, mention.char_end),
        extractor_name=TEXT_EXTRACTOR_NAME,
        extractor_version=TEXT_EXTRACTOR_VERSION,
        prompt_version=context.job.prompt_version or PROMPT_VERSION,
    )


def _candidate_input(
    context: ProcessorContext,
    segment: MemorySegment,
    candidate: CandidateDraft,
) -> CandidateInput:
    evidence = tuple(
        CandidateEvidenceInput(
            segment_id=segment.segment_id,
            relation=item.relation,
            pointer=_span_pointer(segment.pointer, item.char_start, item.char_end),
            exact_quote=item.exact_quote,
            context_pointer=segment.pointer,
        )
        for item in candidate.evidence
    )
    return CandidateInput(
        local_ref=candidate.candidate_ref,
        segment_id=segment.segment_id,
        kind=candidate.kind.value,
        schema_name=candidate.schema_name,
        schema_version=candidate.schema_version,
        arguments=candidate.arguments,
        attributes=candidate.attributes,
        polarity=candidate.polarity.value,
        epistemic=candidate.epistemic,
        temporal=candidate.temporal,
        status=candidate.status.value,
        evidence=evidence,
        canonical_hint=candidate.canonical_hint,
        extractor_name=TEXT_EXTRACTOR_NAME,
        extractor_version=TEXT_EXTRACTOR_VERSION,
        prompt_version=context.job.prompt_version or PROMPT_VERSION,
    )


def _span_pointer(pointer: EvidencePointer, start: int, end: int) -> EvidencePointer:
    location = dict(pointer.location)
    if pointer.kind in {"chat_message", "chat_span"}:
        base = int(location.get("char_start", 0))
        return EvidencePointer(
            pointer_version=POINTER_VERSION,
            kind="chat_span",
            source_version_id=pointer.source_version_id,
            location={
                "chat_message_id": int(location["chat_message_id"]),
                "char_start": base + start,
                "char_end": base + end,
            },
        )
    if pointer.kind == "tool_result":
        base = int(location.get("char_start", 0))
        return EvidencePointer(
            pointer_version=POINTER_VERSION,
            kind="tool_result",
            source_version_id=pointer.source_version_id,
            location={
                "tool_result_ref": str(location["tool_result_ref"]),
                "char_start": base + start,
                "char_end": base + end,
            },
        )
    raise ValueError(f"unsupported text evidence pointer kind: {pointer.kind!r}")


def extraction_result_to_mapping(result: ExtractionResult) -> dict[str, Any]:
    return {
        "schema_version": result.schema_version,
        "abstain": result.abstain,
        "mentions": [
            {
                "mention_ref": item.mention_ref,
                "mention_type": item.mention_type.value,
                "surface_text": item.surface_text,
                "char_start": item.char_start,
                "char_end": item.char_end,
                "normalized_hint": item.normalized_hint,
            }
            for item in result.mentions
        ],
        "candidates": [_candidate_to_mapping(item) for item in result.candidates],
    }


def _candidate_to_mapping(item: CandidateDraft) -> dict[str, Any]:
    arguments = []
    for argument in item.arguments:
        payload: dict[str, Any] = {"role": argument.role}
        if argument.mention_ref is not None:
            payload["mention_ref"] = argument.mention_ref
        else:
            payload["literal"] = thaw_json(argument.literal)
        arguments.append(payload)
    return {
        "candidate_ref": item.candidate_ref,
        "kind": item.kind.value,
        "schema_name": item.schema_name,
        "schema_version": item.schema_version,
        "arguments": arguments,
        "attributes": {str(k): thaw_json(v) for k, v in item.attributes.items()},
        "polarity": item.polarity.value,
        "epistemic": {
            "mode": item.epistemic.mode.value,
            "speaker_commitment": item.epistemic.speaker_commitment.value,
            "scope": item.epistemic.scope.value,
            "alternatives": [thaw_json(value) for value in item.epistemic.alternatives],
            "needs_confirmation": item.epistemic.needs_confirmation,
            "speaker_ref": item.epistemic.speaker_ref,
        },
        "temporal": (
            None
            if item.temporal is None
            else {
                "original_text": item.temporal.original_text,
                "valid_from": item.temporal.valid_from,
                "valid_to": item.temporal.valid_to,
                "event_time": item.temporal.event_time,
                "precision": item.temporal.precision,
                "timezone": item.temporal.timezone,
            }
        ),
        "status": item.status.value,
        "evidence": [
            {
                "relation": value.relation,
                "exact_quote": value.exact_quote,
                "char_start": value.char_start,
                "char_end": value.char_end,
            }
            for value in item.evidence
        ],
        "canonical_hint": item.canonical_hint,
    }


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
