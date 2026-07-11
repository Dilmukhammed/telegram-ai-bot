from __future__ import annotations

import json
import unittest

from memory.extraction.json_schemas import (
    SCHEMA_NAMES,
    extraction_output_schema,
    structured_response_format,
)
from memory.extraction.parser import parse_extraction_output
from memory.extraction.schemas import SpeakerCommitment


class ExtractionJsonSchemaTests(unittest.TestCase):
    def test_schema_names_cover_prompt_contract(self) -> None:
        self.assertIn("likes_music", SCHEMA_NAMES)
        self.assertIn("destination_choice", SCHEMA_NAMES)
        self.assertIn("date_of_birth", SCHEMA_NAMES)
        self.assertIn("prepare_demo", SCHEMA_NAMES)

    def test_structured_response_format_shape(self) -> None:
        payload = structured_response_format(name="extraction", strict=True)
        self.assertEqual(payload["type"], "json_schema")
        self.assertEqual(payload["json_schema"]["name"], "extraction")
        self.assertTrue(payload["json_schema"]["strict"])
        self.assertIn("properties", payload["json_schema"]["schema"])

    def test_probe_example_parses_against_schema_fields(self) -> None:
        raw = {
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
                        "speaker_commitment": SpeakerCommitment.PROBABLE.value,
                    },
                    "evidence": [
                        {
                            "relation": "supports",
                            "quote": "I probably prefer jazz.",
                        }
                    ],
                }
            ],
        }
        parsed = parse_extraction_output(raw, segment_text="I probably prefer jazz.")
        self.assertEqual(parsed.candidates[0].schema_name, "likes_music")
        self.assertEqual(
            parsed.candidates[0].epistemic.speaker_commitment,
            SpeakerCommitment.PROBABLE,
        )

    def test_extraction_schema_is_json_serializable(self) -> None:
        json.dumps(extraction_output_schema())


if __name__ == "__main__":
    unittest.main()
