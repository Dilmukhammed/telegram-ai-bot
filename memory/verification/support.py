from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from memory.extraction.contracts import SCHEMA_CONTRACTS


ALLOWED_VERIFICATION_AUTHORITIES = frozenset(
    {"user_direct_statement", "tool_api_result", "authoritative_api_result"}
)
CONTEXT_ONLY_AUTHORITIES = frozenset({"assistant_generated"})
CONTEXT_ONLY_RELATIONS = frozenset(
    {"introduces_alternatives", "introduces_entity", "supports_coreference"}
)


def deterministic_exact_tool_support(candidate: Mapping[str, Any]) -> bool:
    """Recognize exact task/event facts copied from authoritative JSON payloads."""
    if candidate.get("polarity") != "positive" or candidate.get("attributes"):
        return False
    kind = candidate.get("candidate_kind")
    schema_name = candidate.get("schema_name")
    temporal = candidate.get("temporal")
    exact_task = kind == "task" and temporal is None
    exact_event = (
        kind == "event"
        and schema_name == "calendar_event"
        and isinstance(temporal, Mapping)
    )
    if not exact_task and not exact_event:
        return False
    epistemic = candidate.get("epistemic")
    if not isinstance(epistemic, Mapping) or (
        epistemic.get("mode") != "retrieved"
        or epistemic.get("speaker_commitment") != "certain"
    ):
        return False
    arguments = candidate.get("arguments")
    evidence = candidate.get("evidence")
    if not isinstance(arguments, list) or not isinstance(evidence, list) or not evidence:
        return False
    payload_values: set[str] = set()
    for item in evidence:
        if not isinstance(item, Mapping) or (
            item.get("authority_class")
            not in {"tool_api_result", "authoritative_api_result"}
            or item.get("relation") != "supports"
        ):
            return False
        try:
            payload = json.loads(str(item.get("exact_quote", "")))
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        payload_values.update(_json_scalar_values(payload))
    if exact_event:
        assert isinstance(temporal, Mapping)
        original_text = temporal.get("original_text")
        event_time = temporal.get("event_time")
        if (
            not isinstance(original_text, str)
            or original_text not in payload_values
            or not isinstance(event_time, str)
            or event_time not in payload_values
        ):
            return False
    saw_self = False
    saw_tool_value = False
    for argument in arguments:
        if not isinstance(argument, Mapping) or "literal" not in argument:
            return False
        literal = argument.get("literal")
        if argument.get("role") == "subject" and literal == "self":
            saw_self = True
        elif str(literal) in payload_values:
            saw_tool_value = True
        else:
            return False
    return saw_self and saw_tool_value


