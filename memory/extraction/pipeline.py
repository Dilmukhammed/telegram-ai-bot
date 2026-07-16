from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Any, Protocol, Sequence, runtime_checkable

from memory.extraction.candidates import CandidateEvidenceInput, CandidateInput
from memory.extraction.mentions import MentionInput
from memory.extraction.generation import ModelGeneration
from memory.extraction.prompts import PROMPT_VERSION
from memory.extraction.strategies import generate_segment_extraction_with_trace
from memory.extraction.schemas import (
    CandidateDraft,
    EvidenceSpan,
    ExtractionResult,
    MentionDraft,
    thaw_json,
)
from memory.ids import canonical_json
from memory.models import JobRequest, MemorySegment, ProcessorContext, ProcessorOutput
from memory.pointers import POINTER_VERSION, EvidencePointer
from memory.structured_output import StructuredOutputModel

if TYPE_CHECKING:
    from memory.processors import ProcessorRegistry
    from memory.service import MemoryService


CANDIDATE_EXTRACT_STAGE = "candidate_extract"
TEXT_EXTRACTOR_NAME = "text_candidate_extractor"
TEXT_EXTRACTOR_VERSION = "1"
SUPPORTED_SEGMENT_TYPES = frozenset(
    {
        "chat_text",
        "tool_payload",
        "document_paragraph",
        "document_heading",
        "document_table",
        "document_table_cell",
    }
)
ALLOWED_CANDIDATE_AUTHORITIES = frozenset(
    {
        "user_direct_statement",
        "tool_api_result",
        "authoritative_api_result",
        "user_supplied_document",
    }
)


@runtime_checkable
class ExtractionModel(Protocol):
    model_profile: str

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = "extraction",
    ) -> str: ...


