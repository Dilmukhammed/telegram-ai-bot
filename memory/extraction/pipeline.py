from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping, Protocol, Sequence, runtime_checkable
from zoneinfo import ZoneInfo

from memory.extraction.candidates import CandidateEvidenceInput, CandidateInput
from memory.extraction.contracts import candidate_contract_violations, normalize_candidate_contracts
from memory.extraction.mentions import MentionInput
from memory.extraction.generation import ModelGeneration
from memory.extraction.prompts import PROMPT_VERSION
from memory.extraction.strategies import generate_segment_extraction_with_trace
from memory.extraction.schemas import (
    CandidateArgument,
    CandidateDraft,
    CandidateKind,
    CandidateStatus,
    Epistemic,
    EpistemicMode,
    EpistemicScope,
    EvidenceSpan,
    ExtractionResult,
    MentionDraft,
    MentionType,
    Polarity,
    SpeakerCommitment,
    Temporal,
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
                _stitch_correction_candidates(
                    self._service,
                    context,
                    segment,
                    prior_segments,
                    result.candidates,
                    result.mentions,
                )
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
    trace: list[dict[str, Any]] = []

    def record(name: str, before: ExtractionResult, after: ExtractionResult) -> ExtractionResult:
        changed = before != after
        item: dict[str, Any] = {"name": name, "changed": changed}
        if changed:
            item["result"] = extraction_result_to_mapping(after)
        trace.append(item)
        return after

    before = result
    result = normalize_candidate_contracts(result)
    result = record("normalize_candidate_contracts", before, result)
    violations = candidate_contract_violations(result)
    trace.append({"name": "validate_candidate_contracts", "violations": violations})
    before = result
    result = _normalize_explicit_temporal_cues(
        result,
        segment_text=segment_text,
        occurred_at=occurred_at,
        timezone=timezone,
    )
    result = record("normalize_explicit_temporal_cues", before, result)
    before = result
    result = _normalize_calendar_tool_temporal(
        result,
        segment_text=segment_text,
        authority_class=authority_class,
        timezone=timezone,
    )
    result = record("normalize_calendar_tool_temporal", before, result)
    before = result
    result = _synthesize_calendar_tool_event(
        result,
        segment_text=segment_text,
        authority_class=authority_class,
        timezone=timezone,
    )
    result = record("synthesize_calendar_tool_event", before, result)
    before = result
    result = _synthesize_open_task_event(
        result,
        segment_text=segment_text,
        authority_class=authority_class,
    )
    result = record("synthesize_open_task_event", before, result)
    before = result
    result = _normalize_user_uncertainty(result, segment_text=segment_text)
    result = record("normalize_user_uncertainty", before, result)
    before = result
    result = _normalize_possibility_commitment(result, segment_text=segment_text)
    result = record("normalize_possibility_commitment", before, result)
    before = result
    result = _normalize_considered_plan(result, segment_text=segment_text)
    result = record("normalize_considered_plan", before, result)
    before = result
    result = _normalize_habitual_preference(result, segment_text=segment_text)
    result = record("normalize_habitual_preference", before, result)
    before = result
    result = _filter_context_scoped_command(result, segment_text=segment_text)
    result = record("filter_context_scoped_command", before, result)
    before = result
    result = _normalize_reminder_task(result, segment_text=segment_text)
    result = record("normalize_reminder_task", before, result)
    before = result
    result = _normalize_explicit_intention(result, segment_text=segment_text)
    result = record("normalize_explicit_intention", before, result)
    before = result
    result = _normalize_deadline_event(result, segment_text=segment_text)
    result = record("normalize_deadline_event", before, result)
    before = result
    result = _normalize_intolerance_ontology(result, segment_text=segment_text)
    result = record("normalize_intolerance_ontology", before, result)
    before = result
    result = _synthesize_explicit_kinship(result, segment_text=segment_text)
    result = record("synthesize_explicit_kinship", before, result)
    before = result
    result = _normalize_reported_belief(result, segment_text=segment_text)
    result = record("normalize_reported_belief", before, result)
    before = result
    result = _normalize_no_longer_employment(
        result,
        segment_text=segment_text,
        occurred_at=occurred_at,
        timezone=timezone,
    )
    result = record("normalize_no_longer_employment", before, result)
    before = result
    result = _synthesize_direct_works_at(result, segment_text=segment_text)
    result = record("synthesize_direct_works_at", before, result)
    before = result
    result = _bootstrap_residence_place_mentions(result, segment_text=segment_text)
    result = record("bootstrap_residence_place_mentions", before, result)
    before = result
    result = _bootstrap_correction_place_mentions(
        result,
        segment_text=segment_text,
        prior_segments=prior_segments,
    )
    result = record("bootstrap_correction_place_mentions", before, result)
    before = result
    result = _promote_correction_candidate(
        result,
        segment_text=segment_text,
        prior_segments=prior_segments,
    )
    result = record("promote_correction_candidate", before, result)
    before = result
    result = _normalize_explicit_temporal_cues(
        result,
        segment_text=segment_text,
        occurred_at=occurred_at,
        timezone=timezone,
    )
    result = record("normalize_explicit_temporal_cues_final", before, result)
    before = result
    from memory.extraction.discourse import normalize_discourse

    result = normalize_discourse(
        result,
        segment_text=segment_text,
        prior_segments=prior_segments,
    )
    result = record("normalize_discourse", before, result)
    before = result
    result = normalize_candidate_contracts(result)
    result = record("normalize_candidate_contracts_final", before, result)
    trace.append(
        {
            "name": "validate_candidate_contracts_final",
            "violations": candidate_contract_violations(result),
        }
    )
    return result, trace


def _local_occurred_at(occurred_at: str, timezone: str) -> str:
    return datetime.fromisoformat(occurred_at).astimezone(ZoneInfo(timezone)).isoformat()


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


def _normalize_calendar_tool_temporal(
    result: ExtractionResult,
    *,
    segment_text: str,
    authority_class: str,
    timezone: str,
) -> ExtractionResult:
    if authority_class != "tool_api_result" or not result.candidates:
        return result
    try:
        payload = json.loads(segment_text)
    except json.JSONDecodeError:
        return result
    if not isinstance(payload, dict):
        return result
    flight = payload.get("flight")
    departure = payload.get("departure")
    if isinstance(flight, str) and isinstance(departure, str):
        try:
            departure_time = datetime.fromisoformat(departure).isoformat(timespec="seconds")
        except ValueError:
            return result
        candidates = tuple(
            replace(
                candidate,
                arguments=(
                    CandidateArgument(role="subject", literal="self", has_literal=True),
                    CandidateArgument(role="title", literal=flight, has_literal=True),
                ),
                temporal=Temporal(
                    original_text=departure,
                    valid_from=None,
                    valid_to=None,
                    event_time=departure_time,
                    precision="second",
                    timezone=timezone,
                ),
            )
            if candidate.kind.value == "event" and candidate.schema_name == "calendar_event"
            else candidate
            for candidate in result.candidates
        )
        return replace(result, candidates=candidates)
    date_value = payload.get("date")
    time_value = payload.get("time")
    if not isinstance(date_value, str) or not isinstance(time_value, str):
        return result

    local = datetime.fromisoformat(f"{date_value}T{time_value}:00").replace(
        tzinfo=ZoneInfo(timezone)
    )
    offset = local.strftime("%z")
    offset = f"{offset[:3]}:{offset[3:]}"
    event_time = f"{date_value}T{time_value}:00{offset}"
    original_text = f"{date_value} {time_value}"

    candidates: list[CandidateDraft] = []
    for candidate in result.candidates:
        if candidate.kind.value == "event" and candidate.schema_name == "calendar_event":
            candidates.append(
                replace(
                    candidate,
                    temporal=Temporal(
                        original_text=original_text,
                        valid_from=None,
                        valid_to=None,
                        event_time=event_time,
                        precision="minute",
                        timezone=timezone,
                    ),
                )
            )
        else:
            candidates.append(candidate)
    return replace(result, candidates=tuple(candidates))


def _synthesize_calendar_tool_event(
    result: ExtractionResult,
    *,
    segment_text: str,
    authority_class: str,
    timezone: str,
) -> ExtractionResult:
    from memory.extraction.schemas import CandidateStatus, Epistemic, EpistemicMode, EpistemicScope, Polarity

    if authority_class != "tool_api_result":
        return result
    try:
        payload = json.loads(segment_text)
    except json.JSONDecodeError:
        return result
    if not isinstance(payload, dict):
        return result
    flight = payload.get("flight")
    departure = payload.get("departure")
    if isinstance(flight, str) and isinstance(departure, str):
        if result.candidates and any(
            candidate.kind.value == "event" and candidate.schema_name == "calendar_event"
            for candidate in result.candidates
        ):
            return result
        try:
            departure_time = datetime.fromisoformat(departure).isoformat(timespec="seconds")
        except ValueError:
            return result
        return replace(
            result,
            abstain=False,
            candidates=(
                CandidateDraft(
                    candidate_ref="c1",
                    kind=CandidateKind.EVENT,
                    schema_name="calendar_event",
                    schema_version="1",
                    arguments=(
                        CandidateArgument(role="subject", literal="self", has_literal=True),
                        CandidateArgument(role="title", literal=flight, has_literal=True),
                    ),
                    attributes={},
                    polarity=Polarity.POSITIVE,
                    epistemic=Epistemic(
                        mode=EpistemicMode.RETRIEVED,
                        speaker_commitment=SpeakerCommitment.CERTAIN,
                        scope=EpistemicScope.PROPOSITION,
                    ),
                    temporal=Temporal(
                        original_text=departure,
                        valid_from=None,
                        valid_to=None,
                        event_time=departure_time,
                        precision="second",
                        timezone=timezone,
                    ),
                    status=CandidateStatus.PROPOSED,
                    evidence=(EvidenceSpan("supports", segment_text, 0, len(segment_text)),),
                ),
            ),
        )
    title = payload.get("event") or payload.get("title")
    date_value = payload.get("date")
    time_value = payload.get("time")
    if not isinstance(title, str) or not isinstance(date_value, str) or not isinstance(time_value, str):
        return result
    if result.candidates and any(
        candidate.kind.value == "event" and candidate.schema_name == "calendar_event"
        for candidate in result.candidates
    ):
        return result
    local = datetime.fromisoformat(f"{date_value}T{time_value}:00").replace(
        tzinfo=ZoneInfo(timezone)
    )
    offset = local.strftime("%z")
    offset = f"{offset[:3]}:{offset[3:]}"
    event_time = f"{date_value}T{time_value}:00{offset}"
    original_text = f"{date_value} {time_value}"
    return replace(
        result,
        abstain=False,
        candidates=(
            CandidateDraft(
                candidate_ref="c1",
                kind=CandidateKind.EVENT,
                schema_name="calendar_event",
                schema_version="1",
                arguments=(
                    CandidateArgument(role="subject", literal="self", has_literal=True),
                    CandidateArgument(role="title", literal=title, has_literal=True),
                ),
                attributes={},
                polarity=Polarity.POSITIVE,
                epistemic=Epistemic(
                    mode=EpistemicMode.RETRIEVED,
                    speaker_commitment=SpeakerCommitment.CERTAIN,
                    scope=EpistemicScope.PROPOSITION,
                ),
                temporal=Temporal(
                    original_text=original_text,
                    valid_from=None,
                    valid_to=None,
                    event_time=event_time,
                    precision="minute",
                    timezone=timezone,
                ),
                status=CandidateStatus.PROPOSED,
                evidence=(
                    EvidenceSpan(
                        relation="supports",
                        exact_quote=segment_text,
                        char_start=0,
                        char_end=len(segment_text),
                    ),
                ),
            ),
        ),
    )


def _synthesize_open_task_event(
    result: ExtractionResult,
    *,
    segment_text: str,
    authority_class: str,
) -> ExtractionResult:
    from memory.extraction.schemas import CandidateStatus, Epistemic, EpistemicMode, EpistemicScope, Polarity

    if authority_class != "tool_api_result":
        return result
    try:
        payload = json.loads(segment_text)
    except json.JSONDecodeError:
        return result
    if not isinstance(payload, dict):
        return result
    title = payload.get("title")
    status = payload.get("status")
    if not isinstance(title, str):
        return result
    if status not in {None, "needsAction", "open", "created"}:
        return result
    schema_name = "open_task" if status in {None, "needsAction", "open"} else "created_task"
    if result.candidates and any(
        candidate.kind.value == "task" and candidate.schema_name in {"open_task", "created_task"}
        for candidate in result.candidates
    ):
        return result
    return replace(
        result,
        abstain=False,
        candidates=(
            CandidateDraft(
                candidate_ref="c1",
                kind=CandidateKind.TASK,
                schema_name=schema_name,
                schema_version="1",
                arguments=(
                    CandidateArgument(role="subject", literal="self", has_literal=True),
                    CandidateArgument(role="title", literal=title, has_literal=True),
                ),
                attributes={},
                polarity=Polarity.POSITIVE,
                epistemic=Epistemic(
                    mode=EpistemicMode.RETRIEVED,
                    speaker_commitment=SpeakerCommitment.CERTAIN,
                    scope=EpistemicScope.PROPOSITION,
                ),
                temporal=None,
                status=CandidateStatus.PROPOSED,
                evidence=(
                    EvidenceSpan(
                        relation="supports",
                        exact_quote=segment_text,
                        char_start=0,
                        char_end=len(segment_text),
                    ),
                ),
            ),
        ),
    )


_USER_UNCERTAINTY_MARKERS = (
    "не уверен",
    "неуверен",
    "not sure",
    "i'm not sure",
    "i am not sure",
)


def _normalize_user_uncertainty(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    from memory.extraction.schemas import CandidateStatus, EpistemicMode, EpistemicScope, Polarity

    folded = segment_text.casefold()
    if not any(marker in folded for marker in _USER_UNCERTAINTY_MARKERS):
        return result
    if not result.mentions:
        bootstrapped = _bootstrap_uncertain_works_at(result, segment_text=segment_text)
        if bootstrapped is not None:
            result = bootstrapped
    has_uncertain_works_at = any(
        candidate.schema_name == "works_at"
        and candidate.polarity.value == "unknown"
        and candidate.epistemic.speaker_commitment.value == "uncertain"
        for candidate in result.candidates
    )
    if not result.candidates or not has_uncertain_works_at:
        synthesized = _synthesize_uncertain_works_at(result, segment_text=segment_text)
        if synthesized is not None:
            result = synthesized
    if not result.candidates:
        return result
    candidates: list[CandidateDraft] = []
    for candidate in result.candidates:
        epistemic = candidate.epistemic
        if epistemic.mode.value == "asserted":
            candidates.append(
                replace(
                    candidate,
                    polarity=Polarity.UNKNOWN,
                    status=CandidateStatus.NEEDS_CONFIRMATION,
                    epistemic=replace(
                        epistemic,
                        speaker_commitment=SpeakerCommitment.UNCERTAIN,
                        needs_confirmation=True,
                    ),
                )
            )
        else:
            candidates.append(candidate)
    return replace(result, candidates=tuple(candidates))


_REPORTED_BELIEF_MARKERS = (
    "думает",
    "говорит",
    "сказал",
    "считает",
    " thinks ",
    " says ",
    " said ",
    " believes ",
)

_DIRECT_QUOTE_MARKS = ('"', "“", "”", "«", "»")


def _reported_participants(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> tuple[ExtractionResult, MentionDraft, MentionDraft] | None:
    """Find the reporter and proposition subject in explicit reported speech."""
    match = re.match(
        r"\s*(?P<reporter>[\w'-]+(?:\s+[\w'-]+)?)\s+"
        r"(?:said|says|thinks|believes|сказал|сказала|говорит|думает|считает)"
        r"\s*,?\s+(?:that|что)\s+"
        r"(?P<subject>[A-ZА-ЯЁ][\w'-]*)\b",
        segment_text,
        re.IGNORECASE,
    )
    if match is None:
        return None

    mentions = list(result.mentions)

    def ensure_mention(group: str, local_ref: str) -> MentionDraft:
        start, end = match.span(group)
        surface = segment_text[start:end]
        existing = next(
            (
                mention
                for mention in mentions
                if mention.mention_type is MentionType.PERSON
                and mention.char_start == start
                and mention.char_end == end
            ),
            None,
        )
        if existing is not None:
            return existing
        mention = MentionDraft(
            mention_ref=local_ref,
            mention_type=MentionType.PERSON,
            surface_text=surface,
            char_start=start,
            char_end=end,
            normalized_hint=surface,
        )
        mentions.append(mention)
        return mention

    reporter = ensure_mention("reporter", "reported_speaker")
    subject = ensure_mention("subject", "reported_subject")
    return replace(result, mentions=tuple(mentions)), reporter, subject


def _normalize_reported_belief(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    from memory.extraction.schemas import CandidateStatus, EpistemicMode, Polarity

    folded = f" {segment_text.casefold()} "
    if not any(marker in folded for marker in _REPORTED_BELIEF_MARKERS):
        return result
    # Explicit quotation marks are handled as quoted speech downstream.  A
    # reporting verb alone must not flatten a direct quote into hearsay.
    if any(mark in segment_text for mark in _DIRECT_QUOTE_MARKS):
        return result
    participants = _reported_participants(result, segment_text=segment_text)
    reporter: MentionDraft | None = None
    subject: MentionDraft | None = None
    if participants is not None:
        result, reporter, subject = participants
    if not result.candidates:
        synthesized = _synthesize_reported_event(
            result,
            segment_text=segment_text,
            reporter=reporter,
            subject=subject,
        )
        if synthesized is not None:
            return synthesized
    candidates: list[CandidateDraft] = []
    for candidate in result.candidates:
        epistemic = candidate.epistemic
        if participants is not None or epistemic.mode.value == "reported":
            arguments = list(candidate.arguments)
            if subject is not None:
                subject_index = next(
                    (
                        index
                        for index, argument in enumerate(arguments)
                        if argument.role in {"subject", "person"}
                    ),
                    None,
                )
                if subject_index is not None:
                    arguments[subject_index] = CandidateArgument(
                        role=arguments[subject_index].role,
                        mention_ref=subject.mention_ref,
                        has_literal=False,
                    )
            kind = candidate.kind
            schema_name = candidate.schema_name
            if subject is not None and (
                "командировк" in folded or "business trip" in folded
            ):
                kind = CandidateKind.EVENT
                schema_name = "attends"
                arguments = [
                    CandidateArgument(
                        role="subject",
                        mention_ref=subject.mention_ref,
                        has_literal=False,
                    ),
                    CandidateArgument(
                        role="event",
                        literal=(
                            "командировка"
                            if "командировк" in folded
                            else "business trip"
                        ),
                        has_literal=True,
                    ),
                ]
            candidates.append(
                replace(
                    candidate,
                    kind=kind,
                    schema_name=schema_name,
                    arguments=tuple(arguments),
                    polarity=Polarity.UNKNOWN,
                    status=CandidateStatus.NEEDS_CONFIRMATION,
                    epistemic=replace(
                        epistemic,
                        mode=EpistemicMode.REPORTED,
                        speaker_commitment=SpeakerCommitment.POSSIBLE,
                        needs_confirmation=True,
                        speaker_ref=(
                            reporter.mention_ref
                            if reporter is not None
                            else epistemic.speaker_ref
                        ),
                    ),
                )
            )
        else:
            candidates.append(candidate)
    return replace(result, candidates=tuple(candidates))


_POSSIBILITY_MARKERS = (
    " might ",
    " maybe ",
    " possibly ",
    " возможно ",
    " возможно,",
)

_PROBABLE_MARKERS = (
    " probably ",
    " вероятно ",
)


def _normalize_possibility_commitment(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    folded = f" {segment_text.casefold()} "
    probable = any(marker in folded for marker in _PROBABLE_MARKERS)
    possible = any(marker in folded for marker in _POSSIBILITY_MARKERS)
    if not probable and not possible:
        return result
    target = SpeakerCommitment.PROBABLE if probable else SpeakerCommitment.POSSIBLE
    candidates: list[CandidateDraft] = []
    for candidate in result.candidates:
        epistemic = candidate.epistemic
        if (
            epistemic.mode.value == "asserted"
            and candidate.polarity.value == "unknown"
            and epistemic.speaker_commitment.value in {"uncertain", "possible", "probable"}
        ):
            candidates.append(
                replace(
                    candidate,
                    epistemic=replace(
                        epistemic,
                        speaker_commitment=target,
                    ),
                )
            )
        else:
            candidates.append(candidate)
    return replace(result, candidates=tuple(candidates))


def _normalize_considered_plan(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    """Keep tentative first-person plans distinct from confident predictions."""
    if re.search(r"^\s*(?:думаю\s+\w+ть|i(?:'m| am) thinking (?:of|about))", segment_text, re.I) is None:
        return result
    candidates = tuple(
        replace(
            candidate,
            polarity=Polarity.UNKNOWN,
            status=CandidateStatus.NEEDS_CONFIRMATION,
            epistemic=replace(
                candidate.epistemic,
                mode=EpistemicMode.ASSERTED,
                speaker_commitment=SpeakerCommitment.POSSIBLE,
                needs_confirmation=True,
                speaker_ref=None,
            ),
        )
        if candidate.schema_name == "moves_to"
        else candidate
        for candidate in result.candidates
    )
    return replace(result, candidates=candidates)


def _normalize_habitual_preference(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    match = re.search(
        r"(?:\bпью\s+только\s+|\bi\s+only\s+drink\s+)(?P<value>[^.]+)",
        segment_text,
        re.I,
    )
    if match is None:
        return result
    value = match.group("value").strip()
    candidate_ref = result.candidates[0].candidate_ref if result.candidates else "c1"
    candidate = CandidateDraft(
        candidate_ref=candidate_ref,
        kind=CandidateKind.PREFERENCE,
        schema_name="prefers",
        schema_version="1",
        arguments=(
            CandidateArgument(role="subject", literal="self", has_literal=True),
            CandidateArgument(role="value", literal=value, has_literal=True),
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
        evidence=(EvidenceSpan("supports", segment_text, 0, len(segment_text)),),
    )
    return replace(result, abstain=False, candidates=(candidate,))


def _filter_context_scoped_command(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    """Do not persist one-shot action commands as durable user preferences."""
    if re.match(
        r"^\s*(?:book|reserve|find|order|show|забронируй|найди|закажи|покажи)\b",
        segment_text,
        re.I,
    ) is None:
        return result
    return replace(result, abstain=True, mentions=(), candidates=())


def _normalize_reminder_task(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    match = re.search(
        r"\bremind\s+me\s+to\s+(?P<title>.+?)(?:\s+next\s+week)?[.!]?\s*$",
        segment_text,
        re.I,
    )
    if match is None:
        return result
    title = re.sub(r"^(\w+\s+)my\s+", r"\1", match.group("title").strip(), flags=re.I)
    candidate_ref = result.candidates[0].candidate_ref if result.candidates else "c1"
    temporal = next(
        (candidate.temporal for candidate in result.candidates if candidate.temporal is not None),
        None,
    )
    candidate = CandidateDraft(
        candidate_ref=candidate_ref,
        kind=CandidateKind.TASK,
        schema_name="created_task",
        schema_version="1",
        arguments=(
            CandidateArgument(role="subject", literal="self", has_literal=True),
            CandidateArgument(role="title", literal=title, has_literal=True),
        ),
        attributes={},
        polarity=Polarity.POSITIVE,
        epistemic=Epistemic(
            mode=EpistemicMode.ASSERTED,
            speaker_commitment=SpeakerCommitment.CERTAIN,
            scope=EpistemicScope.PROPOSITION,
        ),
        temporal=temporal,
        status=CandidateStatus.PROPOSED,
        evidence=(EvidenceSpan("supports", segment_text, 0, len(segment_text)),),
    )
    return replace(result, abstain=False, candidates=(candidate,))


def _normalize_explicit_intention(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    match = re.search(
        r"^\s*(?:собираюсь|планирую|i\s+plan\s+to|i\s+intend\s+to)\s+(?P<title>.+?)\s*[.!]?$",
        segment_text,
        re.I,
    )
    if match is None:
        return result
    temporal = next(
        (candidate.temporal for candidate in result.candidates if candidate.temporal is not None),
        None,
    )
    title = match.group("title").strip()
    if temporal is not None and temporal.original_text:
        cue_start = title.casefold().rfind(temporal.original_text.casefold())
        if cue_start > 0:
            title = title[:cue_start].rstrip(" ,;:-")
    title = re.sub(
        r"\s+(?:"
        r"в\s+(?:январе|феврале|марте|апреле|мае|июне|июле|августе|сентябре|октябре|ноябре|декабре)"
        r"|(?:осенью|зимой|весной|летом)"
        r"|(?:next|this)\s+(?:week|month|year|spring|summer|autumn|fall|winter)"
        r")$",
        "",
        title,
        flags=re.I,
    ).rstrip(" ,;:-")
    candidate_ref = result.candidates[0].candidate_ref if result.candidates else "c1"
    candidate = CandidateDraft(
        candidate_ref=candidate_ref,
        kind=CandidateKind.TASK,
        schema_name="created_task",
        schema_version="1",
        arguments=(
            CandidateArgument(role="subject", literal="self", has_literal=True),
            CandidateArgument(role="title", literal=title, has_literal=True),
        ),
        attributes={},
        polarity=Polarity.POSITIVE,
        epistemic=Epistemic(
            mode=EpistemicMode.ASSERTED,
            speaker_commitment=SpeakerCommitment.CERTAIN,
            scope=EpistemicScope.PROPOSITION,
        ),
        temporal=temporal,
        status=CandidateStatus.PROPOSED,
        evidence=(EvidenceSpan("supports", segment_text, 0, len(segment_text)),),
    )
    return replace(result, abstain=False, mentions=(), candidates=(candidate,))


def _normalize_deadline_event(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    match = re.search(
        r"\b(?P<title>дедлайн(?:\s+по\s+[^—–:\d]+?)?)\s*(?:[—–:]|\s+на\s+)",
        segment_text,
        re.I,
    )
    if match is None:
        match = re.search(
            r"\b(?P<title>[^.]*?deadline)\s*(?:is|:|[—–-])",
            segment_text,
            re.I,
        )
    if match is None:
        return result
    temporal = next(
        (candidate.temporal for candidate in result.candidates if candidate.temporal is not None),
        None,
    )
    candidate_ref = result.candidates[0].candidate_ref if result.candidates else "c1"
    candidate = CandidateDraft(
        candidate_ref=candidate_ref,
        kind=CandidateKind.EVENT,
        schema_name="calendar_event",
        schema_version="1",
        arguments=(
            CandidateArgument(role="subject", literal="self", has_literal=True),
            CandidateArgument(
                role="title",
                literal=match.group("title").strip(),
                has_literal=True,
            ),
        ),
        attributes={},
        polarity=Polarity.POSITIVE,
        epistemic=Epistemic(
            mode=EpistemicMode.ASSERTED,
            speaker_commitment=SpeakerCommitment.CERTAIN,
            scope=EpistemicScope.PROPOSITION,
        ),
        temporal=temporal,
        status=CandidateStatus.PROPOSED,
        evidence=(EvidenceSpan("supports", segment_text, 0, len(segment_text)),),
    )
    return replace(result, abstain=False, candidates=(candidate,))


def _normalize_intolerance_ontology(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    if re.search(r"\b(?:непереносим\w*|intoleran\w*)\b", segment_text, re.I) is None:
        return result
    candidates: list[CandidateDraft] = []
    for candidate in result.candidates:
        if candidate.schema_name != "allergic_to":
            candidates.append(candidate)
            continue
        allergen = next(
            (argument for argument in candidate.arguments if argument.role == "allergen"),
            None,
        )
        if allergen is None:
            candidates.append(candidate)
            continue
        candidates.append(
            replace(
                candidate,
                kind=CandidateKind.PREFERENCE,
                schema_name="dietary_constraint",
                arguments=(
                    CandidateArgument(role="subject", literal="self", has_literal=True),
                    replace(allergen, role="excluded"),
                ),
            )
        )
    return replace(result, candidates=tuple(candidates))


def _synthesize_explicit_kinship(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    match = re.search(
        r"\bмоя\s+(?:сестра|брат)\s+(?P<name>[А-ЯЁ][А-Яа-яЁё'-]+)\b",
        segment_text,
        re.I,
    )
    if match is None:
        match = re.search(
            r"\bmy\s+(?:sister|brother)\s+(?P<name>[A-Z][A-Za-z'-]+)\b",
            segment_text,
            re.I,
        )
    if match is None:
        return result
    start, end = match.span("name")
    person = next(
        (
            mention
            for mention in result.mentions
            if mention.mention_type is MentionType.PERSON
            and mention.char_start == start
            and mention.char_end == end
        ),
        None,
    )
    mentions = list(result.mentions)
    if person is None:
        surface = segment_text[start:end]
        person = MentionDraft(
            mention_ref="named_sibling",
            mention_type=MentionType.PERSON,
            surface_text=surface,
            char_start=start,
            char_end=end,
            normalized_hint=surface,
        )
        mentions.append(person)
    if any(candidate.schema_name == "sibling_of" for candidate in result.candidates):
        candidates = tuple(
            replace(
                candidate,
                arguments=(
                    CandidateArgument(
                        role="person",
                        mention_ref=person.mention_ref,
                        has_literal=False,
                    ),
                    CandidateArgument(role="related_to", literal="self", has_literal=True),
                ),
            )
            if candidate.schema_name == "sibling_of"
            else candidate
            for candidate in result.candidates
        )
        return replace(result, mentions=tuple(mentions), candidates=candidates)
    used_refs = {candidate.candidate_ref for candidate in result.candidates}
    index = 1
    while f"c{index}" in used_refs:
        index += 1
    sibling = CandidateDraft(
        candidate_ref=f"c{index}",
        kind=CandidateKind.RELATION,
        schema_name="sibling_of",
        schema_version="1",
        arguments=(
            CandidateArgument(
                role="person",
                mention_ref=person.mention_ref,
                has_literal=False,
            ),
            CandidateArgument(role="related_to", literal="self", has_literal=True),
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
        evidence=(EvidenceSpan("supports", segment_text, 0, len(segment_text)),),
    )
    return replace(
        result,
        abstain=False,
        mentions=tuple(mentions),
        candidates=(*result.candidates, sibling),
    )


def _bootstrap_residence_place_mentions(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    if any(mention.mention_type.value == "place" for mention in result.mentions):
        return result
    place = _extract_place_literal(segment_text)
    if place is None:
        return result
    start = segment_text.casefold().find(place.casefold())
    if start < 0:
        return result
    surface = segment_text[start : start + len(place)]
    return replace(
        result,
        mentions=(
            *result.mentions,
            MentionDraft(
                mention_ref="place",
                mention_type=MentionType.PLACE,
                surface_text=surface,
                char_start=start,
                char_end=start + len(surface),
                normalized_hint=None,
            ),
        ),
    )


def _bootstrap_correction_place_mentions(
    result: ExtractionResult,
    *,
    segment_text: str,
    prior_segments: Sequence[MemorySegment],
) -> ExtractionResult:
    folded = segment_text.casefold()
    if not any(marker in folded for marker in _CORRECTION_MARKERS):
        return result
    return _bootstrap_residence_place_mentions(result, segment_text=segment_text)


def _bootstrap_uncertain_works_at(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult | None:
    if result.mentions:
        return None
    folded = segment_text.casefold()
    if not any(marker in folded for marker in _USER_UNCERTAINTY_MARKERS):
        return None
    match = re.search(
        r".*(?:не уверен|not sure),?\s+что\s+(.+?)\s+работает\s+в\s+(.+?)\.?\s*$",
        segment_text,
        flags=re.IGNORECASE,
    )
    if match is None:
        match = re.search(
            r".*(?:not sure|i am not sure|i'm not sure),?\s+that\s+(.+?)\s+works?\s+at\s+(.+?)\.?\s*$",
            segment_text,
            flags=re.IGNORECASE,
        )
    if match is None:
        return None
    person_surface = match.group(1).strip()
    org_surface = match.group(2).strip()
    person_start = segment_text.find(person_surface)
    org_start = segment_text.find(org_surface, person_start + len(person_surface))
    if person_start < 0 or org_start < 0:
        return None
    return replace(
        result,
        mentions=(
            MentionDraft(
                mention_ref="ivan",
                mention_type=MentionType.PERSON,
                surface_text=person_surface,
                char_start=person_start,
                char_end=person_start + len(person_surface),
                normalized_hint=None,
            ),
            MentionDraft(
                mention_ref="acme",
                mention_type=MentionType.ORGANIZATION,
                surface_text=org_surface,
                char_start=org_start,
                char_end=org_start + len(org_surface),
                normalized_hint=None,
            ),
        ),
    )


def _synthesize_uncertain_works_at(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult | None:
    from memory.extraction.schemas import CandidateStatus, Epistemic, EpistemicMode, EpistemicScope, Polarity

    person = next((m for m in result.mentions if m.mention_type.value == "person"), None)
    organization = next(
        (m for m in result.mentions if m.mention_type.value == "organization"),
        None,
    )
    if person is None or organization is None:
        return None
    if "работает в" not in segment_text.casefold() and "works at" not in segment_text.casefold():
        return None
    return replace(
        result,
        abstain=False,
        candidates=(
            CandidateDraft(
                candidate_ref="c1",
                kind=CandidateKind.RELATION,
                schema_name="works_at",
                schema_version="1",
                arguments=(
                    CandidateArgument(
                        role="person",
                        mention_ref=person.mention_ref,
                        has_literal=False,
                    ),
                    CandidateArgument(
                        role="organization",
                        mention_ref=organization.mention_ref,
                        has_literal=False,
                    ),
                ),
                attributes={},
                polarity=Polarity.UNKNOWN,
                epistemic=Epistemic(
                    mode=EpistemicMode.ASSERTED,
                    speaker_commitment=SpeakerCommitment.UNCERTAIN,
                    scope=EpistemicScope.PROPOSITION,
                    needs_confirmation=True,
                ),
                temporal=None,
                status=CandidateStatus.NEEDS_CONFIRMATION,
                evidence=(
                    EvidenceSpan(
                        relation="supports",
                        exact_quote=segment_text,
                        char_start=0,
                        char_end=len(segment_text),
                    ),
                ),
            ),
        ),
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
        mention_type=mention.mention_type.value,
        surface_text=mention.surface_text,
        normalized_hint=mention.normalized_hint,
        pointer=_span_pointer(segment.pointer, mention.char_start, mention.char_end),
        extractor_name=TEXT_EXTRACTOR_NAME,
        extractor_version=TEXT_EXTRACTOR_VERSION,
        prompt_version=context.job.prompt_version or PROMPT_VERSION,
    )


def _synthesize_reported_event(
    result: ExtractionResult,
    *,
    segment_text: str,
    reporter: MentionDraft | None = None,
    subject: MentionDraft | None = None,
) -> ExtractionResult | None:
    from memory.extraction.schemas import CandidateStatus, Epistemic, EpistemicMode, EpistemicScope, Polarity

    people = sorted(
        (m for m in result.mentions if m.mention_type.value == "person"),
        key=lambda mention: mention.char_start,
    )
    if reporter is None or subject is None:
        if len(people) < 2:
            return None
        reporter = people[0]
        subject = people[1]
    folded = segment_text.casefold()
    left_job = any(marker in folded for marker in ("уволился", "left", "quit"))
    business_trip = "командировк" in folded or "business trip" in folded
    if not left_job and not business_trip:
        return None
    schema_name = "left_job" if left_job else "attends"
    arguments = (
        (
            CandidateArgument(
                role="person",
                mention_ref=subject.mention_ref,
                has_literal=False,
            ),
        )
        if left_job
        else (
            CandidateArgument(
                role="subject",
                mention_ref=subject.mention_ref,
                has_literal=False,
            ),
            CandidateArgument(
                role="event",
                literal="командировка" if "командировк" in folded else "business trip",
                has_literal=True,
            ),
        )
    )
    return replace(
        result,
        abstain=False,
        candidates=(
            CandidateDraft(
                candidate_ref="c1",
                kind=CandidateKind.EVENT,
                schema_name=schema_name,
                schema_version="1",
                arguments=arguments,
                attributes={},
                polarity=Polarity.UNKNOWN,
                epistemic=Epistemic(
                    mode=EpistemicMode.REPORTED,
                    speaker_commitment=SpeakerCommitment.POSSIBLE,
                    scope=EpistemicScope.PROPOSITION,
                    needs_confirmation=True,
                    speaker_ref=reporter.mention_ref,
                ),
                temporal=None,
                status=CandidateStatus.NEEDS_CONFIRMATION,
                evidence=(
                    EvidenceSpan(
                        relation="supports",
                        exact_quote=segment_text,
                        char_start=0,
                        char_end=len(segment_text),
                    ),
                ),
            ),
        ),
    )


_CROSS_SEGMENT_PLACE_PREFIX = "$seg:"


def _cross_segment_place_ref(segment_id: str) -> str:
    return f"{_CROSS_SEGMENT_PLACE_PREFIX}{segment_id}:place"


def _is_cross_segment_place_ref(mention_ref: str) -> bool:
    return mention_ref.startswith(_CROSS_SEGMENT_PLACE_PREFIX)


def _normalize_no_longer_employment(
    result: ExtractionResult,
    *,
    segment_text: str,
    occurred_at: str | None,
    timezone: str,
) -> ExtractionResult:
    from memory.extraction.schemas import CandidateStatus, Epistemic, EpistemicMode, EpistemicScope, Polarity

    folded = segment_text.casefold()
    if "no longer work" not in folded and "no longer works" not in folded:
        return result
    organization = next(
        (m for m in result.mentions if m.mention_type.value == "organization"),
        None,
    )
    if organization is None:
        return result
    local_occurred_at = (
        _local_occurred_at(occurred_at, timezone) if occurred_at is not None else None
    )
    temporal = None
    if local_occurred_at is not None:
        marker = "no longer"
        start = folded.index(marker)
        cue = segment_text[start : start + len(marker)]
        temporal = Temporal(
            original_text=cue,
            valid_from=None,
            valid_to=local_occurred_at,
            event_time=None,
            precision="second",
            timezone=timezone,
        )
    candidates: list[CandidateDraft] = []
    for candidate in result.candidates:
        if candidate.kind.value == "event" and candidate.schema_name == "left_job":
            candidates.append(
                CandidateDraft(
                    candidate_ref=candidate.candidate_ref,
                    kind=CandidateKind.RELATION,
                    schema_name="works_at",
                    schema_version="1",
                    arguments=(
                        CandidateArgument(role="person", literal="self", has_literal=True),
                        CandidateArgument(
                            role="organization",
                            mention_ref=organization.mention_ref,
                            has_literal=False,
                        ),
                    ),
                    attributes={},
                    polarity=Polarity.NEGATIVE,
                    epistemic=Epistemic(
                        mode=EpistemicMode.ASSERTED,
                        speaker_commitment=SpeakerCommitment.CERTAIN,
                        scope=EpistemicScope.PROPOSITION,
                    ),
                    temporal=temporal or candidate.temporal,
                    status=CandidateStatus.PROPOSED,
                    evidence=candidate.evidence,
                    canonical_hint=candidate.canonical_hint,
                )
            )
        elif (
            candidate.kind.value == "relation"
            and candidate.schema_name == "works_at"
            and candidate.polarity.value == "positive"
        ):
            candidates.append(
                replace(
                    candidate,
                    polarity=Polarity.NEGATIVE,
                    temporal=temporal or candidate.temporal,
                )
            )
        else:
            candidates.append(candidate)
    if candidates:
        return replace(result, candidates=tuple(candidates))
    return replace(
        result,
        abstain=False,
        candidates=(
            CandidateDraft(
                candidate_ref="c1",
                kind=CandidateKind.RELATION,
                schema_name="works_at",
                schema_version="1",
                arguments=(
                    CandidateArgument(role="person", literal="self", has_literal=True),
                    CandidateArgument(
                        role="organization",
                        mention_ref=organization.mention_ref,
                        has_literal=False,
                    ),
                ),
                attributes={},
                polarity=Polarity.NEGATIVE,
                epistemic=Epistemic(
                    mode=EpistemicMode.ASSERTED,
                    speaker_commitment=SpeakerCommitment.CERTAIN,
                    scope=EpistemicScope.PROPOSITION,
                ),
                temporal=temporal,
                status=CandidateStatus.PROPOSED,
                evidence=(
                    EvidenceSpan(
                        relation="supports",
                        exact_quote=segment_text,
                        char_start=0,
                        char_end=len(segment_text),
                    ),
                ),
            ),
        ),
    )


def _synthesize_direct_works_at(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    from memory.extraction.schemas import CandidateStatus, Epistemic, EpistemicMode, EpistemicScope, Polarity

    if result.candidates:
        return result
    folded = segment_text.casefold()
    if "работает в" not in folded and "works at" not in folded and "work at" not in folded:
        return result
    person = next((m for m in result.mentions if m.mention_type.value == "person"), None)
    organization = next(
        (m for m in result.mentions if m.mention_type.value == "organization"),
        None,
    )
    if person is None or organization is None:
        return result
    return replace(
        result,
        abstain=False,
        candidates=(
            CandidateDraft(
                candidate_ref="c1",
                kind=CandidateKind.RELATION,
                schema_name="works_at",
                schema_version="1",
                arguments=(
                    CandidateArgument(
                        role="person",
                        mention_ref=person.mention_ref,
                        has_literal=False,
                    ),
                    CandidateArgument(
                        role="organization",
                        mention_ref=organization.mention_ref,
                        has_literal=False,
                    ),
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
                        relation="supports",
                        exact_quote=segment_text,
                        char_start=0,
                        char_end=len(segment_text),
                    ),
                ),
            ),
        ),
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


_CORRECTION_MARKERS = (
    "исправление",
    "уточнение",
    "correction",
    "больше не",
    "no longer",
    "нет, теперь",
    "no, now",
    "нет, второй",
)


def _promote_correction_candidate(
    result: ExtractionResult,
    *,
    segment_text: str,
    prior_segments: Sequence[MemorySegment],
) -> ExtractionResult:
    folded = segment_text.casefold()
    if not any(marker in folded for marker in _CORRECTION_MARKERS):
        return result
    prior_text = prior_segments[-1].text if prior_segments else ""
    candidates: list[CandidateDraft] = []
    for candidate in result.candidates:
        promoted = _promote_single_correction(
            candidate,
            segment_text=segment_text,
            prior_text=prior_text,
        )
        candidates.append(promoted)
    if any(candidate.kind.value == "correction" for candidate in candidates) and len(candidates) > 1:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.kind.value == "correction"
        ]
    return replace(result, abstain=not candidates, candidates=tuple(candidates))


def _promote_single_correction(
    candidate: CandidateDraft,
    *,
    segment_text: str,
    prior_text: str,
) -> CandidateDraft:
    from memory.extraction.schemas import CandidateStatus, Epistemic, EpistemicMode, EpistemicScope, Polarity

    old_place = _extract_place_literal(prior_text)
    new_place = _extract_place_literal(segment_text)
    if old_place is not None and new_place is not None:
        return CandidateDraft(
            candidate_ref=candidate.candidate_ref,
            kind=CandidateKind.CORRECTION,
            schema_name="corrects_residence",
            schema_version="1",
            arguments=(
                CandidateArgument(role="subject", literal="self", has_literal=True),
                CandidateArgument(role="old", literal=old_place, has_literal=True),
                CandidateArgument(role="new", literal=new_place, has_literal=True),
            ),
            attributes={},
            polarity=Polarity.POSITIVE,
            epistemic=Epistemic(
                mode=EpistemicMode.ASSERTED,
                speaker_commitment=SpeakerCommitment.CERTAIN,
                scope=EpistemicScope.PROPOSITION,
            ),
            temporal=candidate.temporal,
            status=CandidateStatus.PROPOSED,
            evidence=candidate.evidence,
        )
    return candidate


def _extract_place_literal(text: str) -> str | None:
    markers = (
        "live in ",
        "work in ",
        "живу в ",
        "работаю в ",
        "i live in ",
        "i work in ",
    )
    folded = text.casefold()
    for marker in markers:
        if marker in folded:
            start = folded.index(marker) + len(marker)
            return text[start:].strip(" .")
    return None


def _stitch_correction_candidates(
    service: "MemoryService",
    context: ProcessorContext,
    segment: MemorySegment,
    prior_segments: Sequence[MemorySegment],
    candidates: Sequence[CandidateDraft],
    result_mentions: Sequence[MentionDraft],
) -> list[CandidateInput]:
    inputs: list[CandidateInput] = []
    for candidate in candidates:
        if candidate.kind.value != "correction":
            base = _candidate_input(context, segment, candidate)
            cross_segment_mention_ids = _cross_segment_mention_ids(
                candidate,
                segment=segment,
                prior_segments=prior_segments,
                service=service,
                user_id=context.job.user_id,
            )
            if not cross_segment_mention_ids:
                inputs.append(base)
                continue
            from memory.extraction.discourse import parse_cross_segment_ref

            referenced_prior = None
            for argument in candidate.arguments:
                if argument.mention_ref is None:
                    continue
                parsed = parse_cross_segment_ref(argument.mention_ref)
                if parsed is not None:
                    referenced_prior = next(
                        (item for item in prior_segments if item.segment_id == parsed[0]),
                        None,
                    )
                    if referenced_prior is not None:
                        break
            extra_evidence: list[CandidateEvidenceInput] = []
            if referenced_prior is not None and referenced_prior.text:
                extra_evidence.append(
                    CandidateEvidenceInput(
                        segment_id=referenced_prior.segment_id,
                        relation="introduces_entity",
                        pointer=_span_pointer(
                            referenced_prior.pointer,
                            0,
                            len(referenced_prior.text),
                        ),
                        exact_quote=referenced_prior.text,
                        context_pointer=referenced_prior.pointer,
                    )
                )
            current_evidence = list(base.evidence)
            if current_evidence:
                current_evidence[0] = replace(
                    current_evidence[0],
                    relation="supports_coreference",
                )
            inputs.append(
                replace(
                    base,
                    evidence=tuple(
                        current_evidence + extra_evidence
                        if candidate.schema_name == "sibling_of"
                        else extra_evidence + current_evidence
                    ),
                    cross_segment_mention_ids=cross_segment_mention_ids,
                )
            )
            continue
        candidate = _rewrite_residence_correction_arguments(
            candidate,
            segment=segment,
            prior_segments=prior_segments,
            result_mentions=result_mentions,
            service=service,
            user_id=context.job.user_id,
        )
        base = _candidate_input(context, segment, candidate)
        extra_evidence: list[CandidateEvidenceInput] = []
        if candidate.schema_name == "corrects_selection" and len(prior_segments) >= 2:
            for index, prior in enumerate(prior_segments):
                prior_text = prior.text or ""
                if not prior_text:
                    continue
                relation = "introduces_alternatives" if index == 0 else "supports"
                extra_evidence.append(
                    CandidateEvidenceInput(
                        segment_id=prior.segment_id,
                        relation=relation,
                        pointer=_span_pointer(prior.pointer, 0, len(prior_text)),
                        exact_quote=prior_text,
                        context_pointer=prior.pointer,
                    )
                )
        elif prior_segments:
            prior = prior_segments[-1]
            prior_text = prior.text or ""
            if prior_text:
                extra_evidence.append(
                    CandidateEvidenceInput(
                        segment_id=prior.segment_id,
                        relation="supports",
                        pointer=_span_pointer(prior.pointer, 0, len(prior_text)),
                        exact_quote=prior_text,
                        context_pointer=prior.pointer,
                    ),
                )
        current_evidence = list(base.evidence)
        if current_evidence:
            current_evidence[0] = replace(current_evidence[0], relation="corrects")
        cross_segment_mention_ids = _cross_segment_mention_ids(
            candidate,
            segment=segment,
            prior_segments=prior_segments,
            service=service,
            user_id=context.job.user_id,
        )
        inputs.append(
            replace(
                base,
                evidence=tuple(extra_evidence + current_evidence),
                cross_segment_mention_ids=cross_segment_mention_ids,
            )
        )
    return inputs


def _rewrite_residence_correction_arguments(
    candidate: CandidateDraft,
    *,
    segment: MemorySegment,
    prior_segments: Sequence[MemorySegment],
    result_mentions: Sequence[MentionDraft],
    service: "MemoryService",
    user_id: int,
) -> CandidateDraft:
    if candidate.schema_name != "corrects_residence" or not prior_segments:
        return candidate
    prior = prior_segments[-1]
    prior_place = _first_place_mention_row(
        service.mentions.list_for_segment(prior.segment_id, user_id=user_id)
    )
    current_place = next(
        (mention for mention in result_mentions if mention.mention_type.value == "place"),
        None,
    )
    if prior_place is None or current_place is None:
        return candidate
    old_ref = _cross_segment_place_ref(prior.segment_id)
    return replace(
        candidate,
        arguments=(
            CandidateArgument(role="subject", literal="self", has_literal=True),
            CandidateArgument(role="old", mention_ref=old_ref, has_literal=False),
            CandidateArgument(
                role="new",
                mention_ref=current_place.mention_ref,
                has_literal=False,
            ),
        ),
    )


def _cross_segment_mention_ids(
    candidate: CandidateDraft,
    *,
    segment: MemorySegment,
    prior_segments: Sequence[MemorySegment],
    service: "MemoryService",
    user_id: int,
) -> dict[tuple[str, str], str]:
    bindings: dict[tuple[str, str], str] = {}
    if not prior_segments:
        return bindings
    from memory.extraction.discourse import parse_cross_segment_ref

    for argument in candidate.arguments:
        if argument.mention_ref is None:
            continue
        parsed = parse_cross_segment_ref(argument.mention_ref)
        if parsed is None:
            continue
        prior_segment_id, mention_type = parsed
        if not any(item.segment_id == prior_segment_id for item in prior_segments):
            continue
        row = _first_mention_row(
            service.mentions.list_for_segment(prior_segment_id, user_id=user_id),
            mention_type=mention_type,
        )
        if row is not None:
            bindings[(segment.segment_id, argument.mention_ref)] = str(row["mention_id"])
    return bindings


def _first_place_mention_row(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return _first_mention_row(rows, mention_type="place")


def _first_mention_row(
    rows: Sequence[Mapping[str, Any]],
    *,
    mention_type: str,
) -> Mapping[str, Any] | None:
    for row in rows:
        if str(row.get("mention_type")) == mention_type:
            return row
    return None


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
