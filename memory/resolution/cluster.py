from __future__ import annotations

import sqlite3
from typing import Any, Mapping, Sequence

from memory.resolution.critics import LinkCriticModel, critique_proposed_alias
from memory.resolution.er_types import ClusterVerdict
from memory.resolution.pairwise import proposal_from_candidate
from memory.resolution.schemas import ProposedExactAlias, ResolutionVerdictRecord


def check_cluster_invariants(
    conn: sqlite3.Connection,
    user_id: int,
    winner_entity_id: str,
    incoming_mention_type: str,
) -> ClusterVerdict:
    winner = conn.execute(
        """
        SELECT entity_id, entity_type, identity_key
        FROM memory_entities
        WHERE user_id = ? AND entity_id = ?
        LIMIT 1
        """,
        (user_id, winner_entity_id),
    ).fetchone()
    if winner is None:
        return ClusterVerdict(
            accepted=False,
            reason="winner_missing",
            decided_by="deterministic",
        )
    if str(winner["entity_type"]) != incoming_mention_type:
        return ClusterVerdict(
            accepted=False,
            reason="cluster_type_mismatch",
            decided_by="deterministic",
        )

    stable_keys = _collect_stable_identity_keys(conn, user_id, winner_entity_id)
    if len(stable_keys) > 1:
        return ClusterVerdict(
            accepted=False,
            reason="multiple_stable_identities",
            decided_by="deterministic",
        )
    return ClusterVerdict(
        accepted=True,
        reason="cluster_invariants_ok",
        decided_by="deterministic",
    )


async def gate_t2_with_critics(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    mention: Mapping[str, Any],
    role: str,
    proposal: ProposedExactAlias,
    incoming_mention_type: str,
    support_model: LinkCriticModel | None,
    adversarial_model: LinkCriticModel | None,
    neighboring_arguments: Sequence[Mapping[str, Any]] | None = None,
    source_authority: str | None = None,
    source_occurred_at: str | None = None,
    cluster_critic_enabled: bool,
) -> tuple[ClusterVerdict, list[ResolutionVerdictRecord]]:
    """Fail-closed T2 gate: invariants plus optional reuse of link critics."""
    invariants = check_cluster_invariants(
        conn,
        user_id,
        proposal.proposed_entity.entity_id,
        incoming_mention_type,
    )
    if not invariants.accepted:
        return invariants, []

    if not cluster_critic_enabled:
        return invariants, []

    if support_model is None:
        return (
            ClusterVerdict(
                accepted=False,
                reason="cluster_critic_unavailable",
                decided_by="critic",
            ),
            [],
        )

    accepted, verdicts, reason = await critique_proposed_alias(
        proposal,
        support_model=support_model,
        adversarial_model=adversarial_model,
        neighboring_arguments=list(neighboring_arguments or ()),
        source_authority=source_authority,
        source_occurred_at=source_occurred_at,
    )
    if not accepted:
        return (
            ClusterVerdict(
                accepted=False,
                reason=f"cluster_{reason}",
                decided_by="critic",
            ),
            verdicts,
        )
    return (
        ClusterVerdict(
            accepted=True,
            reason="cluster_critic_supported",
            decided_by="critic",
        ),
        verdicts,
    )


def build_t2_proposal(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    mention: Mapping[str, Any],
    role: str,
    candidate: Any,
) -> ProposedExactAlias:
    return proposal_from_candidate(
        conn,
        user_id=user_id,
        mention=mention,
        role=role,
        candidate=candidate,
    )


def _collect_stable_identity_keys(
    conn: sqlite3.Connection,
    user_id: int,
    winner_entity_id: str,
) -> set[str]:
    entity_ids = {winner_entity_id, *_merged_losers(conn, user_id, winner_entity_id)}
    stable_keys: set[str] = set()
    if not entity_ids:
        return stable_keys
    placeholders = ",".join("?" for _ in entity_ids)
    rows = conn.execute(
        f"""
        SELECT identity_key
        FROM memory_entities
        WHERE user_id = ? AND entity_id IN ({placeholders})
        """,
        (user_id, *sorted(entity_ids)),
    ).fetchall()
    for row in rows:
        identity_key = str(row["identity_key"])
        if identity_key.startswith("stable:"):
            stable_keys.add(identity_key)
    return stable_keys


def _merged_losers(
    conn: sqlite3.Connection,
    user_id: int,
    winner_entity_id: str,
) -> set[str]:
    try:
        rows = conn.execute(
            """
            SELECT loser_entity_id
            FROM memory_entity_resolution_events
            WHERE user_id = ?
              AND status = 'active'
              AND op = 'merge'
              AND winner_entity_id = ?
            """,
            (user_id, winner_entity_id),
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {str(row["loser_entity_id"]) for row in rows}
