from __future__ import annotations

import unittest
from dataclasses import dataclass

from memory.eval.gates import (
    DEFAULT_GATE_PATH,
    evaluate_gates,
    gate_config_hash,
    load_gate_config,
    parse_gate_config,
)
from memory.eval.matching import (
    FAILURE_CODES,
    candidate_difference_codes,
    candidate_matches,
    failure_codes_for_match,
    find_forbidden_matches,
    match_candidates,
    match_mentions,
    match_one_to_one,
    partial_pattern_matches,
)
from memory.eval.metrics import (
    Metric,
    abstention_accuracy,
    aggregate_metrics,
    metrics_from_match,
    precision_recall_f1,
    wilson_interval,
)


@dataclass(frozen=True)
class Mention:
    mention_id: str
    source_event: str
    mention_type: str
    surface_text: str
    char_start: int
    char_end: int


def _candidate(**overrides):
    candidate = {
        "candidate_ref": "gold",
        "kind": "relation",
        "schema_name": "works_at",
        "schema_version": "1",
        "arguments": [
            {"role": "person", "mention_ref": "ivan"},
            {"role": "organization", "mention_ref": "acme"},
        ],
        "attributes": {"durable": True},
        "polarity": "unknown",
        "epistemic": {
            "mode": "asserted",
            "speaker_commitment": "uncertain",
            "scope": "proposition",
            "alternatives": [],
            "needs_confirmation": True,
        },
        "temporal": None,
        "status": "needs_confirmation",
        "evidence": [
            {
                "source_event": "m1",
                "relation": "supports_uncertainty",
                "exact_quote": "not sure Ivan works at Acme",
                "char_start": 2,
                "char_end": 33,
            }
        ],
    }
    candidate.update(overrides)
    return candidate


def _gate_config():
    return {
        "schema_version": "1",
        "gate_id": "unit",
        "gate_version": "1",
        "pack_id": "unit",
        "pack_version": "1",
        "pack_hash": "abc",
        "subject_type": "all",
        "gates": [
            {
                "metric": "quality",
                "comparison": "gte",
                "threshold": 0.9,
                "active": True,
            },
            {
                "metric": "future_quality",
                "comparison": "gte",
                "threshold": 1.0,
                "active": False,
            },
        ],
        "hard_zero_failure_codes": ["forbidden_candidate"],
        "minimum_slice_counts": {"language:ru": 1},
    }


class MatchingTests(unittest.TestCase):
    def test_perfect_mentions_accept_mapping_and_dataclass(self):
        expected = [
            Mention("gold", "m1", "person", "Иван", 0, 4),
        ]
        actual = [
            {
                "mention_id": "runtime",
                "source_event": "m1",
                "mention_type": "person",
                "surface_text": "Иван",
                "char_start": 0,
                "char_end": 4,
            }
        ]
        result = match_mentions(expected, actual)
        self.assertTrue(result.perfect)
        self.assertEqual((result.true_positives, result.false_positives, result.false_negatives), (1, 0, 0))

    def test_duplicate_actual_is_unexpected(self):
        mention = {
            "source_event": "m1",
            "mention_type": "person",
            "surface_text": "Ivan",
            "char_start": 0,
            "char_end": 4,
        }
        result = match_mentions([mention], [mention, dict(mention)])
        self.assertEqual(result.true_positives, 1)
        self.assertEqual(result.false_positives, 1)
        self.assertEqual(result.unexpected_actual, (1,))
        self.assertEqual(
            failure_codes_for_match(
                result,
                missing_code="mention_missing",
                unexpected_code="mention_unexpected",
            ),
            ("mention_unexpected",),
        )

    def test_maximum_one_to_one_resolves_ambiguity(self):
        expected = [{"x": 1}, {"x": 1, "y": 2}]
        actual = [{"x": 1, "y": 2}, {"x": 1, "z": 3}]
        result = match_one_to_one(expected, actual, partial_pattern_matches)
        self.assertTrue(result.perfect)
        self.assertEqual(result.true_positives, 2)

    def test_candidate_signature_is_semantic_and_strict(self):
        expected = _candidate()
        actual = _candidate(
            candidate_ref="runtime",
            arguments=list(reversed(expected["arguments"])),
            provider_metadata={"model": "ignored"},
        )
        self.assertTrue(candidate_matches(expected, actual))
        actual["attributes"] = {"durable": True, "confidence": "high"}
        self.assertFalse(candidate_matches(expected, actual))
        expected["allow_extra_attributes"] = True
        self.assertTrue(candidate_matches(expected, actual))

    def test_candidate_duplicate_is_false_positive(self):
        expected = [_candidate()]
        actual = [_candidate(candidate_ref="one"), _candidate(candidate_ref="two")]
        result = match_candidates(expected, actual)
        self.assertEqual((result.true_positives, result.false_positives, result.false_negatives), (1, 1, 0))

    def test_forbidden_partial_patterns_match_independently(self):
        pattern = {
            "kind": "relation",
            "schema_name": "works_at",
            "polarity": "positive",
            "arguments": [{"role": "person", "mention_ref": "ivan"}],
        }
        actual = [
            _candidate(polarity="positive"),
            _candidate(polarity="unknown"),
        ]
        matches = find_forbidden_matches([pattern], actual)
        self.assertEqual(len(matches), 1)
        hit = matches[0]
        self.assertEqual((hit.pattern_index, hit.actual_index), (0, 0))

    def test_semantic_candidate_failures_have_specific_codes(self):
        expected = _candidate(
            polarity="negative",
            temporal={"valid_at": "2026-07-10"},
            speaker_alias="u1",
        )
        actual = _candidate(
            polarity="positive",
            epistemic={
                "mode": "asserted",
                "speaker_commitment": "certain",
                "scope": "proposition",
                "alternatives": [],
                "needs_confirmation": False,
            },
            temporal=None,
            speaker_alias="u2",
            evidence=[],
        )
        self.assertEqual(
            candidate_difference_codes(expected, actual),
            (
                "missing_evidence",
                "lost_negation",
                "uncertainty_flattened",
                "wrong_speaker",
                "temporal_mismatch",
            ),
        )

    def test_failure_codes_are_stable(self):
        self.assertEqual(len(FAILURE_CODES), len(set(FAILURE_CODES)))
        self.assertIn("lost_negation", FAILURE_CODES)
        self.assertIn("uncertainty_flattened", FAILURE_CODES)
        self.assertIn("wrong_speaker", FAILURE_CODES)
        self.assertIn("temporal_mismatch", FAILURE_CODES)