def _json_scalar_values(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        result: set[str] = set()
        for item in value.values():
            result.update(_json_scalar_values(item))
        return result
    if isinstance(value, list):
        result = set()
        for item in value:
            result.update(_json_scalar_values(item))
        return result
    if value is None or isinstance(value, (dict, list)):
        return set()
    return {str(value)}


def deterministic_preflight(candidate: Mapping[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    contract = SCHEMA_CONTRACTS.get(str(candidate.get("schema_name", "")))
    arguments = candidate.get("arguments")
    if not isinstance(arguments, list):
        arguments = []
        errors.append("malformed_candidate")
    if contract is None:
        errors.append("malformed_candidate")
    else:
        if str(candidate.get("candidate_kind")) != contract.kind.value:
            errors.append("malformed_candidate")
        roles = [
            str(item.get("role"))
            for item in arguments
            if isinstance(item, Mapping)
        ]
        allowed = set(contract.required_roles + contract.optional_roles)
        if (
            any(role not in roles for role in contract.required_roles)
            or any(role not in allowed for role in roles)
            or len(roles) != len(set(roles))
        ):
            errors.append("argument_unsupported")

    mentions = candidate.get("mentions")
    if not isinstance(mentions, Mapping):
        mentions = {}
        errors.append("malformed_candidate")
    for argument in arguments:
        if not isinstance(argument, Mapping):
            errors.append("malformed_candidate")
            continue
        mention_id = argument.get("mention_id")
        has_literal = "literal" in argument
        if bool(mention_id) == has_literal:
            errors.append("argument_unsupported")
        if mention_id:
            mention = mentions.get(str(mention_id))
            if not isinstance(mention, Mapping) or mention.get("status") != "active":
                errors.append("argument_unsupported")

    epistemic = candidate.get("epistemic")
    if not isinstance(epistemic, Mapping):
        errors.append("malformed_candidate")
        epistemic = {}
    mode = str(epistemic.get("mode", ""))
    commitment = str(epistemic.get("speaker_commitment", ""))
    polarity = str(candidate.get("polarity", ""))
    speaker = epistemic.get("speaker_ref")
    if mode in {"reported", "quoted"}:
        if not isinstance(speaker, str) or speaker == "self":
            errors.append("wrong_speaker")
        elif speaker not in mentions:
            errors.append("wrong_speaker")
    if (
        commitment in {"probable", "possible", "uncertain", "unknown"}
        and polarity != "unknown"
    ):
        errors.append("uncertainty_scope")

    evidence = candidate.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("evidence_not_entailed")
        evidence = []
    has_primary_evidence = False
    for item in evidence:
        if not isinstance(item, Mapping):
            errors.append("malformed_candidate")
            continue
        if (
            item.get("source_status") != "active"
            or item.get("source_version_status") != "active"
            or item.get("segment_status") != "active"
        ):
            errors.append("authority_mismatch")
        authority = item.get("authority_class")
        relation = item.get("relation")
        contextual = (
            authority in CONTEXT_ONLY_AUTHORITIES
            and relation in CONTEXT_ONLY_RELATIONS
        )
        if authority in ALLOWED_VERIFICATION_AUTHORITIES:
            has_primary_evidence = True
        elif not contextual:
            errors.append("authority_mismatch")
        pointer = item.get("pointer")
        text = str(item.get("segment_text", ""))
        quote = str(item.get("exact_quote", ""))
        if not quote or not isinstance(pointer, Mapping):
            errors.append("evidence_not_entailed")
            continue
        location = pointer.get("location")
        if isinstance(location, Mapping) and {
            "char_start",
            "char_end",
        } <= set(location):
            start = location["char_start"]
            end = location["char_end"]
            context_pointer = item.get("context_pointer")
            context_location = (
                context_pointer.get("location")
                if isinstance(context_pointer, Mapping)
                else None
            )
            base = (
                context_location.get("char_start", 0)
                if isinstance(context_location, Mapping)
                else 0
            )
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or not isinstance(base, int)
                or start < 0
                or end < start
                or start - base < 0
                or end - base > len(text)
                or text[start - base : end - base] != quote
            ):
                errors.append("evidence_not_entailed")
        elif quote != text and quote not in text:
            errors.append("evidence_not_entailed")

    if evidence and not has_primary_evidence:
        errors.append("authority_mismatch")
    return tuple(dict.fromkeys(errors))


def candidate_view(candidate: Mapping[str, Any], *, context_chars: int) -> dict[str, Any]:
    if context_chars < 0:
        raise ValueError("context_chars must be >= 0")
    mentions = candidate.get("mentions") or {}
    arguments: list[dict[str, Any]] = []
    for argument in candidate.get("arguments") or ():
        item = dict(argument)
        mention_id = item.get("mention_id")
        if mention_id in mentions:
            mention = mentions[mention_id]
            item["mention"] = {
                "surface_text": mention.get("surface_text"),
                "mention_type": mention.get("mention_type"),
            }
        arguments.append(item)
    epistemic = dict(candidate.get("epistemic") or {})
    speaker_ref = epistemic.get("speaker_ref")
    if speaker_ref in mentions:
        epistemic["speaker"] = {
            "surface_text": mentions[speaker_ref].get("surface_text"),
            "mention_type": mentions[speaker_ref].get("mention_type"),
        }
    evidence = [
        _bounded_evidence(dict(item), context_chars=context_chars)
        for item in candidate.get("evidence") or ()
    ]
    temporal = candidate.get("temporal")
    temporal_provenance = None
    if isinstance(temporal, Mapping):
        temporal_provenance = {
            "source_occurred_at": [
                item.get("source_occurred_at")
                for item in candidate.get("evidence") or ()
                if isinstance(item, Mapping) and item.get("source_occurred_at")
            ],
            "timezone": temporal.get("timezone"),
            "original_text": temporal.get("original_text"),
            "derivation": "normalized_from_explicit_cue_and_source_time",
        }
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_kind": candidate["candidate_kind"],
        "schema_name": candidate["schema_name"],
        "arguments": arguments,
        "attributes": candidate.get("attributes") or {},
        "polarity": candidate["polarity"],
        "epistemic": epistemic,
        "temporal": temporal,
        "temporal_provenance": temporal_provenance,
        "evidence": evidence,
    }


def _bounded_evidence(item: dict[str, Any], *, context_chars: int) -> dict[str, Any]:
    text = str(item.pop("segment_text", ""))
    quote = str(item.get("exact_quote", ""))
    start = text.find(quote) if quote else -1
    if start < 0:
        context = text[: context_chars * 2]
    else:
        context = text[max(0, start - context_chars) : start + len(quote) + context_chars]
    return {
        "relation": item.get("relation"),
        "exact_quote": quote,
        "bounded_context": context,
        "source_type": item.get("source_type"),
        "authority_class": item.get("authority_class"),
        "source_occurred_at": item.get("source_occurred_at"),
        "pointer": item.get("pointer"),
    }
