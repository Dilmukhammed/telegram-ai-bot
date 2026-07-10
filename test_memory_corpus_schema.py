"""Integrity checks for the generated memory corpus pack."""

from __future__ import annotations

import unittest

from eval_memory_corpus.adapter import scenarios_from_pack
from eval_memory_corpus.schema import DEFAULT_PACK_PATH, load_pack


class MemoryCorpusSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pack = load_pack(DEFAULT_PACK_PATH)

    def test_scale_targets(self) -> None:
        self.assertGreaterEqual(len(self.pack.sessions), 200)
        self.assertGreaterEqual(len(self.pack.cases), 1000)
        self.assertGreaterEqual(len(self.pack.cases_for_tier("smoke")), 30)

    def test_unique_session_slugs(self) -> None:
        slugs = [session.slug for session in self.pack.sessions]
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_unique_case_ids(self) -> None:
        ids = [case.id for case in self.pack.cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_unique_markers(self) -> None:
        markers = [fact.marker for session in self.pack.sessions for fact in session.facts]
        self.assertEqual(len(markers), len(set(markers)), "duplicate MEMEVAL markers")

    def test_cases_resolve_seed_sessions(self) -> None:
        by_slug = self.pack.session_by_slug()
        for case in self.pack.cases:
            self.assertTrue(case.seed_sessions, msg=case.id)
            for slug in case.seed_sessions:
                self.assertIn(slug, by_slug, msg=f"{case.id} missing session {slug}")
            if case.expected_session_slug:
                self.assertIn(case.expected_session_slug, by_slug, msg=case.id)
                self.assertIn(case.expected_session_slug, case.seed_sessions, msg=case.id)

    def test_contradiction_pairs(self) -> None:
        by_slug = self.pack.session_by_slug()
        contradiction_cases = [
            case for case in self.pack.cases if case.difficulty == "contradiction"
        ]
        self.assertGreaterEqual(len(contradiction_cases), 80)
        for case in contradiction_cases:
            self.assertTrue(case.must_include, msg=case.id)
            self.assertTrue(case.must_not_include, msg=case.id)
            session = by_slug[case.expected_session_slug or case.seed_sessions[0]]
            facts = {fact.id: fact for fact in session.facts}
            active = [fact for fact in session.facts if fact.status == "active"]
            superseded = [fact for fact in session.facts if fact.status == "superseded"]
            self.assertTrue(superseded, msg=session.slug)
            for old in superseded:
                self.assertIsNotNone(old.superseded_by, msg=old.id)
                self.assertIn(old.superseded_by, facts, msg=old.id)
                newer = facts[old.superseded_by]
                self.assertEqual(newer.status, "active")
            for marker in case.must_include:
                self.assertTrue(
                    any(fact.marker == marker and fact.status == "active" for fact in active),
                    msg=f"{case.id} missing active {marker}",
                )
            for marker in case.must_not_include:
                self.assertTrue(
                    any(fact.marker == marker and fact.status == "superseded" for fact in superseded),
                    msg=f"{case.id} missing superseded {marker}",
                )

    def test_adapter_smoke_scenarios(self) -> None:
        scenarios = scenarios_from_pack(self.pack, tier="smoke")
        self.assertGreaterEqual(len(scenarios), 30)
        self.assertTrue(all(callable(item.seed) for item in scenarios))

    def test_shard_partition(self) -> None:
        full = scenarios_from_pack(self.pack, tier="full")
        shards = [
            scenarios_from_pack(self.pack, tier="full", shard=(i, 8))
            for i in range(8)
        ]
        merged_ids = [item.case.id for shard in shards for item in shard]
        self.assertEqual(sorted(merged_ids), sorted(item.case.id for item in full))


if __name__ == "__main__":
    unittest.main()
