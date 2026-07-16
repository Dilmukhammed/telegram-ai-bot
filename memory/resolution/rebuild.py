from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from memory.db import utc_now_iso
from memory.ids import make_belief_id
from memory.models import LineageInput
from memory.resolution.beliefs import reconcile_belief
from memory.resolution.events_store import (
    build_split_event,
    find_merges_touching_evidence,
    insert_events_in_txn,
)
from memory.resolution.jobs import resolution_job_request
from memory.resolution.schemas import EntityRecord
from memory.resolution.store import _row_to_assertion

if TYPE_CHECKING:
    from memory.service import MemoryService


ROOT_ENTITY_TYPE = "user"
ROOT_IDENTITY = "root_user"


@dataclass(frozen=True, slots=True)
class ResolutionInvalidationResult:
    assertion_count: int
    link_count: int
    verdict_count: int
    alias_count: int
    entity_count: int
    belief_recompute_count: int


@dataclass(frozen=True, slots=True)
class ResolutionRebuildResult:
    candidates_seen: int
    jobs_created: int


def invalidate_resolution_artifacts_in_txn(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    candidate_ids: Sequence[str] | None = None,
    mention_ids: Sequence[str] | None = None,
) -> ResolutionInvalidationResult:
    """Invalidate PR5 artifacts derived from candidates/mentions; recompute beliefs."""
    now = utc_now_iso()
    cand_ids = sorted({str(item) for item in (candidate_ids or ()) if item})
    men_ids = list({str(item) for item in (mention_ids or ()) if item})
    if not cand_ids and not men_ids:
        return ResolutionInvalidationResult(0, 0, 0, 0, 0, 0)

    if cand_ids:
        placeholders = ",".join("?" for _ in cand_ids)
        for row in conn.execute(
            f"""
            SELECT arguments_json FROM memory_claim_candidates
            WHERE user_id = ? AND candidate_id IN ({placeholders})
            """,
            (user_id, *cand_ids),
        ).fetchall():
            args = json.loads(str(row["arguments_json"]))
            if isinstance(args, list):
                for item in args:
                    if isinstance(item, dict) and item.get("mention_id"):
                        men_ids.append(str(item["mention_id"]))
        men_ids = sorted(set(men_ids))

    assertion_count = 0
    proposition_keys: set[str] = set()
    if cand_ids:
        placeholders = ",".join("?" for _ in cand_ids)
        props = conn.execute(
            f"""
            SELECT assertion_id, proposition_key FROM memory_assertions
            WHERE user_id = ? AND candidate_id IN ({placeholders})
              AND status != 'invalidated'
            """,
            (user_id, *cand_ids),
        ).fetchall()
        for row in props:
            proposition_keys.add(str(row["proposition_key"]))
        updated = conn.execute(
            f"""
            UPDATE memory_assertions
            SET status = 'invalidated'
            WHERE user_id = ? AND candidate_id IN ({placeholders})
              AND status != 'invalidated'
            """,
            (user_id, *cand_ids),
        )
        assertion_count = int(updated.rowcount)

    link_count = 0
    verdict_count = 0
    alias_count = 0
    entity_count = 0
    invalidated_alias_ids: list[str] = []
    invalidated_verdict_ids: list[str] = []
    if men_ids:
        placeholders = ",".join("?" for _ in men_ids)
        verdict_rows = conn.execute(
            f"""
            SELECT resolution_verdict_id
            FROM memory_resolution_verdicts
            WHERE user_id = ? AND mention_id IN ({placeholders})
              AND status != 'invalidated'
            """,
            (user_id, *men_ids),
        ).fetchall()
        invalidated_verdict_ids = [str(row["resolution_verdict_id"]) for row in verdict_rows]
        updated = conn.execute(
            f"""
            UPDATE memory_mention_links
            SET status = 'invalidated'
            WHERE user_id = ? AND mention_id IN ({placeholders})
              AND status != 'invalidated'
            """,
            (user_id, *men_ids),
        )
        link_count = int(updated.rowcount)
        updated = conn.execute(
            f"""
            UPDATE memory_resolution_verdicts
            SET status = 'invalidated'
            WHERE user_id = ? AND mention_id IN ({placeholders})
              AND status != 'invalidated'
            """,
            (user_id, *men_ids),
        )
        verdict_count = int(updated.rowcount)
        alias_rows = conn.execute(
            f"""
            SELECT alias_id, entity_id FROM memory_entity_aliases
            WHERE user_id = ? AND source_mention_id IN ({placeholders})
              AND status = 'active'
            """,
            (user_id, *men_ids),
        ).fetchall()
        for row in alias_rows:
            invalidated_alias_ids.append(str(row["alias_id"]))
            conn.execute(
                """
                UPDATE memory_entity_aliases
                SET status = 'invalidated'
                WHERE alias_id = ? AND user_id = ?
                """,
                (row["alias_id"], user_id),
            )
            alias_count += 1
            entity_id = str(row["entity_id"])
            remaining = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM memory_entity_aliases
                    WHERE entity_id = ? AND user_id = ? AND status = 'active'
                    """,
                    (entity_id, user_id),
                ).fetchone()["c"]
            )
            entity = conn.execute(
                """
                SELECT entity_type, identity_key FROM memory_entities
                WHERE entity_id = ? AND user_id = ?
                """,
                (entity_id, user_id),
            ).fetchone()
            if entity is None:
                continue
            if (
                str(entity["entity_type"]) == ROOT_ENTITY_TYPE
                and str(entity["identity_key"]) == ROOT_IDENTITY
            ):
                continue
            if remaining == 0:
                used = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS c FROM memory_assertions
                        WHERE user_id = ? AND status = 'active'
                          AND resolved_arguments_json LIKE ?
                        """,
                        (user_id, f"%{entity_id}%"),
                    ).fetchone()["c"]
                )
                if used == 0:
                    conn.execute(
                        """
                        UPDATE memory_entities
                        SET status = 'invalidated', updated_at = ?
                        WHERE entity_id = ? AND user_id = ?
                          AND status != 'invalidated'
                        """,
                        (now, entity_id, user_id),
                    )
                    entity_count += 1

    split_entity_ids: set[str] = set()
    touched_merges = find_merges_touching_evidence(
        conn,
        user_id,
        alias_ids=invalidated_alias_ids,
        verdict_ids=invalidated_verdict_ids,
        mention_ids=men_ids,
    )
    if touched_merges:
        split_events = []
        for merge_row in touched_merges:
            winner_id = str(merge_row["winner_entity_id"])
            loser_id = str(merge_row["loser_entity_id"])
            split_entity_ids.update({winner_id, loser_id})
            split_events.append(
                build_split_event(
                    user_id=user_id,
                    winner_entity_id=winner_id,
                    loser_entity_id=loser_id,
                    cluster_key=merge_row.get("cluster_key"),
                    tier=str(merge_row["tier"]),
                    evidence={
                        "invalidation_reason": "evidence_invalidated",
                        "reverted_merge_event_id": str(merge_row["event_id"]),
                        "alias_ids": list(invalidated_alias_ids),
                        "verdict_ids": list(invalidated_verdict_ids),
                        "mention_ids": list(men_ids),
                    },
                    reason="evidence_invalidated",
                    decided_by="deterministic",
                    merge_event_id=str(merge_row["event_id"]),
                )
            )
            conn.execute(
                """
                UPDATE memory_entity_resolution_events
                SET status = 'reverted'
                WHERE event_id = ? AND user_id = ?
                """,
                (str(merge_row["event_id"]), user_id),
            )
        insert_events_in_txn(conn, user_id, split_events, resolution_run_id=None, now=now)

    if split_entity_ids:
        for entity_id in sorted(split_entity_ids):
            rows = conn.execute(
                """
                SELECT DISTINCT proposition_key
                FROM memory_assertions
                WHERE user_id = ?
                  AND status IN ('active', 'historical')
                  AND resolved_arguments_json LIKE ?
                """,
                (user_id, f"%{entity_id}%"),
            ).fetchall()
            for row in rows:
                proposition_keys.add(str(row["proposition_key"]))

    belief_recompute = 0
    for prop in sorted(proposition_keys):
        if _recompute_belief_after_invalidation(
            conn, user_id=user_id, proposition_key=prop, now=now
        ):
            belief_recompute += 1

    return ResolutionInvalidationResult(
        assertion_count=assertion_count,
        link_count=link_count,
        verdict_count=verdict_count,
        alias_count=alias_count,
        entity_count=entity_count,
        belief_recompute_count=belief_recompute,
    )


