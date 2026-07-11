from __future__ import annotations

from typing import Any, Literal

from memory.extraction.schemas import (
    CandidateKind,
    EpistemicMode,
    MentionType,
    Polarity,
    SpeakerCommitment,
)


StructuredSchemaName = Literal["extraction"]

SCHEMA_NAMES: tuple[str, ...] = (
    "name",
    "occupation",
    "date_of_birth",
    "allergic_to",
    "diet_identity",
    "has_children",
    "owns_car",
    "prefers",
    "likes",
    "dietary_constraint",
    "budget_limit",
    "hotel_constraint",
    "seat_constraint",
    "favorite_book",
    "likes_music",
    "likes_activity",
    "likes_contact_mode",
    "likes_flying",
    "destination_choice",
    "works_at",
    "lives_in",
    "manager_of",
    "sibling_of",
    "learn_skill",
    "run_marathon",
    "call_person",
    "created_task",
    "open_task",
    "prepare_demo",
    "renew_passport",
    "submit_report",
    "health_state",
    "located_at",
    "calendar_event",
    "left_job",
    "moves_to",
    "attends",
    "corrects_diet",
    "corrects_occupation",
    "corrects_residence",
    "corrects_selection",
)

ARGUMENT_ROLES: tuple[str, ...] = (
    "subject",
    "value",
    "person",
    "organization",
    "place",
    "allergen",
    "skill",
    "title",
    "target",
    "object",
    "old",
    "new",
    "manager",
    "report",
    "related_to",
    "book",
    "activity",
    "mode",
    "amount",
    "excluded",
    "attendee",
    "event",
)

EVIDENCE_RELATIONS: tuple[str, ...] = (
    "supports",
    "introduces_alternatives",
    "corrects",
)


def _enum(values: tuple[str, ...] | list[str]) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


def _nullable_string() -> dict[str, Any]:
    return {"type": ["string", "null"]}


def _json_literal() -> dict[str, Any]:
    return {
        "anyOf": [
            {"type": "string"},
            {"type": "number"},
            {"type": "integer"},
            {"type": "boolean"},
            {"type": "null"},
        ]
    }


def _strict_object(
    *,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    keys = required if required is not None else list(properties)
    return {
        "type": "object",
        "properties": properties,
        "required": keys,
        "additionalProperties": False,
    }


def _slim_mention_schema() -> dict[str, Any]:
    return _strict_object(
        properties={
            "mention_type": _enum(tuple(item.value for item in MentionType)),
            "surface_text": {"type": "string"},
            "normalized_hint": _nullable_string(),
            "mention_ref": {"type": "string"},
        },
        required=["mention_type", "surface_text"],
    )


def _slim_argument_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            _strict_object(
                properties={
                    "role": _enum(ARGUMENT_ROLES),
                    "mention_surface": {"type": "string"},
                }
            ),
            _strict_object(
                properties={
                    "role": _enum(ARGUMENT_ROLES),
                    "mention_ref": {"type": "string"},
                }
            ),
            _strict_object(
                properties={
                    "role": _enum(ARGUMENT_ROLES),
                    "literal": _json_literal(),
                }
            ),
        ]
    }


def _slim_epistemic_schema() -> dict[str, Any]:
    return _strict_object(
        properties={
            "mode": _enum(tuple(item.value for item in EpistemicMode)),
            "speaker_commitment": _enum(tuple(item.value for item in SpeakerCommitment)),
            "alternatives": {
                "type": "array",
                "items": _json_literal(),
            },
            "speaker_ref": _nullable_string(),
        },
        required=["mode", "speaker_commitment"],
    )


def _slim_evidence_schema() -> dict[str, Any]:
    return _strict_object(
        properties={
            "relation": _enum(EVIDENCE_RELATIONS),
            "quote": {"type": "string"},
        }
    )


def _slim_candidate_schema() -> dict[str, Any]:
    return _strict_object(
        properties={
            "kind": _enum(tuple(item.value for item in CandidateKind)),
            "schema_name": _enum(SCHEMA_NAMES),
            "arguments": {
                "type": "array",
                "items": _slim_argument_schema(),
                "minItems": 1,
            },
            "polarity": _enum(tuple(item.value for item in Polarity)),
            "epistemic": _slim_epistemic_schema(),
            "temporal_cue": _nullable_string(),
            "evidence": {
                "type": "array",
                "items": _slim_evidence_schema(),
                "minItems": 1,
            },
            "candidate_ref": {"type": "string"},
        },
        required=[
            "kind",
            "schema_name",
            "arguments",
            "polarity",
            "epistemic",
            "evidence",
        ],
    )


def extraction_output_schema() -> dict[str, Any]:
    return _strict_object(
        properties={
            "abstain": {"type": "boolean"},
            "mentions": {
                "type": "array",
                "items": _slim_mention_schema(),
            },
            "candidates": {
                "type": "array",
                "items": _slim_candidate_schema(),
            },
        }
    )


def schema_for_name(name: StructuredSchemaName) -> dict[str, Any]:
    if name == "extraction":
        return extraction_output_schema()
    raise ValueError(f"unsupported structured schema name: {name!r}")


def structured_response_format(
    *,
    name: StructuredSchemaName,
    strict: bool = True,
) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": strict,
            "schema": schema_for_name(name),
        },
    }


def fallback_json_object_format() -> dict[str, Any]:
    return {"type": "json_object"}
