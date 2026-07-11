from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from memory.config import MemoryConfig
from memory.extraction.parser import ExtractionParseError, parse_extraction_output
from memory.extraction.candidates import CandidateEvidenceInput, CandidateInput
from memory.extraction.mentions import MentionInput
from memory.extraction.pipeline import (
    PROMPT_VERSION,
    TextExtractionProcessor,
    extraction_job_request,
    normalized_segments_hash,
)
from memory.ids import content_hash_from_text
from memory.extraction.schemas import (
    CandidateArgument,
    Epistemic,
    EpistemicMode,
    EpistemicScope,
    SpeakerCommitment,
)
from memory.ingestion.builders import chat_source_input
from memory.ingestion.models import ChatEvidenceRecord
from memory.ingestion.normalizers import ChatTextNormalizer
from memory.models import JobRequest, JobStatus, MemoryJob, ProcessorContext, ProcessorOutput, SegmentInput, SourceInput
from memory.pointers import EvidencePointer
from memory.service import MemoryService


TEXT = "Иван работает в Acme."


def _config(path: str, **overrides) -> MemoryConfig:
    base = MemoryConfig(
        ingest_enabled=False,
        db_path=path,
        worker_enabled=True,
        worker_concurrency=1,
        worker_poll_seconds=0.01,
        job_lease_seconds=10,
        job_max_attempts=2,
        job_retry_base_seconds=0.01,
        job_retry_max_seconds=0.02,
        job_claim_batch_size=1,
        extraction_enabled=True,
        extraction_model_profile="summarize",
        extraction_max_tokens=1024,
    )
    return MemoryConfig(**{**base.__dict__, **overrides})


def _valid_output() -> dict:
    return {
        "schema_version": "1",
        "abstain": False,
        "mentions": [
            {
                "mention_ref": "ivan",
                "mention_type": "person",
                "surface_text": "Иван",
                "char_start": 0,
                "char_end": 4,
                "normalized_hint": "Иван",
            },
            {
                "mention_ref": "acme",
                "mention_type": "organization",
                "surface_text": "Acme",
                "char_start": 16,
                "char_end": 20,
                "normalized_hint": "Acme",
            },
        ],
        "candidates": [
            {
                "candidate_ref": "works",
                "kind": "relation",
                "schema_name": "works_at",
                "schema_version": "1",
                "arguments": [
                    {"role": "person", "mention_ref": "ivan"},
                    {"role": "organization", "mention_ref": "acme"},
                ],
                "attributes": {},
                "polarity": "positive",
                "epistemic": {
                    "mode": "asserted",
                    "speaker_commitment": "certain",
                    "scope": "proposition",
                    "alternatives": [],
                    "needs_confirmation": False,
                    "speaker_ref": "self",
                },
                "temporal": None,
                "status": "proposed",
                "evidence": [
                    {
                        "relation": "supports",
                        "exact_quote": TEXT,
                        "char_start": 0,
                        "char_end": len(TEXT),
                    }
                ],
                "canonical_hint": "works_at:ivan:acme",
            }
        ],
    }


