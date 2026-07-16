from __future__ import annotations

import sqlite3
from typing import Any, Mapping, Sequence

from memory.resolution.er_types import EntityCandidate, PairVerdict
from memory.resolution.normalization import display_label, lookup_key
from memory.resolution.schemas import EntityRecord, ProposedExactAlias


def deterministic_gate(mention_type: str, candidate: EntityCandidate) -> str | None:
    """Return reject reason, or None when the candidate may proceed."""
    if mention_type != candidate.entity_type:
        return "cross_type"
    if mention_type == "person" and candidate.tier != "stable_id":
        return "person_non_stable_id"
    return None


def unique_winner(verdicts: Sequence[PairVerdict]) -> PairVerdict | None:
    accepted = [item for item in verdicts if item.accepted]
    if len(accepted) != 1:
        return None
    return accepted[0]


def proposal_from_candidate(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    mention: Mapping[str, Any],
    role: str,
    candidate: EntityCandidate,
) -> ProposedExactAlias:
    mention_id = str(mention["mention_id"])
    mention_type = str(mention.get("mention_type") or "unknown")
    surface = display_label(mention.get("surface_text") or "")
    normalized = lookup_key(surface)
    alias_rows = conn.execute(
        """
        SELECT alias
        FROM memory_entity_aliases
        WHERE entity_id = ? AND user_id = ? AND status = 'active'
        ORDER BY created_at, alias_id
        """,
        (candidate.entity_id, user_id),
    ).fetchall()
    proposed_entity = EntityRecord(
        entity_id=candidate.entity_id,
        entity_type=candidate.entity_type,
        identity_key=candidate.identity_key,
        canonical_label=candidate.canonical_label,
        status=candidate.status,
        decision=f"{candidate.tier}_candidate",
    )
    return ProposedExactAlias(
        mention_id=mention_id,
        mention_type=mention_type,
        surface_text=surface,
        normalized_alias=normalized,
        proposed_entity=proposed_entity,
        active_aliases=tuple(str(item["alias"]) for item in alias_rows),
        role=role,
    )
