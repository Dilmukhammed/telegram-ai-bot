from __future__ import annotations

SUMMARY_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sentences"],
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "belief_ids"],
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "belief_ids": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                    },
                },
            },
            "minItems": 1,
        }
    },
}


def summary_output_schema() -> dict:
    return SUMMARY_OUTPUT_SCHEMA