class MetricTests(unittest.TestCase):
    def test_precision_recall_f1_preserve_raw_counts(self):
        metrics = precision_recall_f1(3, 1, 2)
        self.assertEqual((metrics.precision.numerator, metrics.precision.denominator), (3, 4))
        self.assertEqual((metrics.recall.numerator, metrics.recall.denominator), (3, 5))
        self.assertEqual((metrics.f1.numerator, metrics.f1.denominator), (6, 9))
        self.assertAlmostEqual(metrics.precision.value, 0.75)
        self.assertAlmostEqual(metrics.recall.value, 0.6)
        self.assertAlmostEqual(metrics.f1.value, 2 / 3)

    def test_match_metrics_penalize_missing_and_extra(self):
        result = match_one_to_one([1, 2], [1, 3])
        metrics = metrics_from_match(result)
        self.assertEqual(metrics.precision, Metric(1, 2))
        self.assertEqual(metrics.recall, Metric(1, 2))
        self.assertEqual(metrics.f1, Metric(2, 4))

    def test_micro_macro_and_slice_denominators(self):
        report = aggregate_metrics(
            [
                {
                    "fixture_id": "a",
                    "language": "ru",
                    "slice_tags": ["negation", "critical"],
                    "metrics": {"accuracy": Metric(1, 1)},
                },
                {
                    "fixture_id": "b",
                    "language": "en",
                    "slice_tags": ["negation"],
                    "metrics": {"accuracy": {"numerator": 1, "denominator": 3}},
                },
                {
                    "fixture_id": "c",
                    "language": "en",
                    "slice_tags": ["abstention"],
                    "metrics": {"accuracy": Metric(0, 0)},
                },
            ]
        )
        aggregate = report.metrics["accuracy"]
        self.assertEqual(aggregate.micro, Metric(2, 4))
        self.assertEqual(aggregate.macro.numerator, 1 + (1 / 3))
        self.assertEqual(aggregate.macro.denominator, 2)
        self.assertEqual(
            report.slices["slice_tags"]["negation"]["accuracy"].micro,
            Metric(2, 4),
        )
        self.assertEqual(
            report.slices["language"]["en"]["accuracy"].macro.denominator,
            1,
        )

    def test_wilson_interval_is_deterministic(self):
        interval = wilson_interval(5, 10)
        self.assertAlmostEqual(interval.lower, 0.236593090512564, places=14)
        self.assertAlmostEqual(interval.upper, 0.763406909487436, places=14)
        self.assertEqual(interval, wilson_interval(5, 10))

    def test_abstention_accuracy(self):
        self.assertEqual(
            abstention_accuracy([(True, 0), (True, 1), (False, 2)]),
            Metric(2, 3),
        )


class GateTests(unittest.TestCase):
    def test_versioned_loader_and_hash_are_stable(self):
        loaded = load_gate_config(DEFAULT_GATE_PATH)
        self.assertEqual(loaded.schema_version, "1")
        self.assertEqual(loaded.config_hash, gate_config_hash(loaded))
        reordered = dict(reversed(list(_gate_config().items())))
        self.assertEqual(
            gate_config_hash(_gate_config()),
            gate_config_hash(reordered),
        )

    def test_only_active_gates_are_evaluated(self):
        config = parse_gate_config(_gate_config())
        evaluation = evaluate_gates(
            config,
            {"quality": Metric(9, 10)},
            slice_counts={"language:ru": 1},
        )
        self.assertTrue(evaluation.passed)
        self.assertNotIn("future_quality", {result.name for result in evaluation.results})

    def test_missing_metric_and_hard_zero_fail(self):
        evaluation = evaluate_gates(
            _gate_config(),
            {},
            failure_codes=[{"code": "forbidden_candidate"}],
            slice_counts={},
        )
        self.assertFalse(evaluation.passed)
        names = {result.name for result in evaluation.failed}
        self.assertEqual(
            names,
            {"quality", "failure_code:forbidden_candidate", "slice_count:language:ru"},
        )


if __name__ == "__main__":
    unittest.main()
