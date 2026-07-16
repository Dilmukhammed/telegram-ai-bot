from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from memory.extraction.pipeline import (
    TextExtractionProcessor,
    extraction_job_request,
    normalized_segments_hash,
)
from memory.ids import content_hash_from_text
from memory.models import JobStatus, SegmentInput, SourceInput
from memory.pointers import EvidencePointer
from memory.service import MemoryService
from memory.structured_output import StructuredOutputModel
from memory.verification.parser import VerificationParseError, parse_verification_output
from memory.verification.pipeline import CandidateVerificationProcessor
from memory.verification.scheduler import VerificationScheduler
from memory.verification.schemas import VerificationVerdict
from memory.verification.scoring import DEFAULT_POLICY_VERSION, score_and_route
from memory.verification.adversarial import (
    looks_like_correction,
    requires_adversarial_verification,
)
from memory.verification.support import (
    candidate_view,
    deterministic_exact_tool_support,
    deterministic_preflight,
)
from memory.eval.loader import load_pack
from memory.eval.verification_expectations import (
    load_verification_expectations,
    resolve_verification_expectations_path,
)
from test_memory_extraction import TEXT, _FakeModel, _config, _valid_output


def _verdict(verdict: str = "supported") -> dict:
    return {
        "schema_version": "1",
        "verdict": verdict,
        "evidence_directness": "direct" if verdict == "supported" else None,
        "scope_errors": [],
        "ambiguities": [],
        "missing_context": [],
        "corrected_candidate": None,
    }


class _VerifierModel:
    def __init__(self, payload: dict, profile: str) -> None:
        self.payload = payload
        self.model_profile = profile
        self.calls: list[list[dict[str, str]]] = []

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = "verification",
    ) -> str:
        self.assert_schema = structured_schema
        self.calls.append(messages)
        return json.dumps(self.payload)


