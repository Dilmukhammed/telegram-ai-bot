from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from memory.eval.subjects import (
    CapturedOutputSubject,
    EvalContext,
    PR1IngestionSubject,
    PR3ExtractionSubject,
    PR4VerificationSubject,
    SubjectOutputError,
    create_subject,
)
from memory.eval.loader import load_fixture
from memory.eval.runner import _default_match_case


class CapturedOutputSubjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_loads_strict_versioned_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "case-1.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "fixture_id": "case-1",
                        "mentions": [{"mention_id": "m1"}],
                        "candidates": [],
                        "usage": {"input_tokens": 10},
                    }
                ),
                encoding="utf-8",
            )
            output = await CapturedOutputSubject(tmp).run(
                {"fixture_id": "case-1"},
                EvalContext(),
            )
        self.assertEqual(output.fixture_id, "case-1")
        self.assertEqual(output.mentions[0]["mention_id"], "m1")
        self.assertEqual(output.usage["input_tokens"], 10)

    async def test_rejects_unknown_fields(self) -> None:
        subject = CapturedOutputSubject(
            {
                "case-1": {
                    "schema_version": "1",
                    "fixture_id": "case-1",
                    "mentions": [],
                    "candidates": [],
                    "unexpected": True,
                }
            }
        )
        with self.assertRaises(SubjectOutputError):
            await subject.run({"fixture_id": "case-1"}, EvalContext())


class PR1IngestionSubjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_live_and_catchup_ingestion_with_baseline(self) -> None:
        case = {
            "fixture_id": "ingestion-live-catchup",
            "users": [{"user_alias": "u1", "user_id": 701}],
            "baseline_events": [
                {
                    "event_id": "old",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": "historical",
                    "content_type": "text",
                    "occurred_at": "2026-07-10T08:00:00+00:00",
                }
            ],
            "events": [
                {
                    "event_id": "m1",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": "live message",
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:00:00+00:00",
                },
                {
                    "event_id": "t1",
                    "kind": "tool_result",
                    "user_alias": "u1",
                    "tool_name": "echo.test",
                    "payload_kind": "result",
                    "payload_json": '{"ok":true}',
                    "ok": True,
                    "cached": False,
                    "occurred_at": "2026-07-10T09:01:00+00:00",
                    "delivery": "catchup",
                },
            ],
        }
        output = await PR1IngestionSubject().run(
            case,
            EvalContext(
                timeout_seconds=5.0,
                poll_interval_seconds=0.02,
                text_segment_chars=100,
                text_segment_overlap=10,
            ),
        )

        self.assertEqual(len(output.sources), 2)
        self.assertEqual({item["source_type"] for item in output.sources}, {"chat_message", "tool_result"})
        self.assertEqual(len(output.source_versions), 2)
        self.assertEqual(len(output.jobs), 2)
        self.assertTrue(all(item["status"] == "done" for item in output.jobs))
        self.assertEqual(len(output.segments), 2)
        self.assertNotIn(
            "historical",
            {item["text"] for item in output.segments},
        )
        self.assertTrue(output.pointer_checks)
        self.assertTrue(all(item["owner_ok"] for item in output.pointer_checks))
        self.assertTrue(all(item["dereference_ok"] for item in output.pointer_checks))
        self.assertTrue(
            all(item["text_ok"] in {None, True} for item in output.pointer_checks)
        )
        self.assertTrue(output.metadata["file_backed"])


class _EvalExtractionModel:
    model_profile = "summarize"

    async def generate(self, messages, *, structured_schema=None):
        _ = structured_schema
        return json.dumps(
            {
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
                            "speaker_ref": None,
                        },
                        "temporal": None,
                        "status": "proposed",
                        "evidence": [
                            {
                                "relation": "supports",
                                "exact_quote": "Иван работает в Acme.",
                                "char_start": 0,
                                "char_end": 21,
                            }
                        ],
                        "canonical_hint": None,
                    }
                ],
            },
            ensure_ascii=False,
        )