def _recompute_belief_after_invalidation(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    proposition_key: str,
    now: str,
) -> bool:
    from memory.resolution.store import _insert_belief_revision_in_txn

    belief_id = make_belief_id(user_id=user_id, proposition_key=proposition_key)
    belief = conn.execute(
        "SELECT belief_id, schema_name, cluster_key FROM memory_beliefs WHERE belief_id = ?",
        (belief_id,),
    ).fetchone()
    if belief is None:
        return False
    rows = conn.execute(
        """
        SELECT *
        FROM memory_assertions
        WHERE user_id = ? AND proposition_key = ?
          AND status IN ('active', 'historical', 'invalidated')
        ORDER BY created_at, assertion_id
        """,
        (user_id, proposition_key),
    ).fetchall()
    supporting = [_row_to_assertion(row) for row in rows]
    if not supporting:
        return False

    entity_ids = {
        arg.entity_id
        for assertion in supporting
        for arg in assertion.resolved_arguments
        if arg.value_kind == "entity" and arg.entity_id
    }
    entity_by_id: dict[str, EntityRecord] = {}
    if entity_ids:
        placeholders = ",".join("?" for _ in entity_ids)
        for row in conn.execute(
            f"""
            SELECT entity_id, entity_type, identity_key, canonical_label, status
            FROM memory_entities
            WHERE user_id = ? AND entity_id IN ({placeholders})
            """,
            (user_id, *sorted(entity_ids)),
        ).fetchall():
            entity_by_id[str(row["entity_id"])] = EntityRecord(
                entity_id=str(row["entity_id"]),
                entity_type=str(row["entity_type"]),
                identity_key=str(row["identity_key"]),
                canonical_label=str(row["canonical_label"]),
                status=str(row["status"]),
                decision="loaded",
            )

    anchor = next(
        (item for item in supporting if item.status == "active"),
        supporting[-1],
    )
    prior = conn.execute(
        "SELECT belief_revision_id FROM memory_belief_heads WHERE belief_id = ? AND user_id = ?",
        (belief_id, user_id),
    ).fetchone()
    prior_id = str(prior["belief_revision_id"]) if prior else None
    revision = reconcile_belief(
        user_id=user_id,
        assertion=anchor,
        supporting_assertions=supporting,
        entity_by_id=entity_by_id,
        is_correction=False,
        prior_head_revision_id=prior_id,
    )
    links: list[LineageInput] = []
    _insert_belief_revision_in_txn(
        conn,
        user_id=user_id,
        revision=revision,
        set_belief_head=True,
        now=now,
        links=links,
    )
    return True