class ParserTests(unittest.TestCase):
    def test_valid_output_preserves_exact_spans(self) -> None:
        parsed = parse_extraction_output(json.dumps(_valid_output(), ensure_ascii=False), segment_text=TEXT)
        self.assertFalse(parsed.abstain)
        self.assertEqual(parsed.mentions[0].surface_text, "Иван")
        self.assertEqual(parsed.candidates[0].evidence[0].exact_quote, TEXT)
        attribute = _valid_output()
        attribute["candidates"][0]["kind"] = "entity_attribute"
        attribute["candidates"][0]["schema_name"] = "has_role"
        self.assertEqual(
            parse_extraction_output(attribute, segment_text=TEXT).candidates[0].kind.value,
            "entity_attribute",
        )

    def test_strict_unknown_duplicate_and_markdown_rejected(self) -> None:
        unknown = _valid_output()
        unknown["confidence"] = 0.99
        with self.assertRaises(ExtractionParseError):
            parse_extraction_output(unknown, segment_text=TEXT)
        with self.assertRaises(ExtractionParseError):
            parse_extraction_output('{"schema_version":"1","schema_version":"1"}', segment_text=TEXT)
        with self.assertRaises(ExtractionParseError):
            parse_extraction_output("```json\n{}\n```", segment_text=TEXT)

    def test_bad_span_and_canonical_entity_id_rejected(self) -> None:
        bad_span = _valid_output()
        bad_span["mentions"][0]["char_end"] = 5
        with self.assertRaises(ExtractionParseError):
            parse_extraction_output(bad_span, segment_text=TEXT)
        canonical = _valid_output()
        canonical["candidates"][0]["attributes"] = {"entity_id": "entity_123"}
        with self.assertRaises(ExtractionParseError):
            parse_extraction_output(canonical, segment_text=TEXT)

    def test_uncertainty_cannot_be_flattened(self) -> None:
        payload = _valid_output()
        candidate = payload["candidates"][0]
        candidate["epistemic"]["speaker_commitment"] = "uncertain"
        candidate["epistemic"]["needs_confirmation"] = True
        candidate["status"] = "needs_confirmation"
        with self.assertRaises(ExtractionParseError):
            parse_extraction_output(payload, segment_text=TEXT)
        candidate["polarity"] = "unknown"
        parsed = parse_extraction_output(payload, segment_text=TEXT)
        self.assertEqual(parsed.candidates[0].polarity.value, "unknown")

    def test_abstention_and_authority_policy(self) -> None:
        abstention = {
            "schema_version": "1",
            "abstain": True,
            "mentions": [],
            "candidates": [],
        }
        self.assertTrue(parse_extraction_output(abstention, segment_text="Привет").abstain)
        with self.assertRaises(ExtractionParseError):
            parse_extraction_output(_valid_output(), segment_text=TEXT, allow_candidates=False)

    def test_invalid_temporal_is_rejected(self) -> None:
        payload = _valid_output()
        payload["candidates"][0]["temporal"] = {"at": "2026-07-10T09:00:00+05:00"}
        with self.assertRaises(ExtractionParseError):
            parse_extraction_output(payload, segment_text=TEXT)

    def test_normalize_user_uncertainty_commitment(self) -> None:
        from memory.extraction.pipeline import _normalize_user_uncertainty
        from memory.extraction.schemas import SpeakerCommitment

        parsed = parse_extraction_output(
            {
                "schema_version": "1",
                "abstain": False,
                "mentions": [
                    {
                        "mention_ref": "ivan",
                        "mention_type": "person",
                        "surface_text": "Иван",
                        "char_start": 17,
                        "char_end": 21,
                        "normalized_hint": None,
                    },
                    {
                        "mention_ref": "acme",
                        "mention_type": "organization",
                        "surface_text": "Acme",
                        "char_start": 33,
                        "char_end": 37,
                        "normalized_hint": None,
                    },
                ],
                "candidates": [
                    {
                        "candidate_ref": "c1",
                        "kind": "relation",
                        "schema_name": "works_at",
                        "schema_version": "1",
                        "arguments": [
                            {"role": "person", "mention_ref": "ivan"},
                            {"role": "organization", "mention_ref": "acme"},
                        ],
                        "attributes": {},
                        "polarity": "unknown",
                        "epistemic": {
                            "mode": "asserted",
                            "speaker_commitment": "possible",
                            "scope": "proposition",
                            "alternatives": [],
                            "needs_confirmation": True,
                            "speaker_ref": None,
                        },
                        "temporal": None,
                        "status": "needs_confirmation",
                        "evidence": [
                            {
                                "relation": "supports",
                                "exact_quote": "Я не уверен, что Иван работает в Acme.",
                                "char_start": 0,
                                "char_end": 38,
                            }
                        ],
                        "canonical_hint": None,
                    }
                ],
            },
            segment_text="Я не уверен, что Иван работает в Acme.",
        )
        normalized = _normalize_user_uncertainty(
            parsed,
            segment_text="Я не уверен, что Иван работает в Acme.",
        )
        self.assertEqual(
            normalized.candidates[0].epistemic.speaker_commitment,
            SpeakerCommitment.UNCERTAIN,
        )

    def test_reported_business_trip_is_synthesized_with_correct_speaker(self) -> None:
        from dataclasses import replace

        from memory.extraction.pipeline import _normalize_reported_belief
        from memory.extraction.schemas import ExtractionResult

        text = "Сосед сказал, что Петр уехал в командировку."
        normalized = _normalize_reported_belief(
            ExtractionResult(schema_version="1", abstain=True),
            segment_text=text,
        )

        self.assertFalse(normalized.abstain)
        self.assertEqual(
            [(mention.surface_text, mention.char_start, mention.char_end) for mention in normalized.mentions],
            [("Сосед", 0, 5), ("Петр", 18, 22)],
        )
        candidate = normalized.candidates[0]
        self.assertEqual(candidate.schema_name, "attends")
        self.assertEqual(candidate.arguments[0].mention_ref, "reported_subject")
        self.assertEqual(candidate.epistemic.mode, EpistemicMode.REPORTED)
        self.assertEqual(candidate.epistemic.speaker_ref, "reported_speaker")
        self.assertEqual(candidate.status.value, "needs_confirmation")

        wrong_model_candidate = replace(
            candidate,
            schema_name="moves_to",
            arguments=(
                CandidateArgument(
                    role="subject",
                    mention_ref="reported_subject",
                    has_literal=False,
                ),
                CandidateArgument(role="place", literal="командировку", has_literal=True),
            ),
        )
        repaired = _normalize_reported_belief(
            ExtractionResult(
                schema_version="1",
                abstain=False,
                mentions=normalized.mentions,
                candidates=(wrong_model_candidate,),
            ),
            segment_text=text,
        ).candidates[0]
        self.assertEqual(repaired.schema_name, "attends")
        self.assertEqual([argument.role for argument in repaired.arguments], ["subject", "event"])

    def test_reporting_verb_does_not_flatten_direct_quote(self) -> None:
        from memory.extraction.pipeline import _normalize_reported_belief
        from memory.extraction.schemas import (
            CandidateDraft,
            CandidateKind,
            CandidateStatus,
            EvidenceSpan,
            ExtractionResult,
            Polarity,
        )

        text = 'Jordan said, “I hate flying.”'
        parsed = ExtractionResult(
            schema_version="1",
            abstain=False,
            candidates=(
                CandidateDraft(
                    candidate_ref="c1",
                    kind=CandidateKind.PREFERENCE,
                    schema_name="likes_flying",
                    schema_version="1",
                    arguments=(CandidateArgument(role="subject", literal="self", has_literal=True),),
                    attributes={},
                    polarity=Polarity.NEGATIVE,
                    epistemic=Epistemic(
                        mode=EpistemicMode.QUOTED,
                        speaker_commitment=SpeakerCommitment.CERTAIN,
                        scope=EpistemicScope.PROPOSITION,
                    ),
                    temporal=None,
                    status=CandidateStatus.PROPOSED,
                    evidence=(EvidenceSpan("supports", text, 0, len(text)),),
                ),
            ),
        )

        normalized = _normalize_reported_belief(parsed, segment_text=text)

        self.assertEqual(normalized.candidates[0].epistemic.mode, EpistemicMode.QUOTED)

    def test_postprocessor_does_not_invent_missing_correction_values(self) -> None:
        from types import SimpleNamespace

        from memory.extraction.pipeline import _promote_correction_candidate
        from memory.extraction.schemas import ExtractionResult

        text = "Уточнение: я больше не вегетарианец."
        normalized = _promote_correction_candidate(
            ExtractionResult(schema_version="1", abstain=True),
            segment_text=text,
            prior_segments=(SimpleNamespace(text="Я вегетарианец."),),
        )

        self.assertTrue(normalized.abstain)
        self.assertEqual(normalized.candidates, ())

    def test_stable_semantic_normalizers_for_preferences_tasks_and_deadlines(self) -> None:
        from memory.extraction.pipeline import apply_segment_post_processors
        from memory.extraction.schemas import ExtractionResult

        def normalize_result(text: str):
            return apply_segment_post_processors(
                ExtractionResult(schema_version="1", abstain=True),
                segment_text=text,
                authority_class="user_direct_statement",
                occurred_at="2026-07-11T09:00:00+05:00",
                timezone="Asia/Tashkent",
                prior_segments=(),
            )

        def normalize(text: str):
            return normalize_result(text).candidates[0]

        coffee = normalize("Пью только чёрный кофе без сахара.")
        self.assertEqual(coffee.schema_name, "prefers")
        self.assertEqual(coffee.arguments[1].literal, "чёрный кофе без сахара")

        one_shot_command = normalize_result("Book a quiet hotel.")
        self.assertTrue(one_shot_command.abstain)
        self.assertEqual(one_shot_command.candidates, ())

        reminder = normalize("Remind me to renew my driver's license next week.")
        self.assertEqual(reminder.schema_name, "created_task")
        self.assertEqual(reminder.arguments[1].literal, "renew driver's license")
        self.assertEqual(reminder.temporal.original_text, "next week")

        exam = normalize("Собираюсь сдать IELTS в декабре.")
        self.assertEqual((exam.kind.value, exam.schema_name), ("task", "created_task"))
        self.assertEqual(exam.arguments[1].literal, "сдать IELTS")
        self.assertEqual(exam.temporal.original_text, "в декабре")

        deadline = normalize("Дедлайн по отчёту — 20 июля.")
        self.assertEqual((deadline.kind.value, deadline.schema_name), ("event", "calendar_event"))
        self.assertEqual(deadline.arguments[1].literal, "Дедлайн по отчёту")
        self.assertEqual(deadline.temporal.original_text, "20 июля")

        sibling = normalize("Моя сестра Оля живёт в Казани.")
        self.assertEqual(sibling.schema_name, "sibling_of")
        self.assertEqual(sibling.arguments[0].mention_ref, "named_sibling")
        self.assertEqual(sibling.arguments[1].literal, "self")

    def test_flight_tool_payload_is_normalized_without_model_guessing(self) -> None:
        from memory.extraction.pipeline import apply_segment_post_processors
        from memory.extraction.schemas import ExtractionResult

        text = '{"flight": "HY704", "departure": "2026-07-18T08:15:00+05:00", "seat": "14A"}'
        candidate = apply_segment_post_processors(
            ExtractionResult(schema_version="1", abstain=True),
            segment_text=text,
            authority_class="tool_api_result",
            occurred_at="2026-07-11T09:00:00+05:00",
            timezone="Asia/Tashkent",
            prior_segments=(),
        ).candidates[0]

        self.assertEqual(candidate.arguments[1].literal, "HY704")
        self.assertEqual(candidate.epistemic.mode.value, "retrieved")
        self.assertEqual(candidate.temporal.event_time, "2026-07-18T08:15:00+05:00")

    def test_sibling_subject_role_is_canonicalized_to_person(self) -> None:
        from memory.extraction.contracts import normalize_candidate_contracts
        from memory.extraction.schemas import (
            CandidateDraft,
            CandidateKind,
            CandidateStatus,
            EvidenceSpan,
            ExtractionResult,
            Polarity,
        )

        text = "Моя сестра Оля."
        candidate = CandidateDraft(
            candidate_ref="c1",
            kind=CandidateKind.RELATION,
            schema_name="sibling_of",
            schema_version="1",
            arguments=(
                CandidateArgument(role="subject", literal="self", has_literal=True),
                CandidateArgument(role="related_to", literal="Оля", has_literal=True),
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
            evidence=(EvidenceSpan("supports", text, 0, len(text)),),
        )
        normalized = normalize_candidate_contracts(
            ExtractionResult(schema_version="1", abstain=False, candidates=(candidate,))
        ).candidates[0]

        self.assertEqual([argument.role for argument in normalized.arguments], ["person", "related_to"])

    def test_considered_relocation_is_possible_not_probable(self) -> None:
        from memory.extraction.pipeline import _normalize_considered_plan
        from memory.extraction.schemas import (
            CandidateDraft,
            CandidateKind,
            CandidateStatus,
            EvidenceSpan,
            ExtractionResult,
            Polarity,
        )

        text = "Думаю переехать в Варшаву осенью."
        candidate = CandidateDraft(
            candidate_ref="c1",
            kind=CandidateKind.EVENT,
            schema_name="moves_to",
            schema_version="1",
            arguments=(
                CandidateArgument(role="subject", literal="self", has_literal=True),
                CandidateArgument(role="place", literal="Warsaw", has_literal=True),
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
            evidence=(EvidenceSpan("supports", text, 0, len(text)),),
        )
        normalized = _normalize_considered_plan(
            ExtractionResult(schema_version="1", abstain=False, candidates=(candidate,)),
            segment_text=text,
        ).candidates[0]

        self.assertEqual(normalized.polarity.value, "unknown")
        self.assertEqual(normalized.epistemic.speaker_commitment.value, "possible")
        self.assertTrue(normalized.epistemic.needs_confirmation)

    def test_general_semantic_policies_transfer_to_unseen_objects(self) -> None:
        from memory.extraction.pipeline import (
            _normalize_intolerance_ontology,
            apply_segment_post_processors,
        )
        from memory.extraction.schemas import (
            CandidateDraft,
            CandidateKind,
            CandidateStatus,
            EvidenceSpan,
            ExtractionResult,
            Polarity,
        )

        def process(text: str) -> ExtractionResult:
            return apply_segment_post_processors(
                ExtractionResult(schema_version="1", abstain=True),
                segment_text=text,
                authority_class="user_direct_statement",
                occurred_at="2026-07-11T09:00:00+05:00",
                timezone="Asia/Tashkent",
                prior_segments=(),
            )

        tea = process("I only drink herbal tea.").candidates[0]
        self.assertEqual((tea.schema_name, tea.arguments[1].literal), ("prefers", "herbal tea"))

        intention = process("I plan to replace the kitchen faucet next month.").candidates[0]
        self.assertEqual(intention.schema_name, "created_task")
        self.assertEqual(intention.arguments[1].literal, "replace the kitchen faucet")

        command = process("Reserve a window seat.")
        self.assertTrue(command.abstain)
        self.assertEqual(command.candidates, ())

        kinship = process("My brother Daniel lives in Toronto.").candidates[0]
        self.assertEqual(kinship.schema_name, "sibling_of")
        self.assertEqual(kinship.arguments[0].mention_ref, "named_sibling")

        text = "I have gluten intolerance."
        allergy = CandidateDraft(
            candidate_ref="c1",
            kind=CandidateKind.ENTITY_ATTRIBUTE,
            schema_name="allergic_to",
            schema_version="1",
            arguments=(
                CandidateArgument(role="subject", literal="self", has_literal=True),
                CandidateArgument(role="allergen", literal="gluten", has_literal=True),
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
            evidence=(EvidenceSpan("supports", text, 0, len(text)),),
        )
        normalized = _normalize_intolerance_ontology(
            ExtractionResult(schema_version="1", abstain=False, candidates=(allergy,)),
            segment_text=text,
        ).candidates[0]
        self.assertEqual((normalized.kind.value, normalized.schema_name), ("preference", "dietary_constraint"))
        self.assertEqual(normalized.arguments[1].role, "excluded")


class _FakeModel:
    model_profile = "fake"

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[list[dict[str, str]]] = []

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = "extraction",
    ) -> str:
        _ = structured_schema
        self.calls.append(messages)
        return json.dumps(self.payload, ensure_ascii=False)


class _SequenceFakeModel(_FakeModel):
    def __init__(self, payloads: list[dict]) -> None:
        super().__init__(payloads[-1])
        self.payloads = list(payloads)

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = "extraction",
    ) -> str:
        _ = structured_schema
        self.calls.append(messages)
        return json.dumps(self.payloads.pop(0), ensure_ascii=False)


class _BadCommitProcessor:
    name = "bad_extractor"
    version = "1"
    stages = frozenset({"candidate_extract"})

    def __init__(self, segment) -> None:
        self.segment = segment

    async def process(self, context: ProcessorContext) -> ProcessorOutput:
        mention = MentionInput(
            local_ref="ivan",
            segment_id=self.segment.segment_id,
            mention_type="person",
            surface_text="Иван",
            normalized_hint="Иван",
            pointer=EvidencePointer(
                pointer_version=1,
                kind="chat_span",
                source_version_id=self.segment.source_version_id,
                location={"chat_message_id": 1, "char_start": 0, "char_end": 4},
            ),
            extractor_name=self.name,
            extractor_version=self.version,
            prompt_version="bad_v1",
        )
        candidate = CandidateInput(
            local_ref="bad",
            segment_id=self.segment.segment_id,
            kind="relation",
            schema_name="works_at",
            schema_version="1",
            arguments=(CandidateArgument(role="person", mention_ref="missing"),),
            attributes={},
            polarity="positive",
            epistemic=Epistemic(
                mode=EpistemicMode.ASSERTED,
                speaker_commitment=SpeakerCommitment.CERTAIN,
                scope=EpistemicScope.PROPOSITION,
            ),
            temporal=None,
            status="proposed",
            evidence=(
                CandidateEvidenceInput(
                    segment_id=self.segment.segment_id,
                    relation="supports",
                    pointer=EvidencePointer(
                        pointer_version=1,
                        kind="chat_span",
                        source_version_id=self.segment.source_version_id,
                        location={"chat_message_id": 1, "char_start": 0, "char_end": len(TEXT)},
                    ),
                    exact_quote=TEXT,
                ),
            ),
            canonical_hint=None,
            extractor_name=self.name,
            extractor_version=self.version,
            prompt_version="bad_v1",
        )
        return ProcessorOutput(
            output_hash="bad",
            output_json={"bad": True},
            new_mentions=(mention,),
            new_candidates=(candidate,),
        )


class _ChatReader:
    def __init__(self, record: ChatEvidenceRecord) -> None:
        self.record = record

    def get_message_for_user(self, message_id: int, user_id: int):
        if message_id == self.record.message_id and user_id == self.record.user_id:
            return self.record
        return None


class NormalizerSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_normalizer_enqueues_versioned_extraction_job_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(str(Path(tmp) / "memory.sqlite"), worker_enabled=False)
            service = MemoryService(config=config)
            now = datetime.now(timezone.utc)
            record = ChatEvidenceRecord(
                message_id=41,
                session_id="s1",
                user_id=7,
                seq=1,
                role="user",
                content=TEXT,
                content_type="text",
                tool_call_id=None,
                tool_name=None,
                source_at=now,
                created_at=now,
                metadata={},
            )
            ingest = service.register_source(chat_source_input(record))
            source = service.sources.get_source(ingest.source_id, user_id=7)
            version = service.sources.get_version(ingest.source_version_id, user_id=7)
            assert source is not None and version is not None
            job = MemoryJob(
                job_id="normalization-test",
                user_id=7,
                source_version_id=ingest.source_version_id,
                stage="normalize_text",
                status=JobStatus.RUNNING,
                attempts=1,
                max_attempts=2,
                processor_name="chat_text_normalizer",
                processor_version="1",
                prompt_version=None,
                input_hash=version.content_hash,
                priority=0,
                not_before=None,
                lease_owner="test",
                lease_token="lease",
                lease_until=now,
            )
            output = await ChatTextNormalizer(
                chat_reader=_ChatReader(record),
                config=config,
            ).process(
                ProcessorContext(
                    job=job,
                    source=source,
                    source_version=version,
                    worker_id="test",
                )
            )
            self.assertEqual(len(output.next_jobs), 1)
            self.assertEqual(output.next_jobs[0].stage, "candidate_extract")
            self.assertEqual(output.next_jobs[0].input_hash, output.output_hash)
            self.assertEqual(output.next_jobs[0].prompt_version, PROMPT_VERSION)


class PipelineIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "memory.sqlite")
        self.config = _config(self.path)
        self.service = MemoryService(config=self.config)

    async def asyncTearDown(self) -> None:
        await self.service.stop_worker(grace_seconds=0.2)
        self.tmp.cleanup()

    def _seed_segment(self, *, authority: str = "user_direct_statement"):
        source = SourceInput(
            user_id=7,
            source_type="chat_message",
            source_ref=f"chat_message_id:{1 if authority == 'user_direct_statement' else 2}",
            authority_class=authority,
            content_hash=content_hash_from_text(TEXT),
            pointer=EvidencePointer(
                pointer_version=1,
                kind="chat_message",
                source_version_id="pending",
                location={"chat_message_id": 1 if authority == "user_direct_statement" else 2},
            ),
        )
        ingest = self.service.register_source(source)
        pointer = EvidencePointer(
            pointer_version=1,
            kind="chat_message",
            source_version_id=ingest.source_version_id,
            location={"chat_message_id": 1 if authority == "user_direct_statement" else 2},
        )
        self.service.segments.insert_segments(
            (
                SegmentInput(
                    source_version_id=ingest.source_version_id,
                    segment_type="chat_text",
                    ordinal=0,
                    text=TEXT,
                    pointer=pointer,
                    normalizer_name="chat_text_normalizer",
                    normalizer_version="1",
                    input_hash=content_hash_from_text(TEXT),
                ),
            ),
            user_id=7,
            lineage_store=self.service.lineage,
        )
        segments = self.service.segments.list_for_source_version(ingest.source_version_id, user_id=7)
        return ingest, segments

    async def _wait_done(self, job_id: str) -> JobStatus:
        for _ in range(200):
            job = self.service.jobs.get_job(job_id)
            assert job is not None
            if job.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.DEAD}:
                return job.status
            await asyncio.sleep(0.01)
        self.fail("extraction job did not finish")

    async def test_worker_persists_mentions_candidates_pointers_and_lineage_atomically(self) -> None:
        ingest, segments = self._seed_segment()
        payload = _valid_output()
        payload["candidates"][0]["epistemic"]["mode"] = "reported"
        payload["candidates"][0]["epistemic"]["speaker_ref"] = "ivan"
        model = _FakeModel(payload)
        self.service.registry.register(
            TextExtractionProcessor(service=self.service, model=model, timezone="Asia/Tashkent")
        )
        request = extraction_job_request(
            normalized_segments_hash(segments),
            model_profile="fake",
        )
        enqueued = self.service.jobs.enqueue(7, ingest.source_version_id, request)
        await self.service.start_worker()
        self.assertEqual(await self._wait_done(enqueued.job_id), JobStatus.DONE)

        mentions = self.service.mentions.list_for_source_version(ingest.source_version_id, user_id=7)
        candidates = self.service.candidates.list_for_user(user_id=7)
        self.assertEqual(len(mentions), 2)
        self.assertEqual(len(candidates), 1)
        mentions_by_surface = {item["surface_text"]: item["mention_id"] for item in mentions}
        self.assertEqual(
            candidates[0]["arguments"][0]["mention_id"],
            mentions_by_surface["Иван"],
        )
        self.assertEqual(
            candidates[0]["epistemic"]["speaker_ref"],
            mentions_by_surface["Иван"],
        )
        with self.service.db.connection() as conn:
            evidence = conn.execute("SELECT * FROM memory_candidate_evidence").fetchone()
            self.assertIsNotNone(evidence)
            pointer = json.loads(evidence["pointer_json"])
            self.assertEqual(pointer["kind"], "chat_span")
            self.assertEqual(pointer["location"]["char_end"], len(TEXT))
            lineage_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM memory_lineage WHERE child_kind IN ('mention','candidate')"
                ).fetchone()["c"]
            )
            self.assertGreaterEqual(lineage_count, 5)

        self.service.sources.invalidate(ingest.source_id, user_id=7, reason="forget")
        with self.service.db.connection() as conn:
            mention_statuses = {
                row["status"] for row in conn.execute("SELECT status FROM memory_mentions")
            }
            candidate_statuses = {
                row["status"] for row in conn.execute("SELECT status FROM memory_claim_candidates")
            }
        self.assertEqual(mention_statuses, {"invalidated"})
        self.assertEqual(candidate_statuses, {"invalidated"})
        self.assertEqual(len(model.calls), 1)
        self.assertIn("segment_text", model.calls[0][1]["content"])

    async def test_assistant_source_hard_abstains_without_model_call(self) -> None:
        ingest, segments = self._seed_segment(authority="assistant_generated")
        model = _FakeModel(_valid_output())
        self.service.registry.register(
            TextExtractionProcessor(service=self.service, model=model, timezone="Asia/Tashkent")
        )
        request = extraction_job_request(normalized_segments_hash(segments), model_profile="fake")
        enqueued = self.service.jobs.enqueue(7, ingest.source_version_id, request)
        await self.service.start_worker()
        self.assertEqual(await self._wait_done(enqueued.job_id), JobStatus.DONE)
        self.assertEqual(model.calls, [])
        self.assertEqual(self.service.candidates.list_for_user(user_id=7), [])

    async def test_worker_repairs_one_invalid_model_response(self) -> None:
        ingest, segments = self._seed_segment()
        invalid = _valid_output()
        invalid["candidates"][0]["temporal"] = {"at": "2026-07-10T09:00:00+05:00"}
        model = _SequenceFakeModel([invalid, _valid_output()])
        self.service.registry.register(
            TextExtractionProcessor(service=self.service, model=model, timezone="Asia/Tashkent")
        )
        request = extraction_job_request(
            normalized_segments_hash(segments),
            model_profile="fake",
        )
        enqueued = self.service.jobs.enqueue(7, ingest.source_version_id, request)
        await self.service.start_worker()

        self.assertEqual(await self._wait_done(enqueued.job_id), JobStatus.DONE)
        self.assertEqual(len(model.calls), 2)
        self.assertIn("rejected by the strict parser", model.calls[1][-1]["content"])
        self.assertEqual(len(self.service.candidates.list_for_user(user_id=7)), 1)

    async def test_candidate_commit_failure_rolls_back_mentions_and_lineage(self) -> None:
        ingest, segments = self._seed_segment()
        self.service.registry.register(_BadCommitProcessor(segments[0]))
        request = JobRequest(
            stage="candidate_extract",
            processor_name="bad_extractor",
            processor_version="1",
            prompt_version="bad_v1",
            model_profile="fake",
            input_hash="bad-input",
        )
        enqueued = self.service.jobs.enqueue(7, ingest.source_version_id, request)
        await self.service.start_worker()
        self.assertEqual(await self._wait_done(enqueued.job_id), JobStatus.FAILED)
        with self.service.db.connection() as conn:
            self.assertEqual(int(conn.execute("SELECT COUNT(*) AS c FROM memory_mentions").fetchone()["c"]), 0)
            self.assertEqual(int(conn.execute("SELECT COUNT(*) AS c FROM memory_claim_candidates").fetchone()["c"]), 0)
            self.assertEqual(
                int(
                    conn.execute(
                        "SELECT COUNT(*) AS c FROM memory_lineage WHERE child_kind IN ('mention','candidate')"
                    ).fetchone()["c"]
                ),
                0,
            )

    def test_job_contract_is_versioned(self) -> None:
        request = extraction_job_request("abc", model_profile="fake")
        self.assertEqual(request.prompt_version, PROMPT_VERSION)
        self.assertEqual(request.stage, "candidate_extract")


if __name__ == "__main__":
    unittest.main()
