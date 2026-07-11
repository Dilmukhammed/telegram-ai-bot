from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Mapping

from memory.extraction.schemas import CandidateArgument, CandidateDraft, CandidateKind, ExtractionResult


@dataclass(frozen=True)
class SchemaContract:
    kind: CandidateKind
    required_roles: tuple[str, ...]
    optional_roles: tuple[str, ...] = ()
    role_aliases: Mapping[str, str] | None = None


def _contract(
    kind: CandidateKind,
    *required_roles: str,
    optional_roles: tuple[str, ...] = (),
    role_aliases: Mapping[str, str] | None = None,
) -> SchemaContract:
    return SchemaContract(kind, required_roles, optional_roles, role_aliases)


SCHEMA_CONTRACTS: dict[str, SchemaContract] = {
    "name": _contract(CandidateKind.ENTITY_ATTRIBUTE, "subject", "value"),
    "occupation": _contract(CandidateKind.ENTITY_ATTRIBUTE, "subject", "value"),
    "date_of_birth": _contract(CandidateKind.ENTITY_ATTRIBUTE, "person", "value"),
    "allergic_to": _contract(CandidateKind.ENTITY_ATTRIBUTE, "subject", "allergen"),
    "diet_identity": _contract(CandidateKind.ENTITY_ATTRIBUTE, "subject", "value"),
    "has_children": _contract(CandidateKind.ENTITY_ATTRIBUTE, "subject"),
    "owns_car": _contract(CandidateKind.ENTITY_ATTRIBUTE, "subject"),
    "prefers": _contract(CandidateKind.PREFERENCE, "subject", "value"),
    "likes": _contract(CandidateKind.PREFERENCE, "subject", "value"),
    "dietary_constraint": _contract(CandidateKind.PREFERENCE, "subject", "excluded"),
    "budget_limit": _contract(
        CandidateKind.PREFERENCE,
        "subject",
        "amount",
        role_aliases={"value": "amount"},
    ),
    "hotel_constraint": _contract(CandidateKind.PREFERENCE, "subject", "value"),
    "seat_constraint": _contract(CandidateKind.PREFERENCE, "subject", "value"),
    "favorite_book": _contract(
        CandidateKind.PREFERENCE,
        "subject",
        "book",
        role_aliases={"value": "book", "title": "book"},
    ),
    "likes_music": _contract(CandidateKind.PREFERENCE, "subject", "value"),
    "likes_activity": _contract(
        CandidateKind.PREFERENCE,
        "subject",
        "activity",
        role_aliases={"value": "activity"},
    ),
    "likes_contact_mode": _contract(
        CandidateKind.PREFERENCE,
        "subject",
        "mode",
        role_aliases={"value": "mode"},
    ),
    "likes_flying": _contract(CandidateKind.PREFERENCE, "subject"),
    "destination_choice": _contract(CandidateKind.PREFERENCE, "subject"),
    "works_at": _contract(CandidateKind.RELATION, "person", "organization"),
    "lives_in": _contract(CandidateKind.RELATION, "person", "place"),
    "manager_of": _contract(CandidateKind.RELATION, "manager", "report"),
    "sibling_of": _contract(
        CandidateKind.RELATION,
        "person",
        "related_to",
        role_aliases={"subject": "person"},
    ),
    "learn_skill": _contract(CandidateKind.GOAL, "subject", "skill"),
    "run_marathon": _contract(CandidateKind.GOAL, "subject"),
    "call_person": _contract(CandidateKind.TASK, "subject", "target"),
    "created_task": _contract(CandidateKind.TASK, "subject", "title"),
    "open_task": _contract(CandidateKind.TASK, "subject", "title"),
    "prepare_demo": _contract(CandidateKind.TASK, "subject"),
    "renew_passport": _contract(CandidateKind.TASK, "subject"),
    "submit_report": _contract(
        CandidateKind.TASK,
        "subject",
        "object",
        role_aliases={"value": "object"},
    ),
    "health_state": _contract(CandidateKind.STATE, "subject", "value"),
    "located_at": _contract(CandidateKind.STATE, "person", "place"),
    "calendar_event": _contract(
        CandidateKind.EVENT,
        "subject",
        "title",
        optional_roles=("attendee",),
    ),
    "left_job": _contract(
        CandidateKind.EVENT,
        "person",
        optional_roles=("organization",),
    ),
    "moves_to": _contract(CandidateKind.EVENT, "subject", "place"),
    "attends": _contract(CandidateKind.EVENT, "subject", "event"),
    "corrects_diet": _contract(CandidateKind.CORRECTION, "subject", "old", "new"),
    "corrects_occupation": _contract(CandidateKind.CORRECTION, "subject", "old", "new"),
    "corrects_residence": _contract(CandidateKind.CORRECTION, "subject", "old", "new"),
    "corrects_selection": _contract(CandidateKind.CORRECTION, "subject", "old", "new"),
}


