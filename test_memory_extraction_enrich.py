from __future__ import annotations

import unittest

from memory.extraction.enrich import enrich_extraction_payload, is_slim_extraction_payload
from memory.extraction.parser import parse_extraction_output


TEXT = "Иван работает в Acme."


class ExtractionEnrichTests(unittest.TestCase):
    def test_detects_slim_payload(self) -> None:
        slim = {
            "abstain": False,
            "mentions": [
                {"mention_type": "person", "surface_text": "Иван"},
                {"mention_type": "organization", "surface_text": "Acme"},
            ],
            "candidates": [
                {
                    "kind": "relation",
                    "schema_name": "works_at",
                    "arguments": [
                        {"role": "person", "mention_surface": "Иван"},
                        {"role": "organization", "mention_surface": "Acme"},
                    ],
                    "polarity": "positive",
                    "epistemic": {
                        "mode": "asserted",
                        "speaker_commitment": "certain",
                    },
                    "evidence": [{"relation": "supports", "quote": TEXT}],
                }
            ],
        }
        self.assertTrue(is_slim_extraction_payload(slim))

    def test_enrich_fills_offsets_refs_and_status(self) -> None:
        slim = {
            "abstain": False,
            "mentions": [],
            "candidates": [
                {
                    "kind": "preference",
                    "schema_name": "likes_music",
                    "arguments": [
                        {"role": "subject", "literal": "self"},
                        {"role": "value", "literal": "jazz"},
                    ],
                    "polarity": "unknown",
                    "epistemic": {
                        "mode": "asserted",
                        "speaker_commitment": "probable",
                    },
                    "evidence": [{"relation": "supports", "quote": "I probably prefer jazz."}],
                }
            ],
        }
        parsed = parse_extraction_output(slim, segment_text="I probably prefer jazz.")
        self.assertEqual(parsed.candidates[0].status.value, "needs_confirmation")
        self.assertTrue(parsed.candidates[0].epistemic.needs_confirmation)
        self.assertEqual(parsed.candidates[0].evidence[0].char_start, 0)
        self.assertEqual(parsed.candidates[0].canonical_hint, "likes_music:self:jazz")

    def test_enrich_maps_speaker_surface_to_mention_ref(self) -> None:
        segment = "Коллега думает, что Иван уволился."
        slim = {
            "abstain": False,
            "mentions": [
                {"mention_type": "person", "surface_text": "Коллега", "normalized_hint": "коллега"},
                {"mention_type": "person", "surface_text": "Иван"},
            ],
            "candidates": [
                {
                    "kind": "event",
                    "schema_name": "left_job",
                    "arguments": [{"role": "person", "mention_surface": "Иван"}],
                    "polarity": "unknown",
                    "epistemic": {
                        "mode": "reported",
                        "speaker_commitment": "possible",
                        "speaker_ref": "Коллега",
                    },
                    "evidence": [{"relation": "supports", "quote": segment}],
                }
            ],
        }
        parsed = parse_extraction_output(slim, segment_text=segment)
        self.assertEqual(parsed.candidates[0].epistemic.speaker_ref, "m1")

    def test_full_payload_still_parses(self) -> None:
        full = {
            "schema_version": "1",
            "abstain": True,
            "mentions": [],
            "candidates": [],
        }
        self.assertFalse(is_slim_extraction_payload(full))
        parsed = parse_extraction_output(full, segment_text=TEXT)
        self.assertTrue(parsed.abstain)


if __name__ == "__main__":
    unittest.main()
