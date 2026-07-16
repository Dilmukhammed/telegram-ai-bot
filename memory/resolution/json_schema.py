from __future__ import annotations

from typing import Any


def resolution_link_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "verdict",
            "scope_errors",
            "ambiguities",
            "missing_context",
            "corrected_resolution",
        ],
        "properties": {
            "schema_version": {"type": "string", "enum": ["1"]},
            "verdict": {
                "type": "string",
                "enum": ["supported", "contradicted", "insufficient", "malformed"],
            },
            "scope_errors": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 9,
            },
            "ambiguities": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 8,
            },
            "missing_context": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 8,
            },
            "corrected_resolution": {"type": "null"},
        },
    }
