from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from memory.ids import make_alias_id, make_entity_id, make_mention_link_id
from memory.resolution.normalization import display_label, lookup_key, typed_literal_payload
from memory.resolution.schemas import (
    EXACT_ALIAS_TYPES,
    RESOLVER_VERSION,
    AliasRecord,
    EntityRecord,
    MentionLinkRecord,
    ProposedExactAlias,
    ResolvedArgument,
)


ROOT_ENTITY_TYPE = "user"
ROOT_IDENTITY_KEY = "root_user"
CONCEPT_ENTITY_TYPE = "concept"


def ensure_root_user_entity(
    conn: sqlite3.Connection,
    *,
    user_id: int,
) -> EntityRecord:
    entity_id = make_entity_id(
        user_id=user_id,
        entity_type=ROOT_ENTITY_TYPE,
        identity_key=ROOT_IDENTITY_KEY,
        resolver_version=RESOLVER_VERSION,
    )
    return EntityRecord(
        entity_id=entity_id,
        entity_type=ROOT_ENTITY_TYPE,
        identity_key=ROOT_IDENTITY_KEY,
        canonical_label="self",
        status="active",
        decision="root_user",
    )


def resolve_literal_argument(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    role: str,
    literal: Any,
) -> tuple[ResolvedArgument, EntityRecord | None]:
    if isinstance(literal, str) and lookup_key(literal) == "self":
        entity = ensure_root_user_entity(conn, user_id=user_id)
        return (
            ResolvedArgument(role=role, value_kind="entity", entity_id=entity.entity_id),
            entity,
        )
    payload = typed_literal_payload(literal)
    # A literal denotes the same concept regardless of the argument slot in
    # which it appeared.  Including ``role`` here made e.g. correction.new
    # "Japanese food" and preference.value "Japanese food" two different
    # entities.  Besides duplicating graph nodes, that prevented later
    # negative/correction assertions from targeting the original concept.
    identity_key = lookup_key(
        f"literal|{payload['type']}|{display_label(payload['value'])}"
    )
    entity_id = make_entity_id(
        user_id=user_id,
        entity_type=CONCEPT_ENTITY_TYPE,
        identity_key=identity_key,
        resolver_version=RESOLVER_VERSION,
    )
    entity = EntityRecord(
        entity_id=entity_id,
        entity_type=CONCEPT_ENTITY_TYPE,
        identity_key=identity_key,
        canonical_label=display_label(literal),
        status="active",
        decision="exact_concept",
    )
    return (
        ResolvedArgument(role=role, value_kind="entity", entity_id=entity.entity_id),
        entity,
    )


def _provisional_entity(
    *,
    user_id: int,
    mention_id: str,
    mention_type: str,
    surface: str,
) -> EntityRecord:
    identity_key = f"mention:{mention_id}"
    entity_type = mention_type if mention_type else "unknown"
    entity_id = make_entity_id(
        user_id=user_id,
        entity_type=entity_type,
        identity_key=identity_key,
        resolver_version=RESOLVER_VERSION,
    )
    return EntityRecord(
        entity_id=entity_id,
        entity_type=entity_type,
        identity_key=identity_key,
        canonical_label=surface or mention_id,
        status="provisional",
        decision="provisional_new",
    )