def rebuild_ready_candidates(
    service: "MemoryService",
    *,
    user_id: int | None = None,
    limit: int = 100,
    required_verification_policy: str,
    support_profile: str = "extraction",
    adversarial_profile: str = "agent",
    candidate_generation_enabled: bool = False,
    fuzzy_blocking_enabled: bool = False,
    fuzzy_min_trigram: float = 0.6,
    cross_language_enabled: bool = False,
    cluster_critic_enabled: bool = False,
    merge_events_enabled: bool = False,
    max_candidates: int = 8,
) -> ResolutionRebuildResult:
    """Enqueue resolution jobs for ready candidates missing current-version assertions."""
    rows = service.resolution.list_schedulable(
        required_verification_policy=required_verification_policy,
        limit=limit,
    )
    if user_id is not None:
        rows = [row for row in rows if int(row["user_id"]) == user_id]
    created = 0
    for row in rows:
        result = service.jobs.enqueue(
            int(row["user_id"]),
            str(row["source_version_id"]),
            resolution_job_request(
                str(row["candidate_id"]),
                score_id=str(row["score_id"]),
                verdict_set_hash=str(row["verdict_set_hash"]),
                required_verification_policy=required_verification_policy,
                support_profile=support_profile,
                adversarial_profile=adversarial_profile,
                candidate_generation_enabled=candidate_generation_enabled,
                fuzzy_blocking_enabled=fuzzy_blocking_enabled,
                fuzzy_min_trigram=fuzzy_min_trigram,
                cross_language_enabled=cross_language_enabled,
                cluster_critic_enabled=cluster_critic_enabled,
                merge_events_enabled=merge_events_enabled,
                max_candidates=max_candidates,
            ),
        )
        if result.created:
            created += 1
            continue
        # Same deterministic job_id already exists (often done). Reopen terminal
        # jobs so assertion-less ready candidates are resolved again.
        if service.jobs.reopen_terminal_job(
            result.job_id,
            user_id=int(row["user_id"]),
            reason="resolution_rebuild",
        ):
            created += 1
    return ResolutionRebuildResult(candidates_seen=len(rows), jobs_created=created)
