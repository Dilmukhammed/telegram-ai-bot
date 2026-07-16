from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from memory.attachment.schemas import DOMAIN_PACKS, is_trigger_schema
from memory.attachment.taxonomy import match_taxonomy, normalize_label

_PERSON_TYPES = frozenset({"person"})
_HOLDER_ROLES = frozenset({"subject", "agent", "experiencer", "holder"})
_ATTACH_ROLES = frozenset(
    {"value", "object", "theme", "target", "food", "place", "product", "patient"}
)
_SELF_ENTITY_TYPES = frozenset({"user", "self"})
_LOW_INFO = re.compile(r"^[\W\d_]+$", re.UNICODE)
_SELF_LITERALS = frozenset({"self", "me", "i", "я", "мы"})


@dataclass(frozen=True, slots=True)
class TriggerResult:
    should_run: bool
    attach_domains: tuple[str, ...]
    skip_reason: str | None = None


def infer_domains(
    *,
    schema_name: str,
    entity_type: str | None,
    label: str,
    curated_taxonomy_enabled: bool,
) -> tuple[str, ...]:
    domains: list[str] = []
    schema = (schema_name or "").casefold()
    etype = (entity_type or "").casefold()

    if (
        schema in {"preference", "product", "prefers", "likes_food", "likes_cuisine"}
        or schema.startswith("likes_")
        or schema.startswith("prefer")
        or etype in {"product", "food"}
    ):
        domains.append("food")
    if (
        schema in {"place", "lives_in", "moves_to", "located_in"}
        or schema.startswith("lives_")
        or schema.startswith("moves_")
        or schema.startswith("located_")
        or etype in {"place", "geo"}
    ):
        domains.append("geo")
    if (
        schema in {"organization", "project", "works_at"}
        or schema.startswith("works_")
        or etype in {"organization", "org"}
    ):
        domains.append("org")
    if schema in {"topic", "document_assertion"} or etype in {"topic"}:
        domains.append("topic")
    if match_taxonomy(label, enabled=curated_taxonomy_enabled):
        if "food" not in domains:
            domains.append("food")
    return tuple(dict.fromkeys(domains))


def run_trigger_gate(
    *,
    schema_name: str,
    entity_type: str | None,
    mention_type: str | None,
    label: str,
    belief_status: str | None,
    utility_class: str | None,
    curated_taxonomy_enabled: bool,
    candidate_kind: str | None = None,
) -> TriggerResult:
    if mention_type == "person" or entity_type in _PERSON_TYPES:
        return TriggerResult(False, (), "person_skipped")
    if not is_trigger_schema(schema_name, candidate_kind=candidate_kind):
        return TriggerResult(False, (), f"schema_not_eligible:{schema_name}")
    if belief_status not in {None, "active"}:
        return TriggerResult(False, (), "belief_not_active")
    if utility_class == "provisional":
        return TriggerResult(False, (), "provisional_belief")
    normalized = normalize_label(label)
    if not normalized or _LOW_INFO.match(normalized):
        return TriggerResult(False, (), "low_info_label")
    if normalized in _SELF_LITERALS:
        return TriggerResult(False, (), "self_literal")
    domains = infer_domains(
        schema_name=schema_name,
        entity_type=entity_type,
        label=label,
        curated_taxonomy_enabled=curated_taxonomy_enabled,
    )
    if not domains:
        return TriggerResult(False, (), "no_attach_domain")
    for domain in domains:
        if domain not in DOMAIN_PACKS:
            return TriggerResult(False, (), f"blocked_domain:{domain}")
    return TriggerResult(True, domains)


def subject_from_belief_head(head: Mapping[str, Any]) -> tuple[str | None, str, str | None]:
    """Return (entity_id, label, entity_type) for the attach *object* (not the holder)."""
    import json

    args_raw = head.get("resolved_arguments_json")
    args: list[dict[str, Any]] = []
    if isinstance(args_raw, str):
        try:
            parsed = json.loads(args_raw)
            if isinstance(parsed, list):
                args = [a for a in parsed if isinstance(a, dict)]
        except json.JSONDecodeError:
            args = []
    elif isinstance(args_raw, list):
        args = [a for a in args_raw if isinstance(a, dict)]

    schema_name = str(head.get("schema_name") or head.get("assertion_schema") or "")

    def _from_arg(arg: dict[str, Any]) -> tuple[str | None, str, str | None] | None:
        if arg.get("value_kind") == "entity" and arg.get("entity_id"):
            entity_id = str(arg["entity_id"])
            label = str(arg.get("label") or arg.get("canonical_label") or entity_id)
            entity_type = str(arg.get("entity_type") or schema_name or "concept")
            return entity_id, label, entity_type
        if arg.get("role") in _ATTACH_ROLES and arg.get("literal"):
            return None, str(arg["literal"]), schema_name or None
        return None

    for arg in args:
        role = str(arg.get("role") or "").lower()
        if role in _ATTACH_ROLES:
            picked = _from_arg(arg)
            if picked is not None:
                return picked

    for arg in args:
        role = str(arg.get("role") or "").lower()
        if role in _HOLDER_ROLES:
            continue
        picked = _from_arg(arg)
        if picked is not None:
            return picked

    for arg in args:
        picked = _from_arg(arg)
        if picked is not None:
            return picked

    for arg in args:
        if arg.get("literal"):
            return None, str(arg["literal"]), schema_name or None
    proposition = str(head.get("proposition_key") or "")
    if proposition:
        return None, proposition.split(":", 1)[-1], schema_name or None
    return None, "", schema_name or None


def enrich_subject_from_entities(
    conn: Any,
    *,
    user_id: int,
    entity_id: str | None,
    label: str,
    entity_type: str | None,
) -> tuple[str | None, str, str | None]:
    """Resolve canonical label/type; reject root/self holders."""
    if not entity_id:
        return entity_id, label, entity_type
    row = conn.execute(
        """
        SELECT entity_id, entity_type, identity_key, canonical_label
        FROM memory_entities
        WHERE entity_id = ? AND user_id = ?
        """,
        (entity_id, user_id),
    ).fetchone()
    if row is None:
        return entity_id, label, entity_type
    etype = str(row["entity_type"] or entity_type or "")
    identity = str(row["identity_key"] or "")
    canon = str(row["canonical_label"] or label)
    if etype in _SELF_ENTITY_TYPES or identity == "root_user" or normalize_label(canon) in _SELF_LITERALS:
        return None, "", None
    return str(row["entity_id"]), canon, etype or entity_type
