from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from memory.eval import (
    FixtureValidationError,
    canonical_pack_hash,
    load_pack,
    parse_fixture,
    parse_manifest,
    validate_pack_coverage,
)


def _fixture(
    fixture_id: str = "ru_relation_001",
    *,
    tier: str = "smoke",
    language: str = "ru",
    tags: list[str] | None = None,
) -> dict:
    text = "Иван работает в Acme."
    return {
        "schema_version": "1",
        "fixture_id": fixture_id,
        "title": "Synthetic employment relation",
        "tier": tier,
        "language": language,
        "criticality": "critical",
        "slice_tags": tags or ["relation"],
        "reference_time": "2026-07-10T12:00:00+05:00",
        "timezone": "Asia/Tashkent",
        "users": [
            {
                "user_alias": "u1",
                "user_id": 1001,
                "metadata": {"synthetic": True},
            }
        ],
        "events": [
            {
                "event_id": "m1",
                "kind": "chat_message",
                "user_alias": "u1",
                "role": "user",
                "content": text,
                "content_type": "text",
                "occurred_at": "2026-07-10T09:00:00+05:00",
                "metadata": {},
            }
        ],
        "expected": {
            "sources": [
                {
                    "source_event": "m1",
                    "source_type": "chat_message",
                    "source_ref_alias": "m1",
                    "authority_class": "user_assertion",
                    "content_hash_rule": "sha256_utf8",
                    "source_version_count": 1,
                }
            ],
            "segments": [
                {
                    "source_event": "m1",
                    "segment_type": "text",
                    "ordinal": 0,
                    "text": text,
                    "normalizer_version": "1",
                    "pointer": {
                        "source_event": "m1",
                        "char_start": 0,
                        "char_end": len(text),
                    },
                }
            ],
            "mentions": [
                {
                    "mention_id": "mention_ivan",
                    "source_event": "m1",
                    "mention_type": "person",
                    "surface_text": "Иван",
                    "char_start": 0,
                    "char_end": 4,
                    "normalized_hint": "Иван",
                    "pointer": {
                        "source_event": "m1",
                        "char_start": 0,
                        "char_end": 4,
                    },
                },
                {
                    "mention_id": "mention_acme",
                    "source_event": "m1",
                    "mention_type": "organization",
                    "surface_text": "Acme",
                    "char_start": 16,
                    "char_end": 20,
                    "normalized_hint": "Acme",
                    "pointer": {
                        "source_event": "m1",
                        "char_start": 16,
                        "char_end": 20,
                    },
                },
            ],
            "candidates": [
                {
                    "candidate_ref": "candidate_works_at",
                    "kind": "relation",
                    "schema_name": "works_at",
                    "schema_version": "1",
                    "arguments": [
                        {"role": "person", "mention_ref": "mention_ivan"},
                        {
                            "role": "organization",
                            "mention_ref": "mention_acme",
                        },
                    ],
                    "attributes": {},
                    "polarity": "positive",
                    "epistemic": {
                        "mode": "asserted",
                        "speaker_commitment": "certain",
                        "scope": "proposition",
                        "alternatives": [],
                        "needs_confirmation": False,
                    },
                    "temporal": None,
                    "status": "proposed",
                    "evidence": [
                        {
                            "source_event": "m1",
                            "relation": "supports",
                            "exact_quote": "Иван работает в Acme",
                            "char_start": 0,
                            "char_end": 20,
                        }
                    ],
                }
            ],
            "forbidden_candidates": [],
            "expect_abstention": False,
        },
        "review": {
            "status": "reviewed",
            "reviewed_by": "human-reviewer",
            "reviewed_at": "2026-07-10T12:30:00+05:00",
            "notes": [],
        },
    }


def _manifest(paths: list[str]) -> dict:
    return {
        "schema_version": "1",
        "pack_id": "test_text_v1",
        "pack_version": "1",
        "fixtures": paths,
        "coverage": {
            "fixture_count": len(paths),
            "smoke_count": 1,
            "language_minimums": {"ru": 1, "en": 1},
            "slice_minimums": {"relation": 1, "hard_negative": 1},
            "multi_turn_minimum": 0,
            "hard_negative_minimum": 1,
            "require_reviewed": True,
        },
    }