class LLMExtractionModel:
    """Small adapter around the repository LLM client; construction is opt-in."""

    def __init__(self, client: Any, *, model_profile: str, max_tokens: int = 4096) -> None:
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
        structured_schema: str | None = "extraction",
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
        structured_schema: str | None = "extraction",
    ) -> ModelGeneration:
        from memory.extraction.json_schemas import extraction_output_schema

        if structured_schema not in (None, "extraction"):
            raise ValueError(f"unsupported extraction structured schema: {structured_schema!r}")
        generated = await self._transport.generate(
            messages,
            schema_name=structured_schema,
            schema=extraction_output_schema() if structured_schema is not None else None,
        )
        return ModelGeneration(text=generated.text, metadata=generated.metadata)


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
        semantic_payloads: list[dict[str, Any]] = []
        prior_segments: tuple[MemorySegment, ...] = ()
        if context.source_version.occurred_at is not None:
            prior_segments = tuple(
                await asyncio.to_thread(
                    self._service.segments.list_prior_chat_text_segments,
                    user_id=context.job.user_id,
                    before_occurred_at=context.source_version.occurred_at.isoformat(),
                    limit=3,
                )
            )
        for segment in selected:
            generated = await generate_segment_extraction_with_trace(
                self._model,
                segment_text=segment.text or "",
                source_type=context.source.source_type,
                authority_class=context.source.authority_class,
                occurred_at=(
                    context.source_version.occurred_at.isoformat()
                    if context.source_version.occurred_at is not None
                    else None
                ),
                timezone=self._timezone,
                prior_segments=[
                    {"segment_text": prior.text or ""}
                    for prior in prior_segments
                    if prior.text
                ],
            )
            parsed_result = generated.result
            result, postprocessor_trace = apply_segment_post_processors_with_trace(
                parsed_result,
                segment_text=segment.text or "",
                authority_class=context.source.authority_class,
                occurred_at=(
                    context.source_version.occurred_at.isoformat()
                    if context.source_version.occurred_at is not None
                    else None
                ),
                timezone=self._timezone,
                prior_segments=prior_segments,
            )
            semantic_payload = {
                "segment_id": segment.segment_id,
                "result": extraction_result_to_mapping(result),
            }
            semantic_payloads.append(semantic_payload)
            result_payloads.append(
                {
                    **semantic_payload,
                    "trace": {
                        "generation": generated.trace,
                        "parsed_result": extraction_result_to_mapping(parsed_result),
                        "postprocessors": postprocessor_trace,
                    },
                }
            )
            mention_inputs.extend(
                _mention_input(context, segment, mention)
                for mention in result.mentions
            )
            candidate_inputs.extend(
                _candidate_input(context, segment, candidate, prior_segments=prior_segments)
                for candidate in result.candidates
            )

        return ProcessorOutput(
            output_hash=_hash_payload(semantic_payloads),
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


def apply_segment_post_processors(
    result: ExtractionResult,
    *,
    segment_text: str,
    authority_class: str,
    occurred_at: str | None,
    timezone: str,
    prior_segments: Sequence[MemorySegment],
) -> ExtractionResult:
    processed, _ = apply_segment_post_processors_with_trace(
        result,
        segment_text=segment_text,
        authority_class=authority_class,
        occurred_at=occurred_at,
        timezone=timezone,
        prior_segments=prior_segments,
    )
    return processed


def apply_segment_post_processors_with_trace(
    result: ExtractionResult,
    *,
    segment_text: str,
    authority_class: str,
    occurred_at: str | None,
    timezone: str,
    prior_segments: Sequence[MemorySegment],
) -> tuple[ExtractionResult, list[dict[str, Any]]]:
    """Generic path: drop prior-only re-extracts, then temporal normalize."""
    del authority_class
    trace: list[dict[str, Any]] = []

    def record(name: str, before: ExtractionResult, after: ExtractionResult) -> ExtractionResult:
        changed = before != after
        item: dict[str, Any] = {"name": name, "changed": changed}
        if changed:
            item["result"] = extraction_result_to_mapping(after)
        trace.append(item)
        return after

    before = result
    result = _drop_prior_only_candidates(
        result,
        segment_text=segment_text,
        prior_segments=prior_segments,
    )
    result = record("drop_prior_only_candidates", before, result)

    before = result
    result = _ensure_explicit_correction_candidate(
        result,
        segment_text=segment_text,
        prior_segments=prior_segments,
    )
    result = record("ensure_explicit_correction_candidate", before, result)

    before = result
    result = _attach_correction_prior_support(
        result,
        segment_text=segment_text,
        prior_segments=prior_segments,
    )
    result = record("attach_correction_prior_support", before, result)

    before = result
    result = _normalize_explicit_temporal_cues(
        result,
        segment_text=segment_text,
        occurred_at=occurred_at,
        timezone=timezone,
    )
    result = record("normalize_explicit_temporal_cues", before, result)
    return result, trace


_CORRECTION_MARKERS = (
    "correction:",
    "correction -",
    "исправление:",
    "исправление -",
    "исправление —",
)


def _has_correction_marker(segment_text: str) -> bool:
    lower = segment_text.casefold()
    return any(marker in lower for marker in _CORRECTION_MARKERS)


def _ensure_explicit_correction_candidate(
    result: ExtractionResult,
    *,
    segment_text: str,
    prior_segments: Sequence[MemorySegment],
) -> ExtractionResult:
    """If the user explicitly marks a correction but the LLM skips it, synthesize one."""
    from memory.extraction.schemas import (
        CandidateArgument,
        CandidateStatus,
        Epistemic,
        EpistemicMode,
        EpistemicScope,
        Polarity,
        SpeakerCommitment,
    )

    if not _has_correction_marker(segment_text):
        return result
    if any(_looks_like_correction_draft(item) for item in result.candidates):
        return result
    # list_prior returns oldest→newest; attach to the most recent prior.
    usable_priors = [
        prior
        for prior in prior_segments
        if str(getattr(prior, "text", "") or "").strip()
    ]
    if not usable_priors:
        return result
    prior_text = str(usable_priors[-1].text or "").strip()
    if not segment_text:
        return result
    candidate = CandidateDraft(
        candidate_ref="c_auto_correction",
        kind="correction",
        schema_name="correction",
        schema_version="1",
        arguments=(
            CandidateArgument(role="old", literal=prior_text[:160], has_literal=True),
            CandidateArgument(role="new", literal=segment_text.strip()[:160], has_literal=True),
        ),
        attributes={},
        polarity=Polarity.POSITIVE,
        epistemic=Epistemic(
            mode=EpistemicMode.ASSERTED,
            speaker_commitment=SpeakerCommitment.CERTAIN,
            scope=EpistemicScope.PROPOSITION,
        ),
        temporal=None,
        status=CandidateStatus.PROPOSED,
        evidence=(
            EvidenceSpan(
                relation="corrects",
                exact_quote=segment_text,
                char_start=0,
                char_end=len(segment_text),
            ),
        ),
        canonical_hint=None,
    )
    return ExtractionResult(
        schema_version=result.schema_version,
        abstain=False,
        mentions=result.mentions,
        candidates=tuple((*result.candidates, candidate)),
    )

def _looks_like_correction_draft(candidate: CandidateDraft) -> bool:
    if "correct" in candidate.kind.casefold() or "correct" in candidate.schema_name.casefold():
        return True
    roles = {argument.role.casefold() for argument in candidate.arguments}
    if "old" in roles and "new" in roles:
        return True
    return any(evidence.relation == "corrects" for evidence in candidate.evidence)


def _attach_correction_prior_support(
    result: ExtractionResult,
    *,
    segment_text: str,
    prior_segments: Sequence[MemorySegment],
) -> ExtractionResult:
    """Attach supports evidence on the latest prior segment for correction candidates.

    Insert-time supersede requires supports on a segment other than the correction's
    own segment. The LLM only quotes the current segment; we deterministically link
    the most recent prior chat segment as the superseded support context.
    """
    # list_prior returns oldest→newest; supersede against the most recent prior.
    usable_priors = [
        prior
        for prior in prior_segments
        if str(getattr(prior, "text", "") or "").strip()
        and str(getattr(prior, "segment_id", "") or "").strip()
    ]
    if result.abstain or not result.candidates or not usable_priors:
        return result
    prior = usable_priors[-1]
    prior_text = str(prior.text or "")
    prior_id = str(prior.segment_id)
    updated: list[CandidateDraft] = []
    changed = False
    for candidate in result.candidates:
        if not _looks_like_correction_draft(candidate):
            updated.append(candidate)
            continue
        evidence = list(candidate.evidence)
        if any(item.source_segment_id == prior_id for item in evidence):
            updated.append(candidate)
            continue
        # Prefer marking the current-segment quote as corrects when missing.
        normalized_current: list[EvidenceSpan] = []
        saw_corrects = any(item.relation == "corrects" for item in evidence)
        for item in evidence:
            if (
                not saw_corrects
                and item.source_segment_id is None
                and item.exact_quote in segment_text
                and item.relation == "supports"
            ):
                normalized_current.append(
                    EvidenceSpan(
                        relation="corrects",
                        exact_quote=item.exact_quote,
                        char_start=item.char_start,
                        char_end=item.char_end,
                        source_segment_id=item.source_segment_id,
                    )
                )
                saw_corrects = True
                changed = True
            else:
                normalized_current.append(item)
        normalized_current.append(
            EvidenceSpan(
                relation="supports",
                exact_quote=prior_text,
                char_start=0,
                char_end=len(prior_text),
                source_segment_id=prior_id,
            )
        )
        changed = True
        updated.append(
            CandidateDraft(
                candidate_ref=candidate.candidate_ref,
                kind=candidate.kind,
                schema_name=candidate.schema_name,
                schema_version=candidate.schema_version,
                arguments=candidate.arguments,
                attributes=candidate.attributes,
                polarity=candidate.polarity,
                epistemic=candidate.epistemic,
                temporal=candidate.temporal,
                status=candidate.status,
                evidence=tuple(normalized_current),
                canonical_hint=candidate.canonical_hint,
            )
        )
    if not changed:
        return result
    return ExtractionResult(
        schema_version=result.schema_version,
        abstain=False,
        mentions=result.mentions,
        candidates=tuple(updated),
    )

def _drop_prior_only_candidates(
    result: ExtractionResult,
    *,
    segment_text: str,
    prior_segments: Sequence[MemorySegment],
) -> ExtractionResult:
    """Drop candidates whose evidence quotes appear only in prior text, not current."""
    prior_texts = [
        str(getattr(prior, "text", "") or "")
        for prior in prior_segments
        if str(getattr(prior, "text", "") or "").strip()
    ]
    if not prior_texts or result.abstain or not result.candidates:
        return result
    current = segment_text
    kept: list[CandidateDraft] = []
    for candidate in result.candidates:
        quotes = [
            str(evidence.exact_quote or "").strip()
            for evidence in candidate.evidence
            if str(evidence.exact_quote or "").strip()
        ]
        if not quotes:
            kept.append(candidate)
            continue
        in_current = any(quote in current for quote in quotes)
        only_in_prior = (not in_current) and all(
            any(quote in prior for prior in prior_texts) for quote in quotes
        )
        if only_in_prior:
            continue
        kept.append(candidate)
    if len(kept) == len(result.candidates):
        return result
    if not kept:
        return ExtractionResult(
            schema_version=result.schema_version,
            abstain=True,
            mentions=(),
            candidates=(),
        )
    return ExtractionResult(
        schema_version=result.schema_version,
        abstain=False,
        mentions=result.mentions,
        candidates=tuple(kept),
    )

def _normalize_explicit_temporal_cues(
    result: ExtractionResult,
    *,
    segment_text: str,
    occurred_at: str | None,
    timezone: str,
) -> ExtractionResult:
    from memory.extraction.temporal import normalize_text_temporal

    return normalize_text_temporal(
        result,
        segment_text=segment_text,
        occurred_at=occurred_at,
        timezone=timezone,
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
    processor = TextExtractionProcessor(
        service=service,
        model=model,
        timezone=timezone,
    )
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
        mention_type=mention.mention_type,
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
    *,
    prior_segments: Sequence[MemorySegment] = (),
) -> CandidateInput:
    prior_by_id = {
        str(prior.segment_id): prior
        for prior in prior_segments
        if str(getattr(prior, "segment_id", "") or "")
    }
    evidence_rows: list[CandidateEvidenceInput] = []
    for item in candidate.evidence:
        source = segment
        if item.source_segment_id:
            matched = prior_by_id.get(item.source_segment_id)
            if matched is None:
                raise ValueError(
                    f"candidate evidence references unknown prior segment: "
                    f"{item.source_segment_id!r}"
                )
            source = matched
        evidence_rows.append(
            CandidateEvidenceInput(
                segment_id=source.segment_id,
                relation=item.relation,
                pointer=_span_pointer(source.pointer, item.char_start, item.char_end),
                exact_quote=item.exact_quote,
                context_pointer=source.pointer,
            )
        )
    return CandidateInput(
        local_ref=candidate.candidate_ref,
        segment_id=segment.segment_id,
        kind=candidate.kind,
        schema_name=candidate.schema_name,
        schema_version=candidate.schema_version,
        arguments=candidate.arguments,
        attributes=candidate.attributes,
        polarity=candidate.polarity.value,
        epistemic=candidate.epistemic,
        temporal=candidate.temporal,
        status=candidate.status.value,
        evidence=tuple(evidence_rows),
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
                "mention_type": item.mention_type,
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
    return {
        "candidate_ref": item.candidate_ref,
        "kind": item.kind,
        "schema_name": item.schema_name,
        "schema_version": item.schema_version,
        "arguments": [
            {
                "role": argument.role,
                **(
                    {"mention_ref": argument.mention_ref}
                    if argument.mention_ref is not None
                    else {"literal": thaw_json(argument.literal)}
                ),
            }
            for argument in item.arguments
        ],
        "attributes": {str(k): thaw_json(v) for k, v in item.attributes.items()},
        "polarity": item.polarity.value,
        "epistemic": {
            "mode": item.epistemic.mode.value,
            "speaker_commitment": item.epistemic.speaker_commitment.value,
            "scope": item.epistemic.scope.value,
            "alternatives": [thaw_json(v) for v in item.epistemic.alternatives],
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
                "relation": span.relation,
                "exact_quote": span.exact_quote,
                "char_start": span.char_start,
                "char_end": span.char_end,
                **(
                    {"source_segment_id": span.source_segment_id}
                    if span.source_segment_id
                    else {}
                ),
            }
            for span in item.evidence
        ],
        "canonical_hint": item.canonical_hint,
    }


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