_LITERAL_CANONICALIZATION: dict[str, dict[str, object]] = {
    "diet_identity": {
        "вегетарианец": "vegetarian",
        "вегетарианка": "vegetarian",
    },
    "attends": {
        "встреча": "meeting",
        "встречу": "meeting",
    },
    "call_person": {
        "врач": "doctor",
        "врачу": "doctor",
        "доктор": "doctor",
        "доктору": "doctor",
    },
    "submit_report": {
        "отчёт": "report",
        "отчет": "report",
    },
    "dietary_constraint": {
        "лактоза": "lactose",
        "лактозы": "lactose",
    },
    "likes_music": {"джаз": "jazz"},
}


def normalize_candidate_contracts(result: ExtractionResult) -> ExtractionResult:
    candidates = tuple(_normalize_candidate(candidate) for candidate in result.candidates)
    return result if candidates == result.candidates else replace(result, candidates=candidates)


def candidate_contract_violations(result: ExtractionResult) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    for index, candidate in enumerate(result.candidates):
        contract = SCHEMA_CONTRACTS.get(candidate.schema_name)
        if contract is None:
            violations.append(
                {"candidate_index": index, "schema_name": candidate.schema_name, "error": "unknown_schema"}
            )
            continue
        roles = tuple(argument.role for argument in candidate.arguments)
        allowed = set(contract.required_roles + contract.optional_roles)
        missing = [role for role in contract.required_roles if role not in roles]
        unexpected = [role for role in roles if role not in allowed]
        duplicates = sorted({role for role in roles if roles.count(role) > 1})
        if candidate.kind is not contract.kind or missing or unexpected or duplicates:
            violations.append(
                {
                    "candidate_index": index,
                    "schema_name": candidate.schema_name,
                    "actual_kind": candidate.kind.value,
                    "expected_kind": contract.kind.value,
                    "missing_roles": missing,
                    "unexpected_roles": unexpected,
                    "duplicate_roles": duplicates,
                }
            )
    return violations


def _normalize_candidate(candidate: CandidateDraft) -> CandidateDraft:
    contract = SCHEMA_CONTRACTS.get(candidate.schema_name)
    if contract is None:
        return candidate
    aliases = dict(contract.role_aliases or {})
    arguments = tuple(
        _normalize_argument(candidate.schema_name, argument, aliases)
        for argument in candidate.arguments
    )
    order = {
        role: index
        for index, role in enumerate(contract.required_roles + contract.optional_roles)
    }
    arguments = tuple(sorted(arguments, key=lambda item: order.get(item.role, len(order))))
    alternative_map = {
        "лондон": "London",
        "париж": "Paris",
    }
    alternatives = tuple(
        alternative_map.get(str(item).casefold(), item)
        for item in candidate.epistemic.alternatives
    )
    epistemic = replace(candidate.epistemic, alternatives=alternatives)
    return replace(
        candidate,
        kind=contract.kind,
        arguments=arguments,
        epistemic=epistemic,
    )


def _normalize_argument(
    schema_name: str,
    argument: CandidateArgument,
    aliases: Mapping[str, str],
) -> CandidateArgument:
    role = aliases.get(argument.role, argument.role)
    literal = argument.literal
    if argument.has_literal and isinstance(literal, str):
        if schema_name in {"created_task", "open_task"} and role == "title":
            literal = re.sub(r"^(\w+\s+)my\s+", r"\1", literal, flags=re.IGNORECASE)
        canonical = _LITERAL_CANONICALIZATION.get(schema_name, {}).get(literal.casefold())
        if canonical is not None:
            literal = canonical
        elif schema_name == "budget_limit" and role == "amount":
            match = re.search(r"\d+(?:[.,]\d+)?", literal)
            if match is not None:
                number = match.group(0).replace(",", ".")
                literal = float(number) if "." in number else int(number)
    return replace(argument, role=role, literal=literal)