class FixtureSchemaTests(unittest.TestCase):
    def test_valid_fixture_is_recursively_immutable(self) -> None:
        fixture = parse_fixture(_fixture())
        self.assertEqual(fixture.expected.mentions[0].surface_text, "Иван")
        with self.assertRaises(FrozenInstanceError):
            fixture.title = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            fixture.users[0].metadata["changed"] = True  # type: ignore[index]

    def test_rejects_unknown_fields_at_nested_levels(self) -> None:
        value = _fixture()
        value["events"][0]["surprise"] = True
        with self.assertRaisesRegex(FixtureValidationError, "unknown fields"):
            parse_fixture(value)

    def test_rejects_unknown_schema_enum_and_naive_datetime(self) -> None:
        for path, value in (
            (("schema_version",), "2"),
            (("tier",), "quick"),
            (("reference_time",), "2026-07-10T12:00:00"),
        ):
            fixture = _fixture()
            fixture[path[0]] = value
            with self.subTest(path=path), self.assertRaises(FixtureValidationError):
                parse_fixture(fixture)

    def test_rejects_duplicate_and_dangling_symbolic_references(self) -> None:
        duplicate = _fixture()
        duplicate["events"].append(copy.deepcopy(duplicate["events"][0]))
        with self.assertRaisesRegex(FixtureValidationError, "duplicate symbolic"):
            parse_fixture(duplicate)

        dangling = _fixture()
        dangling["expected"]["candidates"][0]["arguments"][0][
            "mention_ref"
        ] = "missing"
        with self.assertRaisesRegex(FixtureValidationError, "dangling mention"):
            parse_fixture(dangling)

    def test_rejects_missing_users_and_symbolic_sources(self) -> None:
        no_users = _fixture()
        no_users["users"] = []
        with self.assertRaisesRegex(FixtureValidationError, "synthetic user"):
            parse_fixture(no_users)

        no_events = _fixture()
        no_events["events"] = []
        with self.assertRaisesRegex(FixtureValidationError, "symbolic source event"):
            parse_fixture(no_events)

    def test_rejects_bad_unicode_span_pointer_and_exact_quote(self) -> None:
        for mutate in (
            lambda value: value["expected"]["mentions"][0].update(char_end=3),
            lambda value: value["expected"]["mentions"][0]["pointer"].update(
                char_start=1
            ),
            lambda value: value["expected"]["candidates"][0]["evidence"][0].update(
                exact_quote="wrong"
            ),
        ):
            value = _fixture()
            mutate(value)
            with self.assertRaises(FixtureValidationError):
                parse_fixture(value)

    def test_expected_segment_accepts_whole_source_pointer(self) -> None:
        value = _fixture()
        value["expected"]["segments"][0]["pointer"] = {"source_event": "m1"}
        fixture = parse_fixture(value)
        self.assertIsNone(fixture.expected.segments[0].pointer.char_start)
        self.assertIsNone(fixture.expected.segments[0].pointer.char_end)

        value["expected"]["segments"][0]["pointer"] = {
            "source_event": "m1",
            "char_start": 0,
        }
        with self.assertRaisesRegex(FixtureValidationError, "provided together"):
            parse_fixture(value)

    def test_rejects_cross_user_evidence(self) -> None:
        value = _fixture()
        value["users"].append({"user_alias": "u2", "user_id": 1002})
        value["events"].append(
            {
                "event_id": "m2",
                "kind": "chat_message",
                "user_alias": "u2",
                "role": "user",
                "content": "Acme",
                "content_type": "text",
                "occurred_at": "2026-07-10T09:01:00+05:00",
                "metadata": {},
            }
        )
        evidence = value["expected"]["candidates"][0]["evidence"]
        evidence.append(
            {
                "source_event": "m2",
                "relation": "supports",
                "exact_quote": "Acme",
                "char_start": 0,
                "char_end": 4,
            }
        )
        with self.assertRaisesRegex(FixtureValidationError, "cross-user"):
            parse_fixture(value)

    def test_rejects_canonical_entity_ids(self) -> None:
        value = _fixture()
        value["expected"]["candidates"][0]["attributes"] = {
            "canonical_entity_id": "entity_123"
        }
        with self.assertRaisesRegex(FixtureValidationError, "entity IDs"):
            parse_fixture(value)

    def test_rejects_flattened_uncertainty(self) -> None:
        value = _fixture()
        epistemic = value["expected"]["candidates"][0]["epistemic"]
        epistemic["speaker_commitment"] = "uncertain"
        epistemic["needs_confirmation"] = True
        with self.assertRaisesRegex(FixtureValidationError, "unknown polarity"):
            parse_fixture(value)

        value = _fixture()
        epistemic = value["expected"]["candidates"][0]["epistemic"]
        epistemic["speaker_commitment"] = "probable"
        with self.assertRaisesRegex(FixtureValidationError, "unknown polarity"):
            parse_fixture(value)

    def test_reported_speaker_and_forbidden_records_are_strict(self) -> None:
        value = _fixture()
        epistemic = value["expected"]["candidates"][0]["epistemic"]
        epistemic.update(mode="reported", speaker_ref="mention_ivan")
        value["expected"]["forbidden_sources"] = [{"source_type": "tool_summary"}]
        value["expected"]["forbidden_segments"] = [{"segment_type": "tool_summary"}]
        fixture = parse_fixture(value)
        self.assertEqual(fixture.expected.candidates[0].epistemic.speaker_ref, "mention_ivan")
        self.assertEqual(fixture.expected.forbidden_sources[0].source_type, "tool_summary")

        value["expected"]["candidates"][0]["epistemic"]["speaker_ref"] = "missing"
        with self.assertRaisesRegex(FixtureValidationError, "dangling mention"):
            parse_fixture(value)

        value = _fixture()
        value["expected"]["forbidden_sources"] = [{"source_event": "missing"}]
        with self.assertRaisesRegex(FixtureValidationError, "dangling source event"):
            parse_fixture(value)

    def test_stage2_entity_attribute_kind_is_canonical(self) -> None:
        value = _fixture()
        value["expected"]["candidates"][0]["kind"] = "entity_attribute"
        fixture = parse_fixture(value)
        self.assertEqual(fixture.expected.candidates[0].kind.value, "entity_attribute")

        value["expected"]["candidates"][0]["kind"] = "attribute"
        with self.assertRaises(FixtureValidationError):
            parse_fixture(value)

    def test_rejects_abstention_with_candidates(self) -> None:
        value = _fixture()
        value["expected"]["expect_abstention"] = True
        with self.assertRaisesRegex(FixtureValidationError, "expected candidates"):
            parse_fixture(value)

    def test_rejects_expected_forbidden_semantic_overlap(self) -> None:
        value = _fixture()
        value["expected"]["forbidden_candidates"] = [
            {
                "kind": "relation",
                "schema_name": "works_at",
                "schema_version": "1",
                "polarity": "positive",
                "arguments": [
                    {"role": "person", "surface_text": "Иван"},
                    {"role": "organization", "surface_text": "Acme"},
                ],
            }
        ]
        with self.assertRaisesRegex(FixtureValidationError, "semantic signature"):
            parse_fixture(value)

    def test_review_envelope_is_strict(self) -> None:
        value = _fixture()
        value["review"]["reviewed_by"] = None
        with self.assertRaisesRegex(FixtureValidationError, "reviewed fixtures"):
            parse_fixture(value)

    def test_schema_artifact_is_strict_json_schema(self) -> None:
        schema_path = (
            Path(__file__).parent / "memory" / "eval" / "fixtures" / "schema_v1.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"], {"const": "1"})
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["$defs"]["candidate"]["additionalProperties"])