def resolve_mention_argument(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    role: str,
    mention: Mapping[str, Any],
) -> tuple[
    ResolvedArgument,
    EntityRecord,
    AliasRecord | None,
    MentionLinkRecord,
    ProposedExactAlias | None,
]:
    """Resolve a mention. Exact-alias hits return a proposal for critic confirmation."""
    mention_id = str(mention["mention_id"])
    mention_type = str(mention.get("mention_type") or "unknown")
    surface = display_label(mention.get("surface_text") or "")
    normalized = lookup_key(surface)
    proposal: ProposedExactAlias | None = None

    if mention_type in EXACT_ALIAS_TYPES and normalized:
        matches = conn.execute(
            """
            SELECT a.entity_id, e.entity_type, e.identity_key, e.canonical_label, e.status
            FROM memory_entity_aliases a
            JOIN memory_entities e ON e.entity_id = a.entity_id
            WHERE a.user_id = ?
              AND a.normalized_alias = ?
              AND a.status = 'active'
              AND e.status IN ('active', 'provisional')
              AND e.entity_type = ?
            ORDER BY a.created_at, a.alias_id
            """,
            (user_id, normalized, mention_type),
        ).fetchall()
        if len(matches) == 1:
            row = matches[0]
            proposed = EntityRecord(
                entity_id=str(row["entity_id"]),
                entity_type=str(row["entity_type"]),
                identity_key=str(row["identity_key"]),
                canonical_label=str(row["canonical_label"]),
                status=str(row["status"]),
                decision="exact_alias_candidate",
            )
            alias_rows = conn.execute(
                """
                SELECT alias FROM memory_entity_aliases
                WHERE entity_id = ? AND user_id = ? AND status = 'active'
                ORDER BY created_at, alias_id
                """,
                (proposed.entity_id, user_id),
            ).fetchall()
            proposal = ProposedExactAlias(
                mention_id=mention_id,
                mention_type=mention_type,
                surface_text=surface,
                normalized_alias=normalized,
                proposed_entity=proposed,
                active_aliases=tuple(str(item["alias"]) for item in alias_rows),
                role=role,
            )
            # Placeholder provisional until critics accept; pipeline may replace.
            entity = _provisional_entity(
                user_id=user_id,
                mention_id=mention_id,
                mention_type=mention_type,
                surface=surface,
            )
        else:
            entity = _provisional_entity(
                user_id=user_id,
                mention_id=mention_id,
                mention_type=mention_type,
                surface=surface,
            )
    else:
        entity = _provisional_entity(
            user_id=user_id,
            mention_id=mention_id,
            mention_type=mention_type,
            surface=surface,
        )

    alias: AliasRecord | None = None
    if mention_type in EXACT_ALIAS_TYPES and normalized:
        alias = AliasRecord(
            alias_id=make_alias_id(
                user_id=user_id,
                entity_id=entity.entity_id,
                normalized_alias=normalized,
                source_mention_id=mention_id,
            ),
            entity_id=entity.entity_id,
            source_mention_id=mention_id,
            alias=surface,
            normalized_alias=normalized,
        )

    link = MentionLinkRecord(
        link_id=make_mention_link_id(
            mention_id=mention_id,
            entity_id=entity.entity_id,
            resolver_version=RESOLVER_VERSION,
        ),
        mention_id=mention_id,
        entity_id=entity.entity_id,
        decision=entity.decision,
        resolution_components={
            "mention_type": mention_type,
            "normalized_alias": normalized,
            "decision": entity.decision,
            "proposed_entity_id": (
                proposal.proposed_entity.entity_id if proposal is not None else None
            ),
        },
    )
    return (
        ResolvedArgument(role=role, value_kind="entity", entity_id=entity.entity_id),
        entity,
        alias,
        link,
        proposal,
    )


def accept_proposed_alias(
    *,
    user_id: int,
    role: str,
    mention: Mapping[str, Any],
    proposal: ProposedExactAlias,
) -> tuple[ResolvedArgument, EntityRecord, AliasRecord, MentionLinkRecord]:
    """Build final records after critics accepted the proposed reuse."""
    mention_id = str(mention["mention_id"])
    surface = display_label(mention.get("surface_text") or "")
    normalized = lookup_key(surface)
    entity = EntityRecord(
        entity_id=proposal.proposed_entity.entity_id,
        entity_type=proposal.proposed_entity.entity_type,
        identity_key=proposal.proposed_entity.identity_key,
        canonical_label=proposal.proposed_entity.canonical_label,
        status=proposal.proposed_entity.status,
        decision="exact_alias_verified",
    )
    alias = AliasRecord(
        alias_id=make_alias_id(
            user_id=user_id,
            entity_id=entity.entity_id,
            normalized_alias=normalized,
            source_mention_id=mention_id,
        ),
        entity_id=entity.entity_id,
        source_mention_id=mention_id,
        alias=surface,
        normalized_alias=normalized,
    )
    link = MentionLinkRecord(
        link_id=make_mention_link_id(
            mention_id=mention_id,
            entity_id=entity.entity_id,
            resolver_version=RESOLVER_VERSION,
        ),
        mention_id=mention_id,
        entity_id=entity.entity_id,
        decision="exact_alias_verified",
        resolution_components={
            "mention_type": proposal.mention_type,
            "normalized_alias": normalized,
            "decision": "exact_alias_verified",
            "proposed_entity_id": entity.entity_id,
            "critic_risk": "support_and_adversarial",
        },
    )
    return (
        ResolvedArgument(role=role, value_kind="entity", entity_id=entity.entity_id),
        entity,
        alias,
        link,
    )
