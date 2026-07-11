"""Focused tests for deterministic graph-memory evaluation execution."""

from __future__ import annotations

import asyncio
import json
import socket
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from memory.eval.reports import BaselineCompatibilityError, compare_baseline
from memory.eval.gates import parse_gate_config
from memory.eval.loader import load_fixture
from memory.eval.matching import to_plain
from memory.eval.runner import (
    EXIT_GATE_FAILURE,
    EXIT_HARNESS_ERROR,
    EXIT_SUCCESS,
    NetworkDeniedError,
    RunnerConfig,
    _default_match_case,
    derive_case_seed,
    parse_shard,
    run_evaluation,
    select_fixtures,
)


def _fixture(
    fixture_id: str,
    *,
    tier: str = "smoke",
    language: str = "en",
    tags: tuple[str, ...] = ("direct",),
    criticality: str = "normal",
) -> dict[str, object]:
    return {
        "fixture_id": fixture_id,
        "title": fixture_id,
        "tier": tier,
        "language": language,
        "criticality": criticality,
        "slice_tags": list(tags),
        "reference_time": "2026-07-10T12:00:00+05:00",
        "timezone": "Asia/Tashkent",
    }


class PassingSubject:
    subject_id = "fake"
    pipeline_id = "fake-v1"
    processor_version = "1"

    async def run(self, case, context):
        await asyncio.sleep(0)
        return {
            "passed": True,
            "metrics": {"accuracy": {"numerator": 1, "denominator": 1}},
            "actual_signatures": [f"{case['fixture_id']}:{context.seed}"],
        }


class MemoryEvalSelectionTests(unittest.TestCase):
    def test_candidate_matching_treats_likes_as_prefers_alias(self) -> None:
        from memory.eval.matching import candidate_matches

        expected = {
            "kind": "preference", "schema_name": "prefers", "schema_version": "1",
            "polarity": "positive", "arguments": [], "attributes": {},
            "epistemic": {}, "temporal": None, "status": "proposed", "evidence": [],
        }
        self.assertTrue(candidate_matches(expected, {**expected, "schema_name": "likes"}))

    def test_filter_sort_and_shard_are_deterministic(self) -> None:
        fixtures = [
            _fixture("c", language="ru", tags=("direct", "critical")),
            _fixture("a", language="ru", tags=("direct", "critical")),
            _fixture("b", tier="full", language="en"),
            _fixture("d", language="ru", tags=("other",)),
        ]
        selected = select_fixtures(
            fixtures,
            tier="smoke",
            language="ru",
            slice_tags=("direct",),
            shard=(1, 2),
        )
        self.assertEqual([item["fixture_id"] for item in selected], ["c"])

    def test_candidate_matching_ignores_runtime_mention_ids(self) -> None:
        epistemic = {
            "mode": "asserted",
            "speaker_commitment": "certain",
            "scope": "proposition",
            "alternatives": [],
            "needs_confirmation": False,
            "speaker_ref": None,
        }
        evidence = [
            {
                "source_event": "m1",
                "relation": "supports",
                "exact_quote": "Иван",
                "char_start": 0,
                "char_end": 4,
            }
        ]
        expected_candidate = {
            "kind": "entity_attribute",
            "schema_name": "has_name",
            "schema_version": "1",
            "arguments": [
                {
                    "role": "person",
                    "mention_ref": "gold_ivan",
                    "literal": None,
                    "has_literal": False,
                }
            ],
            "attributes": {},
            "polarity": "positive",
            "epistemic": epistemic,
            "temporal": None,
            "status": "proposed",
            "evidence": evidence,
        }
        fixture = {
            "fixture_id": "runtime-ids",
            "expected": {
                "sources": [],
                "segments": [],
                "mentions": [
                    {
                        "mention_id": "gold_ivan",
                        "source_event": "m1",
                        "mention_type": "person",
                        "surface_text": "Иван",
                        "char_start": 0,
                        "char_end": 4,
                    }
                ],
                "candidates": [expected_candidate],
                "forbidden_candidates": [],
                "forbidden_sources": [],
                "forbidden_segments": [],
                "expect_abstention": False,
            },
        }
        actual_candidate = json.loads(json.dumps(expected_candidate))
        actual_candidate["arguments"][0]["mention_ref"] = "mmen_runtime_123"
        result = _default_match_case(
            fixture,
            {
                "fixture_id": "runtime-ids",
                "sources": [],
                "source_versions": [],
                "segments": [],
                "jobs": [],
                "pointer_checks": [],
                "mentions": [
                    {
                        "mention_id": "mmen_runtime_123",
                        "source_event": "m1",
                        "mention_type": "person",
                        "surface_text": "Иван",
                        "char_start": 0,
                        "char_end": 4,
                    }
                ],
                "candidates": [actual_candidate],
                "metadata": {"subject_type": "extraction"},
            },
        )
        self.assertEqual(result["metrics"]["candidate_precision"]["numerator"], 1)
        self.assertFalse(
            any(item["code"].startswith("candidate_") for item in result["failures"])
        )

    def test_candidate_matching_accepts_mention_surface_for_literal(self) -> None:
        fixture = load_fixture(
            Path("memory/eval/fixtures/text_v1/cases/ru_goal_008.json")
        )
        candidate = to_plain(fixture.expected.candidates[0])
        skill = next(item for item in candidate["arguments"] if item["role"] == "skill")
        skill.update(
            {
                "mention_ref": "mmen_python",
                "literal": None,
                "has_literal": False,
            }
        )
        result = _default_match_case(
            fixture,
            {
                "fixture_id": fixture.fixture_id,
                "sources": [],
                "source_versions": [],
                "segments": [],
                "jobs": [],
                "pointer_checks": [],
                "mentions": [
                    {
                        "mention_id": "mmen_python",
                        "source_event": "m1",
                        "mention_type": "concept",
                        "surface_text": "Python",
                        "char_start": 13,
                        "char_end": 19,
                    }
                ],
                "candidates": [candidate],
                "metadata": {"subject_type": "extraction"},
            },
        )
        self.assertEqual(result["metrics"]["candidate_precision"]["numerator"], 1)
        self.assertFalse(
            any(
                item["code"] in {"mention_unexpected", "candidate_missing", "candidate_unexpected"}
                for item in result["failures"]
            )
        )

    def test_full_tier_contains_smoke_and_full_cases(self) -> None:
        fixtures = [_fixture("smoke"), _fixture("full", tier="full")]
        self.assertEqual(
            [item["fixture_id"] for item in select_fixtures(fixtures, tier="full")],
            ["full", "smoke"],
        )

    def test_shards_reassemble_sorted_pack(self) -> None:
        fixtures = [_fixture(str(index)) for index in reversed(range(12))]
        all_ids = [
            item["fixture_id"] for item in select_fixtures(fixtures, tier="smoke")
        ]
        shard_ids = [
            item["fixture_id"]
            for shard_index in range(4)
            for item in select_fixtures(
                fixtures, tier="smoke", shard=(shard_index, 4)
            )
        ]
        self.assertEqual(sorted(shard_ids), sorted(all_ids))

    def test_seed_is_stable_and_case_specific(self) -> None:
        self.assertEqual(derive_case_seed("pack", "a"), derive_case_seed("pack", "a"))
        self.assertNotEqual(derive_case_seed("pack", "a"), derive_case_seed("pack", "b"))

    def test_invalid_shard_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            parse_shard("2/2")


class MemoryEvalRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_and_output_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            result = await run_evaluation(
                RunnerConfig(
                    tier="smoke",
                    concurrency=3,
                    output=output,
                    timeout_seconds=1,
                ),
                fixtures=[_fixture("z"), _fixture("a"), _fixture("m")],
                subject=PassingSubject(),
                pack={"pack_id": "text", "pack_version": "1", "pack_hash": "abc"},
            )
            self.assertEqual(result.exit_code, EXIT_SUCCESS)
            self.assertEqual(
                [case["fixture_id"] for case in result.cases], ["a", "m", "z"]
            )
            self.assertEqual(
                {path.name for path in result.artifacts.values()},
                {
                    "run_manifest.json",
                    "cases.jsonl",
                    "summary.json",
                    "report.md",
                    "junit.xml",
                },
            )
            jsonl_ids = [
                json.loads(line)["fixture_id"]
                for line in (output / "cases.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(jsonl_ids, ["a", "m", "z"])
            suite = ElementTree.parse(output / "junit.xml").getroot()
            self.assertEqual(len(suite.findall("testcase")), 3)

    async def test_gate_failure_returns_one(self) -> None:
        class FailingSubject(PassingSubject):
            async def run(self, case, context):
                return {
                    "passed": False,
                    "failures": [{"code": "candidate_missing", "message": "missing"}],
                }

        with tempfile.TemporaryDirectory() as temporary:
            result = await run_evaluation(
                RunnerConfig(output=Path(temporary), timeout_seconds=1),
                fixtures=[_fixture("failure")],
                subject=FailingSubject(),
                pack={"pack_hash": "abc"},
            )
        self.assertEqual(result.exit_code, EXIT_GATE_FAILURE)

    async def test_conventional_gate_adapter(self) -> None:
        gate_config = parse_gate_config(
            {
                "schema_version": "1",
                "gate_id": "runner-test",
                "gate_version": "1",
                "pack_id": "text",
                "pack_version": "1",
                "pack_hash": "abc",
                "subject_type": "all",
                "gates": [
                    {
                        "metric": "accuracy",
                        "comparison": "gte",
                        "threshold": 1.0,
                        "active": True,
                    }
                ],
                "hard_zero_failure_codes": [],
                "minimum_slice_counts": {},
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = await run_evaluation(
                RunnerConfig(output=Path(temporary), timeout_seconds=1),
                fixtures=[_fixture("gated")],
                subject=PassingSubject(),
                pack={"pack_id": "text", "pack_version": "1", "pack_hash": "abc"},
                gate_config=gate_config,
            )
        self.assertEqual(result.exit_code, EXIT_SUCCESS)
        self.assertTrue(all(gate["passed"] for gate in result.summary["gates"]))

    async def test_timeout_and_subject_exception_return_two(self) -> None:
        class SlowSubject(PassingSubject):
            async def run(self, case, context):
                await asyncio.sleep(1)

        class BrokenSubject(PassingSubject):
            async def run(self, case, context):
                raise RuntimeError("broken")

        for subject, expected_code in (
            (SlowSubject(), "subject_timeout"),
            (BrokenSubject(), "subject_error"),
        ):
            with self.subTest(expected_code), tempfile.TemporaryDirectory() as temporary:
                result = await run_evaluation(
                    RunnerConfig(
                        output=Path(temporary),
                        timeout_seconds=0.01,
                    ),
                    fixtures=[_fixture(expected_code)],
                    subject=subject,
                    pack={"pack_hash": "abc"},
                )
                self.assertEqual(result.exit_code, EXIT_HARNESS_ERROR)
                self.assertEqual(result.cases[0]["failures"][0]["code"], expected_code)

    async def test_junit_failure_messages_are_bounded(self) -> None:
        class VerboseSubject(PassingSubject):
            async def run(self, case, context):
                return {
                    "passed": False,
                    "failures": [
                        {"code": "candidate_missing", "message": "x" * 20_000}
                    ],
                }

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            await run_evaluation(
                RunnerConfig(output=output, timeout_seconds=1),
                fixtures=[_fixture("verbose")],
                subject=VerboseSubject(),
                pack={"pack_hash": "abc"},
            )
            failure = ElementTree.parse(output / "junit.xml").find(".//failure")
            self.assertIsNotNone(failure)
            assert failure is not None
            self.assertLessEqual(len(failure.attrib["message"]), 2_000)
            self.assertLessEqual(len(failure.text or ""), 2_000)

    async def test_network_is_denied_by_default(self) -> None:
        class NetworkSubject(PassingSubject):
            async def run(self, case, context):
                with self.assertRaises(NetworkDeniedError):
                    socket.create_connection(("example.com", 443), timeout=0.01)
                return {"passed": True}

            def __init__(self, test_case):
                self.assertRaises = test_case.assertRaises

        with tempfile.TemporaryDirectory() as temporary:
            result = await run_evaluation(
                RunnerConfig(output=Path(temporary), timeout_seconds=1),
                fixtures=[_fixture("offline")],
                subject=NetworkSubject(self),
                pack={"pack_hash": "abc"},
            )
        self.assertEqual(result.exit_code, EXIT_SUCCESS)
        self.assertFalse(result.manifest["network_allowed"])

    async def test_concurrency_is_bounded(self) -> None:
        class CountingSubject(PassingSubject):
            active = 0
            maximum = 0

            async def run(self, case, context):
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                await asyncio.sleep(0.01)
                self.active -= 1
                return {"passed": True}

        subject = CountingSubject()
        with tempfile.TemporaryDirectory() as temporary:
            await run_evaluation(
                RunnerConfig(
                    output=Path(temporary),
                    timeout_seconds=1,
                    concurrency=2,
                ),
                fixtures=[_fixture(str(index)) for index in range(6)],
                subject=subject,
                pack={"pack_hash": "abc"},
            )
        self.assertEqual(subject.maximum, 2)

    async def test_compatible_baseline_and_incompatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            baseline_dir = Path(temporary) / "baseline"
            current_dir = Path(temporary) / "current"
            first = await run_evaluation(
                RunnerConfig(output=baseline_dir, timeout_seconds=1),
                fixtures=[_fixture("a")],
                subject=PassingSubject(),
                pack={"pack_id": "text", "pack_version": "1", "pack_hash": "abc"},
            )
            second = await run_evaluation(
                RunnerConfig(
                    output=current_dir,
                    baseline=baseline_dir / "summary.json",
                    timeout_seconds=1,
                ),
                fixtures=[_fixture("a")],
                subject=PassingSubject(),
                pack={"pack_id": "text", "pack_version": "1", "pack_hash": "abc"},
            )
            self.assertEqual(first.exit_code, EXIT_SUCCESS)
            self.assertEqual(second.exit_code, EXIT_SUCCESS)
            incompatible = dict(first.summary)
            incompatible["compatibility"] = {
                **first.summary["compatibility"],
                "pack_hash": "different",
            }
            with self.assertRaises(BaselineCompatibilityError):
                compare_baseline(second.summary, incompatible)


if __name__ == "__main__":
    unittest.main()