class VerificationParserTests(unittest.TestCase):
    def test_strict_verdict(self) -> None:
        parsed = parse_verification_output(_verdict())
        self.assertEqual(parsed.verdict, VerificationVerdict.SUPPORTED)
        with self.assertRaises(VerificationParseError):
            parse_verification_output({**_verdict(), "confidence": 0.9})
        with self.assertRaises(VerificationParseError):
            parse_verification_output(
                '{"schema_version":"1","schema_version":"1","verdict":"supported",'
                '"evidence_directness":"direct","scope_errors":[],"ambiguities":[],'
                '"missing_context":[],"corrected_candidate":null}'
            )

    def test_supported_requires_directness(self) -> None:
        payload = _verdict()
        payload["evidence_directness"] = None
        with self.assertRaises(VerificationParseError):
            parse_verification_output(payload)

    def test_verification_expectations_cover_smoke_candidate_refs(self) -> None:
        base = load_pack("memory/eval/fixtures/text_v1")
        verification = load_verification_expectations(
            resolve_verification_expectations_path("verification_v1")
        )
        smoke = {
            fixture.fixture_id: fixture
            for fixture in base.fixtures
            if fixture.tier.value == "smoke"
        }
        self.assertEqual(set(verification.cases), set(smoke))
        for fixture_id, expectation in verification.cases.items():
            refs = {
                candidate.candidate_ref
                for candidate in smoke[fixture_id].expected.candidates
            }
            self.assertTrue(
                {outcome.candidate_ref for outcome in expectation.outcomes} <= refs
            )

    def test_verification_v2_expectations_cover_pack(self) -> None:
        base = load_pack("memory/eval/fixtures/text_v1_verification_v2")
        verification = load_verification_expectations(
            resolve_verification_expectations_path("verification_v2")
        )
        fixture_ids = {fixture.fixture_id for fixture in base.fixtures}
        self.assertEqual(set(verification.cases), fixture_ids)
        for fixture_id, expectation in verification.cases.items():
            fixture = next(item for item in base.fixtures if item.fixture_id == fixture_id)
            refs = {candidate.candidate_ref for candidate in fixture.expected.candidates}
            self.assertTrue(
                {outcome.candidate_ref for outcome in expectation.outcomes} <= refs
            )

    def test_verification_v3_expectations_cover_pack(self) -> None:
        base = load_pack("memory/eval/fixtures/text_v1_verification_v3")
        verification = load_verification_expectations(
            resolve_verification_expectations_path("verification_v3")
        )
        fixture_ids = {fixture.fixture_id for fixture in base.fixtures}
        self.assertEqual(set(verification.cases), fixture_ids)
        for fixture_id, expectation in verification.cases.items():
            fixture = next(item for item in base.fixtures if item.fixture_id == fixture_id)
            refs = {candidate.candidate_ref for candidate in fixture.expected.candidates}
            self.assertTrue(
                {outcome.candidate_ref for outcome in expectation.outcomes} <= refs
            )

    def test_preflight_resolves_absolute_span_inside_chunk(self) -> None:
        candidate = {
            "candidate_kind": "relation",
            "schema_name": "works_at",
            "arguments": [
                {"role": "person", "mention_id": "m1"},
                {"role": "organization", "mention_id": "m2"},
            ],
            "mentions": {
                "m1": {"status": "active"},
                "m2": {"status": "active"},
            },
            "polarity": "positive",
            "epistemic": {
                "mode": "asserted",
                "speaker_commitment": "certain",
                "speaker_ref": None,
            },
            "evidence": [
                {
                    "segment_text": "Иван работает в Acme.",
                    "exact_quote": "Иван",
                    "pointer": {
                        "location": {"char_start": 100, "char_end": 104}
                    },
                    "context_pointer": {
                        "location": {"char_start": 100, "char_end": 121}
                    },
                    "segment_status": "active",
                    "source_status": "active",
                    "source_version_status": "active",
                    "authority_class": "user_direct_statement",
                }
            ],
        }
        self.assertEqual(deterministic_preflight(candidate), ())

    def test_preflight_allows_assistant_context_with_primary_evidence(self) -> None:
        candidate = {
            "candidate_kind": "preference",
            "schema_name": "prefers",
            "arguments": [
                {"role": "subject", "mention_id": "m1"},
                {"role": "value", "literal": "Hotel Bristol"},
            ],
            "mentions": {"m1": {"status": "active"}},
            "polarity": "positive",
            "epistemic": {
                "mode": "asserted",
                "speaker_commitment": "certain",
                "speaker_ref": None,
            },
            "evidence": [
                {
                    "segment_text": "Hotel Aurora or Hotel Bristol",
                    "exact_quote": "Hotel Aurora or Hotel Bristol",
                    "pointer": {"location": {"message_id": "assistant-1"}},
                    "segment_status": "active",
                    "source_status": "active",
                    "source_version_status": "active",
                    "authority_class": "assistant_generated",
                    "relation": "introduces_alternatives",
                },
                {
                    "segment_text": "No, the second one.",
                    "exact_quote": "the second one",
                    "pointer": {"location": {"message_id": "user-1"}},
                    "segment_status": "active",
                    "source_status": "active",
                    "source_version_status": "active",
                    "authority_class": "user_direct_statement",
                    "relation": "supports",
                },
            ],
        }
        self.assertEqual(deterministic_preflight(candidate), ())
        candidate["evidence"] = candidate["evidence"][:1]
        self.assertEqual(deterministic_preflight(candidate), ("authority_mismatch",))

    def test_candidate_view_exposes_temporal_provenance(self) -> None:
        view = candidate_view(
            {
                "candidate_id": "mcand_temporal",
                "candidate_kind": "task",
                "schema_name": "task",
                "arguments": [],
                "mentions": {},
                "attributes": {},
                "polarity": "positive",
                "epistemic": {},
                "temporal": {
                    "original_text": "tomorrow at 9",
                    "timezone": "Asia/Tashkent",
                    "start": "2026-07-12T09:00:00+05:00",
                },
                "evidence": [
                    {
                        "segment_text": "tomorrow at 9",
                        "exact_quote": "tomorrow at 9",
                        "source_occurred_at": "2026-07-11T12:00:00+05:00",
                    }
                ],
            },
            context_chars=32,
        )
        self.assertEqual(
            view["temporal_provenance"]["source_occurred_at"],
            ["2026-07-11T12:00:00+05:00"],
        )
        self.assertEqual(view["temporal_provenance"]["timezone"], "Asia/Tashkent")

    def test_exact_tool_task_support_does_not_need_llm(self) -> None:
        candidate = {
            "candidate_kind": "task",
            "schema_name": "created_task",
            "arguments": [
                {"role": "subject", "literal": "self"},
                {"role": "title", "literal": "Buy bread"},
            ],
            "attributes": {},
            "polarity": "positive",
            "epistemic": {
                "mode": "retrieved",
                "speaker_commitment": "certain",
            },
            "temporal": None,
            "evidence": [
                {
                    "authority_class": "tool_api_result",
                    "relation": "supports",
                    "exact_quote": (
                        '{"task_id":"task_1","title":"Buy bread",'
                        '"status":"created"}'
                    ),
                }
            ],
        }
        self.assertTrue(deterministic_exact_tool_support(candidate))
        candidate["arguments"][1]["literal"] = "Buy milk"
        self.assertFalse(deterministic_exact_tool_support(candidate))

    def test_exact_tool_support_ignores_free_kind_labels(self) -> None:
        candidate = {
            "candidate_kind": "queued_todo",
            "schema_name": "inbox_item",
            "arguments": [
                {"role": "owner", "literal": "self"},
                {"role": "title", "literal": "Buy bread"},
            ],
            "attributes": {},
            "polarity": "positive",
            "epistemic": {
                "mode": "retrieved",
                "speaker_commitment": "certain",
            },
            "temporal": None,
            "evidence": [
                {
                    "authority_class": "tool_api_result",
                    "relation": "supports",
                    "exact_quote": (
                        '{"task_id":"task_1","title":"Buy bread",'
                        '"status":"created"}'
                    ),
                }
            ],
        }
        self.assertTrue(deterministic_exact_tool_support(candidate))

    def test_exact_tool_calendar_event_supports_payload_temporal(self) -> None:
        candidate = {
            "candidate_kind": "event",
            "schema_name": "calendar_event",
            "arguments": [
                {"role": "subject", "literal": "self"},
                {"role": "title", "literal": "HY704"},
            ],
            "attributes": {},
            "polarity": "positive",
            "epistemic": {
                "mode": "retrieved",
                "speaker_commitment": "certain",
            },
            "temporal": {
                "original_text": "2026-07-18T08:15:00+05:00",
                "event_time": "2026-07-18T08:15:00+05:00",
                "valid_from": None,
                "valid_to": None,
                "precision": "second",
                "timezone": "Asia/Tashkent",
            },
            "evidence": [
                {
                    "authority_class": "tool_api_result",
                    "relation": "supports",
                    "exact_quote": (
                        '{"flight":"HY704",'
                        '"departure":"2026-07-18T08:15:00+05:00"}'
                    ),
                }
            ],
        }
        self.assertTrue(deterministic_exact_tool_support(candidate))
        candidate["temporal"]["event_time"] = "2026-07-19T08:15:00+05:00"
        self.assertFalse(deterministic_exact_tool_support(candidate))

    def test_adversarial_triggers_on_structural_correction(self) -> None:
        base = {
            "candidate_kind": "occupation_update",
            "polarity": "positive",
            "epistemic": {
                "mode": "asserted",
                "speaker_commitment": "certain",
                "needs_confirmation": False,
            },
            "temporal": None,
            "arguments": [
                {"role": "old", "literal": "designer"},
                {"role": "new", "literal": "PM"},
            ],
            "evidence": [{"relation": "supports"}],
        }
        self.assertTrue(looks_like_correction(base))
        self.assertTrue(requires_adversarial_verification(base))

        by_evidence = {
            **base,
            "candidate_kind": "fact",
            "arguments": [{"role": "subject", "literal": "self"}],
            "evidence": [{"relation": "corrects"}],
        }
        self.assertTrue(looks_like_correction(by_evidence))

        by_kind = {
            **base,
            "candidate_kind": "corrects_occupation",
            "arguments": [{"role": "subject", "literal": "self"}],
            "evidence": [{"relation": "supports"}],
        }
        self.assertTrue(looks_like_correction(by_kind))

        plain = {
            **base,
            "candidate_kind": "prefers",
            "arguments": [{"role": "object", "literal": "tea"}],
            "evidence": [{"relation": "supports"}],
        }
        self.assertFalse(looks_like_correction(plain))
        self.assertFalse(requires_adversarial_verification(plain))


class StructuredOutputTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_strict_compatible_json_object_cascade(self) -> None:
        class Client:
            model_name = "test-model"
            reasoning_effort = None

            def __init__(self) -> None:
                self.formats: list[dict] = []

            async def chat_structured(self, messages, **kwargs):
                _ = messages
                self.formats.append(kwargs["response_format"])
                if len(self.formats) < 3:
                    raise RuntimeError("unsupported response format")
                return '{"ok":true}'

        client = Client()
        generated = await StructuredOutputModel(
            client,
            model_profile="checker",
            max_tokens=256,
        ).generate(
            [{"role": "user", "content": "verify"}],
            schema_name="probe",
            schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
        )
        self.assertEqual(generated.text, '{"ok":true}')
        self.assertEqual(
            [item["type"] for item in client.formats],
            ["json_schema", "json_schema", "json_object"],
        )
        self.assertTrue(client.formats[0]["json_schema"]["strict"])
        self.assertFalse(client.formats[1]["json_schema"]["strict"])
        self.assertEqual(generated.metadata["response_format"], "json_object")


class VerificationPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.config = _config(str(Path(self.tmp.name) / "memory.sqlite"))
        self.service = MemoryService(config=self.config)

    async def asyncTearDown(self) -> None:
        await self.service.stop_worker(grace_seconds=0.2)
        self.tmp.cleanup()

    def _seed_segment(self):
        source = SourceInput(
            user_id=7,
            source_type="chat_message",
            source_ref="chat_message_id:1",
            authority_class="user_direct_statement",
            content_hash=content_hash_from_text(TEXT),
            pointer=EvidencePointer(
                pointer_version=1,
                kind="chat_message",
                source_version_id="pending",
                location={"chat_message_id": 1},
            ),
        )
        ingest = self.service.register_source(source)
        self.service.segments.insert_segments(
            (
                SegmentInput(
                    source_version_id=ingest.source_version_id,
                    segment_type="chat_text",
                    ordinal=0,
                    text=TEXT,
                    pointer=EvidencePointer(
                        pointer_version=1,
                        kind="chat_message",
                        source_version_id=ingest.source_version_id,
                        location={"chat_message_id": 1},
                    ),
                    normalizer_name="chat_text_normalizer",
                    normalizer_version="1",
                    input_hash=content_hash_from_text(TEXT),
                ),
            ),
            user_id=7,
            lineage_store=self.service.lineage,
        )
        return ingest, self.service.segments.list_for_source_version(
            ingest.source_version_id,
            user_id=7,
        )

    async def _wait_terminal(self, job_id: str) -> JobStatus:
        for _ in range(300):
            job = self.service.jobs.get_job(job_id)
            assert job is not None
            if job.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.DEAD}:
                return job.status
            await asyncio.sleep(0.01)
        self.fail(f"job did not finish: {job_id}")

    async def test_scheduler_verifies_and_routes_atomically(self) -> None:
        ingest, segments = self._seed_segment()
        extraction_model = _FakeModel(_valid_output())
        support_model = _VerifierModel(_verdict(), "checker")
        adversarial_model = _VerifierModel(_verdict(), "agent")
        self.service.registry.register(
            TextExtractionProcessor(
                service=self.service,
                model=extraction_model,
                timezone="Asia/Tashkent",
            )
        )
        self.service.registry.register(
            CandidateVerificationProcessor(
                service=self.service,
                support_model=support_model,
                adversarial_model=adversarial_model,
                policy_version="verification_policy_v1",
            )
        )
        extraction = self.service.jobs.enqueue(
            7,
            ingest.source_version_id,
            extraction_job_request(
                normalized_segments_hash(segments),
                model_profile="fake",
            ),
        )
        await self.service.start_worker()
        self.assertEqual(await self._wait_terminal(extraction.job_id), JobStatus.DONE)

        scheduler = VerificationScheduler(
            service=self.service,
            support_profile="checker",
            adversarial_profile="agent",
            policy_version="verification_policy_v1",
            interval_seconds=1,
            batch_size=10,
        )
        scan = scheduler.scan_once()
        self.assertEqual(scan.jobs_created, 1)
        with self.service.db.connection() as conn:
            row = conn.execute(
                "SELECT job_id, target_kind, target_id FROM memory_jobs "
                "WHERE stage = 'candidate_verify'"
            ).fetchone()
        assert row is not None
        self.assertEqual(row["target_kind"], "candidate")
        status = await self._wait_terminal(str(row["job_id"]))
        with self.service.db.connection() as conn:
            error = conn.execute(
                "SELECT last_error FROM memory_jobs WHERE job_id = ?",
                (row["job_id"],),
            ).fetchone()["last_error"]
        self.assertEqual(status, JobStatus.DONE, error)

        candidates = self.service.candidates.list_for_user(user_id=7)
        self.assertEqual(candidates[0]["status"], "ready_for_resolution")
        self.assertEqual(candidates[0]["acceptance_policy"], "verification_policy_v1")
        verdicts = self.service.verification.list_verdicts(
            user_id=7,
            candidate_id=str(row["target_id"]),
        )
        self.assertEqual({item["role"] for item in verdicts}, {"deterministic", "support"})
        self.assertEqual(scheduler.scan_once().jobs_created, 0)
        self.assertEqual(len(support_model.calls), 1)
        self.assertEqual(adversarial_model.calls, [])

        await self.service.stop_worker(grace_seconds=0.2)
        self.service = MemoryService(config=self.config)
        self.service.registry.register(
            CandidateVerificationProcessor(
                service=self.service,
                support_model=support_model,
                adversarial_model=adversarial_model,
                policy_version=DEFAULT_POLICY_VERSION,
            )
        )
        await self.service.start_worker()
        rescore_scheduler = VerificationScheduler(
            service=self.service,
            support_profile="checker",
            adversarial_profile="agent",
            policy_version=DEFAULT_POLICY_VERSION,
            interval_seconds=1,
            batch_size=10,
        )
        self.assertEqual(rescore_scheduler.scan_once().jobs_created, 1)
        with self.service.db.connection() as conn:
            rescore_job = conn.execute(
                "SELECT job_id FROM memory_jobs WHERE stage = 'candidate_verify' "
                "AND job_id != ?",
                (row["job_id"],),
            ).fetchone()
        assert rescore_job is not None
        self.assertEqual(
            await self._wait_terminal(str(rescore_job["job_id"])),
            JobStatus.DONE,
        )
        candidates = self.service.candidates.list_for_user(user_id=7)
        self.assertEqual(candidates[0]["acceptance_policy"], DEFAULT_POLICY_VERSION)
        self.assertEqual(len(support_model.calls), 1)
        with self.service.db.connection() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) AS c FROM memory_candidate_scores").fetchone()["c"],
                2,
            )

        self.service.sources.invalidate(ingest.source_id, user_id=7, reason="forget")
        with self.service.db.connection() as conn:
            self.assertEqual(
                {
                    item["status"]
                    for item in conn.execute("SELECT status FROM memory_candidate_verdicts")
                },
                {"invalidated"},
            )
            self.assertEqual(
                {
                    item["status"]
                    for item in conn.execute("SELECT status FROM memory_candidate_scores")
                },
                {"invalidated"},
            )

    def test_scoring_rejects_malformed_without_model_verdict(self) -> None:
        from memory.verification.schemas import (
            VerificationVerdictInput,
            VerifierRole,
        )

        malformed = VerificationVerdictInput(
            candidate_id="mcand_test",
            role=VerifierRole.DETERMINISTIC,
            verdict=VerificationVerdict.MALFORMED,
            evidence_directness=None,
            scope_errors=("argument_unsupported",),
            ambiguities=(),
            missing_context=(),
            verifier_name="preflight",
            verifier_version="1",
            prompt_version="v1",
            model_profile=None,
            model_name=None,
            input_hash="hash",
            raw_output={},
        )
        decision = score_and_route(
            {"candidate_id": "mcand_test", "evidence": []},
            (malformed,),
        )
        self.assertEqual(decision.update.to_status, "rejected")
        self.assertEqual(decision.score.components["argument_completeness"], 0.0)

    def test_argument_completeness_is_one_without_structural_errors(self) -> None:
        from memory.verification.schemas import (
            EvidenceDirectness,
            VerificationVerdictInput,
            VerifierRole,
        )

        deterministic = VerificationVerdictInput(
            candidate_id="mcand_ok",
            role=VerifierRole.DETERMINISTIC,
            verdict=VerificationVerdict.SUPPORTED,
            evidence_directness=EvidenceDirectness.DIRECT,
            scope_errors=(),
            ambiguities=(),
            missing_context=(),
            verifier_name="preflight",
            verifier_version="1",
            prompt_version="v1",
            model_profile=None,
            model_name=None,
            input_hash="hash",
            raw_output={},
        )
        support = VerificationVerdictInput(
            candidate_id="mcand_ok",
            role=VerifierRole.SUPPORT,
            verdict=VerificationVerdict.SUPPORTED,
            evidence_directness=EvidenceDirectness.DIRECT,
            scope_errors=(),
            ambiguities=(),
            missing_context=(),
            verifier_name="support",
            verifier_version="1",
            prompt_version="v1",
            model_profile="checker",
            model_name="test",
            input_hash="hash2",
            raw_output={},
        )
        decision = score_and_route(
            {"candidate_id": "mcand_ok", "evidence": []},
            (deterministic, support),
        )
        self.assertEqual(decision.score.components["argument_completeness"], 1.0)

    def test_epistemic_soft_signals_route_to_needs_confirmation(self) -> None:
        from memory.verification.schemas import (
            EvidenceDirectness,
            VerificationVerdictInput,
            VerifierRole,
        )

        deterministic = VerificationVerdictInput(
            candidate_id="mcand_soft",
            role=VerifierRole.DETERMINISTIC,
            verdict=VerificationVerdict.SUPPORTED,
            evidence_directness=EvidenceDirectness.DIRECT,
            scope_errors=(),
            ambiguities=(),
            missing_context=(),
            verifier_name="preflight",
            verifier_version="1",
            prompt_version="v1",
            model_profile=None,
            model_name=None,
            input_hash="hash",
            raw_output={},
        )
        support = VerificationVerdictInput(
            candidate_id="mcand_soft",
            role=VerifierRole.SUPPORT,
            verdict=VerificationVerdict.SUPPORTED,
            evidence_directness=EvidenceDirectness.DIRECT,
            scope_errors=(),
            ambiguities=(),
            missing_context=(),
            verifier_name="support",
            verifier_version="1",
            prompt_version="v1",
            model_profile="checker",
            model_name="test",
            input_hash="hash2",
            raw_output={},
        )
        decision = score_and_route(
            {
                "candidate_id": "mcand_soft",
                "polarity": "unknown",
                "epistemic": {"mode": "asserted", "speaker_commitment": "possible"},
                "evidence": [],
            },
            (deterministic, support),
        )
        self.assertEqual(decision.update.to_status, "needs_confirmation")

        quoted = score_and_route(
            {
                "candidate_id": "mcand_soft",
                "polarity": "positive",
                "epistemic": {"mode": "quoted", "speaker_commitment": "certain"},
                "evidence": [],
            },
            (deterministic, support),
        )
        self.assertEqual(quoted.update.to_status, "needs_confirmation")

    def test_structural_correction_insufficient_becomes_needs_confirmation(self) -> None:
        from memory.verification.schemas import (
            EvidenceDirectness,
            VerificationVerdictInput,
            VerifierRole,
        )

        deterministic = VerificationVerdictInput(
            candidate_id="mcand_corr",
            role=VerifierRole.DETERMINISTIC,
            verdict=VerificationVerdict.SUPPORTED,
            evidence_directness=EvidenceDirectness.DIRECT,
            scope_errors=(),
            ambiguities=(),
            missing_context=(),
            verifier_name="preflight",
            verifier_version="1",
            prompt_version="v1",
            model_profile=None,
            model_name=None,
            input_hash="hash",
            raw_output={},
        )
        support = VerificationVerdictInput(
            candidate_id="mcand_corr",
            role=VerifierRole.SUPPORT,
            verdict=VerificationVerdict.INSUFFICIENT,
            evidence_directness=None,
            scope_errors=("argument_unsupported",),
            ambiguities=(),
            missing_context=(),
            verifier_name="support",
            verifier_version="1",
            prompt_version="v1",
            model_profile="checker",
            model_name="test",
            input_hash="hash2",
            raw_output={},
        )
        decision = score_and_route(
            {
                "candidate_id": "mcand_corr",
                "candidate_kind": "occupation_change",
                "polarity": "positive",
                "epistemic": {"mode": "asserted", "speaker_commitment": "certain"},
                "arguments": [
                    {"role": "old", "literal": "designer"},
                    {"role": "new", "literal": "PM"},
                ],
                "evidence": [{"relation": "supports"}],
            },
            (deterministic, support),
        )
        self.assertEqual(decision.update.to_status, "needs_confirmation")


if __name__ == "__main__":
    unittest.main()
