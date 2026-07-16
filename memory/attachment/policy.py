from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from memory.attachment.schemas import (
    TIER_CURATED,
    TIER_HYBRID,
    TIER_LLM_COMMITTEE,
    UTILITY_DEFERRED,
    UTILITY_DURABLE,
    AttachmentHypothesis,
)
from memory.db import utc_now_iso
from memory.ids import make_attachment_negative_id


def classify_risk(
    *,
    hypothesis: AttachmentHypothesis | None,
    curated: bool,
    hybrid_score: float,
) -> str:
    if hypothesis is None:
        return "abstain"
    if hypothesis.op in {"inferred_preference", "same_as"}:
        return "high"
    if curated:
        return "low"
    if hybrid_score >= 0.5:
        return "mid"
    return "high"


def layers_for_risk(risk: str, *, verify_enabled: bool) -> frozenset[str]:
    if risk == "low":
        return frozenset({"L5"} if verify_enabled else set())
    if risk == "mid":
        return frozenset({"L4", "L5", "L6"})
    if risk == "high":
        return frozenset({"L4", "L5", "L6", "L7", "L8"})
    return frozenset()


def decide_utility_class(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    source_entity_id: str,
    op: str,
    target_entity_id: str,
    explicit_cuisine: bool = False,
    user_explicit: bool = False,
) -> str:
    if op == "inferred_preference":
        count = conn.execute(
            """
            SELECT COUNT(DISTINCT source_entity_id) AS c
            FROM memory_attachment_events
            WHERE user_id = ? AND op = 'cuisine_of'
              AND target_entity_id = ? AND status = 'active'
            """,
            (user_id, target_entity_id),
        ).fetchone()
        dishes = int(count["c"]) if count else 0
        if user_explicit:
            return UTILITY_DURABLE
        if dishes >= 1:
            return UTILITY_DEFERRED
        return UTILITY_DEFERRED if dishes == 0 else UTILITY_DEFERRED

    if op in {
        "alias_of",
        "cuisine_of",
        "topic_of",
        "instance_of",
        "subtype_of",
        "part_of",
        "located_in",
    }:
        if user_explicit:
            return UTILITY_DURABLE
        prior = conn.execute(
            """
            SELECT COUNT(*) AS c FROM memory_attachment_events
            WHERE user_id = ? AND source_entity_id = ? AND op = ?
              AND target_entity_id = ? AND status = 'active'
            """,
            (user_id, source_entity_id, op, target_entity_id),
        ).fetchone()
        if prior and int(prior["c"]) > 0:
            return UTILITY_DURABLE
        corroboration = conn.execute(
            """
            SELECT COUNT(DISTINCT source_entity_id) AS c
            FROM memory_attachment_events
            WHERE user_id = ? AND op = ? AND target_entity_id = ?
              AND status = 'active'
            """,
            (user_id, op, target_entity_id),
        ).fetchone()
        if corroboration and int(corroboration["c"]) >= 1:
            return UTILITY_DURABLE
        return UTILITY_DEFERRED

    if op == "same_as":
        return UTILITY_DEFERRED
    return UTILITY_DEFERRED


def infer_tier(*, curated: bool, llm_calls: int) -> str:
    if curated and llm_calls == 0:
        return TIER_CURATED
    if llm_calls <= 1:
        return TIER_HYBRID
    return TIER_LLM_COMMITTEE


def should_defer_inferred_preference(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    target_entity_id: str,
) -> bool:
    """First dish alone never durable inferred_preference."""
    row = conn.execute(
        """
        SELECT COUNT(*) AS c FROM memory_attachment_events
        WHERE user_id = ? AND op = 'cuisine_of' AND target_entity_id = ?
          AND status = 'active'
        """,
        (user_id, target_entity_id),
    ).fetchone()
    return not row or int(row["c"]) < 2


def insert_negative(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    source_entity_id: str,
    op: str,
    target_entity_id: str,
    reason: str,
    layer: str,
) -> str:
    negative_id = make_attachment_negative_id(
        user_id=user_id,
        source_entity_id=source_entity_id,
        op=op,
        target_entity_id=target_entity_id,
    )
    now = utc_now_iso()
    conn.execute(
        """
        INSERT OR REPLACE INTO memory_attachment_negatives(
            negative_id, user_id, source_entity_id, op, target_entity_id,
            reason, layer, status, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', NULL, ?)
        """,
        (
            negative_id,
            user_id,
            source_entity_id,
            op,
            target_entity_id,
            reason,
            layer,
            now,
        ),
    )
    return negative_id
