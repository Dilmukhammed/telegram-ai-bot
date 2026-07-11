from __future__ import annotations

from typing import Any

from memory.verification.schemas import EvidenceDirectness, VerificationVerdict


SCOPE_ERROR_CODES = (
    "evidence_not_entailed",
    "argument_unsupported",
    "wrong_speaker",
    "quoted_as_asserted",
    "negation_scope",
    "uncertainty_scope",
    "temporal_scope",
    "authority_mismatch",
    "malformed_candidate",
)


def verification_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string", "enum": ["1"]},
            "verdict": {
                "type": "string",
                "enum": [item.value for item in VerificationVerdict],
            },
            "evidence_directness": {
                "type": ["string", "null"],
                "enum": [item.value for item in EvidenceDirectness] + [None],
            },
            "scope_errors": {
                "type": "array",
                "items": {"type": "string", "enum": list(SCOPE_ERROR_CODES)},
                "maxItems": 9,
            },
            "ambiguities": {
                "type": "array",
                "items": {"type": "string", "maxLength": 500},
                "maxItems": 8,
            },
            "missing_context": {
                "type": "array",
                "items": {"type": "string", "maxLength": 500},
                "maxItems": 8,
            },
            "corrected_candidate": {"type": "null"},
        },
        "required": [
            "schema_version",
            "verdict",
            "evidence_directness",
            "scope_errors",
            "ambiguities",
            "missing_context",
            "corrected_candidate",
        ],
        "additionalProperties": False,
    }