class PackLoaderTests(unittest.TestCase):
    def _write_pack(self, root: Path, manifest: dict) -> Path:
        cases = root / "cases"
        cases.mkdir()
        first = _fixture(tags=["relation"])
        second = _fixture(
            "en_hard_negative_001",
            tier="full",
            language="en",
            tags=["hard_negative"],
        )
        for name, value in (("a.json", first), ("b.json", second)):
            (cases / name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest_path

    def test_load_pack_validates_coverage_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_manifest = _manifest(["cases/a.json", "cases/b.json"])
            manifest_path = self._write_pack(root, raw_manifest)
            first_load = load_pack(manifest_path)

            raw_manifest["pack_hash"] = first_load.pack_hash
            manifest_path.write_text(json.dumps(raw_manifest), encoding="utf-8")
            second_load = load_pack(root)
            self.assertEqual(second_load.pack_hash, first_load.pack_hash)
            self.assertEqual(
                [case.fixture_id for case in second_load.fixtures],
                ["ru_relation_001", "en_hard_negative_001"],
            )

    def test_pack_hash_is_canonical_across_fixture_order(self) -> None:
        fixtures = [
            parse_fixture(_fixture()),
            parse_fixture(
                _fixture(
                    "en_hard_negative_001",
                    tier="full",
                    language="en",
                    tags=["hard_negative"],
                )
            ),
        ]
        manifest_a = parse_manifest(_manifest(["cases/a.json", "cases/b.json"]))
        manifest_b = parse_manifest(_manifest(["cases/b.json", "cases/a.json"]))
        self.assertEqual(
            canonical_pack_hash(manifest_a, fixtures),
            canonical_pack_hash(manifest_b, list(reversed(fixtures))),
        )

    def test_rejects_bad_declared_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _manifest(["cases/a.json", "cases/b.json"])
            manifest["pack_hash"] = "0" * 64
            path = self._write_pack(root, manifest)
            with self.assertRaisesRegex(FixtureValidationError, "canonical pack hash"):
                load_pack(path)

    def test_rejects_coverage_shortfall_and_draft_release_fixture(self) -> None:
        fixtures = [parse_fixture(_fixture())]
        requirements = parse_manifest(
            {
                **_manifest(["case.json"]),
                "coverage": {
                    **_manifest(["case.json"])["coverage"],
                    "fixture_count": 2,
                },
            }
        ).coverage
        with self.assertRaisesRegex(FixtureValidationError, "expected exactly 2"):
            validate_pack_coverage(fixtures, requirements)

        draft = _fixture()
        draft["review"] = {
            "status": "draft",
            "reviewed_by": None,
            "reviewed_at": None,
            "notes": [],
        }
        draft_fixture = parse_fixture(draft)
        reviewed_requirement = parse_manifest(
            {
                "schema_version": "1",
                "pack_id": "draft_check",
                "pack_version": "1",
                "fixtures": ["case.json"],
                "coverage": {
                    "fixture_count": 1,
                    "smoke_count": 1,
                    "language_minimums": {"ru": 1},
                    "slice_minimums": {"relation": 1},
                    "require_reviewed": True,
                },
            }
        ).coverage
        with self.assertRaisesRegex(FixtureValidationError, "draft fixtures"):
            validate_pack_coverage([draft_fixture], reviewed_requirement)

    def test_manifest_rejects_unknown_fields_and_escaping_paths(self) -> None:
        manifest = _manifest(["cases/a.json", "cases/b.json"])
        manifest["unknown"] = True
        with self.assertRaisesRegex(FixtureValidationError, "unknown fields"):
            parse_manifest(manifest)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            escaping = _manifest(["../outside.json", "cases/b.json"])
            path = self._write_pack(root, escaping)
            with self.assertRaisesRegex(FixtureValidationError, "pack directory"):
                load_pack(path)


class CheckedInCorpusTests(unittest.TestCase):
    def test_text_v1_has_exact_balanced_reviewed_corpus(self) -> None:
        root = Path(__file__).parent / "memory" / "eval" / "fixtures" / "text_v1"
        pack = load_pack(root)
        self.assertEqual(len(pack.fixtures), 64)
        self.assertEqual(sum(case.tier.value == "smoke" for case in pack.fixtures), 16)
        self.assertEqual(
            {
                language: sum(case.language.value == language for case in pack.fixtures)
                for language in ("ru", "en", "mixed")
            },
            {"ru": 32, "en": 28, "mixed": 4},
        )
        self.assertTrue(pack.manifest.coverage.require_reviewed)
        self.assertTrue(all(case.review.status.value == "reviewed" for case in pack.fixtures))
        self.assertEqual(
            pack.pack_hash,
            "cdd6197697b6d6120c3e1f6f79fb4a8fdca1fd7b2634b19305966a53968eb639",
        )


if __name__ == "__main__":
    unittest.main()