class PR3ExtractionSubjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_checked_in_relation_fixture_scores_with_runtime_ids(self) -> None:
        fixture = load_fixture(
            Path("memory/eval/fixtures/text_v1/cases/ru_relation_001.json")
        )
        output = await PR3ExtractionSubject(_EvalExtractionModel()).run(
            fixture,
            EvalContext(timeout_seconds=5.0, poll_interval_seconds=0.02),
        )
        scored = _default_match_case(fixture, output)
        self.assertEqual(scored["metrics"]["mention_precision"]["numerator"], 2)
        self.assertEqual(scored["metrics"]["candidate_precision"]["numerator"], 1)
        self.assertEqual(scored["failures"], [])

    async def test_real_ingestion_worker_and_extraction_are_collected(self) -> None:
        case = {
            "fixture_id": "pr3-relation",
            "users": [{"user_alias": "u1", "user_id": 801}],
            "events": [
                {
                    "event_id": "m1",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": "Иван работает в Acme.",
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:00:00+00:00",
                }
            ],
        }
        output = await PR3ExtractionSubject(_EvalExtractionModel()).run(
            case,
            EvalContext(timeout_seconds=5.0, poll_interval_seconds=0.02),
        )
        self.assertEqual(len(output.sources), 1)
        self.assertEqual({item["stage"] for item in output.jobs}, {"normalize_text", "candidate_extract"})
        self.assertTrue(all(item["status"] == "done" for item in output.jobs))
        self.assertEqual(len(output.mentions), 2)
        self.assertEqual(len(output.candidates), 1)
        self.assertEqual(output.mentions[0]["source_event"], "m1")
        self.assertEqual(output.candidates[0]["evidence"][0]["source_event"], "m1")
        self.assertEqual(output.metadata["subject_type"], "extraction")

    def test_factory_requires_explicit_network_permission(self) -> None:
        with self.assertRaises(ValueError):
            create_subject("extraction", allow_network=False)


class _EvalVerificationModel:
    def __init__(self, profile: str) -> None:
        self.model_profile = profile

    async def generate(self, messages, *, structured_schema=None):
        _ = messages, structured_schema
        return json.dumps(
            {
                "schema_version": "1",
                "verdict": "supported",
                "evidence_directness": "direct",
                "scope_errors": [],
                "ambiguities": [],
                "missing_context": [],
                "corrected_candidate": None,
            }
        )


class PR4VerificationSubjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_relation_fixture_runs_verification_subject(self) -> None:
        fixture = load_fixture(
            Path("memory/eval/fixtures/text_v1/cases/ru_relation_001.json")
        )
        output = await PR4VerificationSubject(
            _EvalExtractionModel(),
            _EvalVerificationModel("checker"),
            _EvalVerificationModel("agent"),
        ).run(
            fixture,
            EvalContext(timeout_seconds=5.0, poll_interval_seconds=0.02),
        )
        self.assertEqual(output.metadata["subject_type"], "verification")
        self.assertEqual(
            {item["stage"] for item in output.jobs},
            {"normalize_text", "candidate_extract", "candidate_verify"},
        )
        self.assertEqual(output.candidates[0]["status"], "proposed")
        self.assertEqual(
            output.candidates[0]["verification_status"],
            "ready_for_resolution",
        )
        self.assertEqual(
            {item["role"] for item in output.verdicts},
            {"deterministic", "support"},
        )
        scored = _default_match_case(fixture, output)
        self.assertEqual(scored["metrics"]["verification_recall"]["numerator"], 1)
        self.assertEqual(scored["metrics"]["verification_recall"]["denominator"], 1)
        self.assertEqual(
            scored["metrics"]["verification_job_completion"]["numerator"], 1
        )
        self.assertEqual(
            scored["metrics"]["verification_job_completion"]["denominator"], 1
        )
        self.assertTrue(scored["verification_trace"])
        self.assertIn("raw_output", scored["verification_trace"][0])
        self.assertIn(
            "verification_fixtures_reviewed",
            scored["metrics"],
        )

    def test_factory_requires_explicit_network_permission(self) -> None:
        with self.assertRaises(ValueError):
            create_subject("verification", allow_network=False)


if __name__ == "__main__":
    unittest.main()
