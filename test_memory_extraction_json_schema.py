from __future__ import annotations

import json
import unittest

from memory.extraction.json_schemas import (
    extraction_output_schema,
    structured_response_format,
)
from memory.extraction.parser import parse_extraction_output
from memory.extraction.schemas import SpeakerCommitment


class ExtractionJsonSchemaTests(unittest.TestCase):
    def test_free_labels_accepted_in_schema(self) -> None:
        schema = extraction_output_schema()
        mention_type = schema["properties"]["mentions"]["items"]["properties"]["mention_type"]
        kind = schema["properties"]["candidates"]["items"]["properties"]["kind"]
        schema_name = schema["properties"]["candidates"]["items"]["properties"]["schema_name"]
        role = schema["properties"]["candidates"]["items"]["properties"]["arguments"]["items"]["oneOf"][0][
            "properties"
        ]["role"]
        for field in (mention_type, kind, schema_name, role):
            self.assertEqual(field["type"], "string")
            self.assertEqual(field["minLength"], 1)
            self.assertNotIn("enum", field)

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

    def test_free_invented_labels_parse(self) -> None:
        raw = {
            "abstain": False,
            "mentions": [
                {
                    "mention_type": "game_character",
                    "surface_text": "Lara",
                }
            ],
            "candidates": [
                {
                    "kind": "game_progress",
                    "schema_name": "quest_completed",
                    "arguments": [
                        {"role": "player", "literal": "self"},
                        {"role": "quest", "mention_surface": "Lara"},
                    ],
                    "polarity": "positive",
                    "epistemic": {
                        "mode": "asserted",
                        "speaker_commitment": "certain",
                    },
                    "evidence": [
                        {"relation": "supports", "quote": "I finished Lara's quest."}
                    ],
                }
            ],
        }
        parsed = parse_extraction_output(raw, segment_text="I finished Lara's quest.")
        self.assertEqual(parsed.mentions[0].mention_type, "game_character")
        self.assertEqual(parsed.candidates[0].kind, "game_progress")
        self.assertEqual(parsed.candidates[0].schema_name, "quest_completed")
        self.assertEqual(parsed.candidates[0].arguments[0].role, "player")

    def test_extraction_schema_is_json_serializable(self) -> None:
        json.dumps(extraction_output_schema())


if __name__ == "__main__":
    unittest.main()
