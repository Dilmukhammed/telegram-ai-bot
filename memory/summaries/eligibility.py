from __future__ import annotations

from memory.summaries.schemas import (
    SUMMARY_TYPE_ACTIVE_STATE,
    SUMMARY_TYPE_CORE_PROFILE,
    SUMMARY_TYPE_ENTITY,
    SUMMARY_TYPE_TIMELINE_ENTITY,
    SUMMARY_TYPE_TIMELINE_USER,
    BeliefSnapshot,
    user_target_id,
)

_DEFERRED_UTILITY = frozenset({"deferred", "ephemeral"})
_ACTIVE_STATE_STATUSES = frozenset({"active", "uncertain", "disputed"})
_TIMELINE_STATUSES = frozenset({"historical", "uncertain"})
_TIMELINE_SCHEMA_HINTS = (
    "had_",
    "completed",
    "event",
    "travel",
    "trip",
    "visited",
    "moved",
    "before",
)


def eligible_for_summary_type(
    beliefs: tuple[BeliefSnapshot, ...],
    *,
    summary_type: str,
    target_id: str,
    member_belief_ids: frozenset[str] | None = None,
) -> tuple[BeliefSnapshot, ...]:
    if summary_type == SUMMARY_TYPE_CORE_PROFILE:
        return beliefs_for_core_profile(beliefs)
    if summary_type == SUMMARY_TYPE_ENTITY:
        return beliefs_for_entity(beliefs, entity_id=target_id)
    if summary_type == SUMMARY_TYPE_TIMELINE_USER:
        return beliefs_for_timeline(beliefs, scope_user=True, entity_id=None)
    if summary_type == SUMMARY_TYPE_TIMELINE_ENTITY:
        return beliefs_for_timeline(beliefs, scope_user=False, entity_id=target_id)
    if summary_type == SUMMARY_TYPE_ACTIVE_STATE:
        return beliefs_for_active_state(beliefs)
    if member_belief_ids is not None:
        return tuple(b for b in beliefs if b.belief_id in member_belief_ids)
    return ()


def beliefs_for_core_profile(
    beliefs: tuple[BeliefSnapshot, ...],
) -> tuple[BeliefSnapshot, ...]:
    return tuple(
        b
        for b in beliefs
        if b.belief_status == "active"
        and b.utility_class == "durable"
        and b.utility_class not in _DEFERRED_UTILITY
    )


def beliefs_for_entity(
    beliefs: tuple[BeliefSnapshot, ...],
    *,
    entity_id: str,
) -> tuple[BeliefSnapshot, ...]:
    return tuple(
        b
        for b in beliefs
        if b.utility_class == "durable" and entity_id in b.entity_ids
    )


def beliefs_for_timeline(
    beliefs: tuple[BeliefSnapshot, ...],
    *,
    scope_user: bool,
    entity_id: str | None,
) -> tuple[BeliefSnapshot, ...]:
    out: list[BeliefSnapshot] = []
    for belief in beliefs:
        if belief.belief_status not in _TIMELINE_STATUSES:
            schema = belief.schema_name.casefold()
            if not any(hint in schema for hint in _TIMELINE_SCHEMA_HINTS):
                continue
        if scope_user:
            out.append(belief)
        elif entity_id and entity_id in belief.entity_ids:
            out.append(belief)
    return tuple(out)


def beliefs_for_active_state(
    beliefs: tuple[BeliefSnapshot, ...],
) -> tuple[BeliefSnapshot, ...]:
    return tuple(
        b
        for b in beliefs
        if b.belief_status in _ACTIVE_STATE_STATUSES
        or b.utility_class in {"task", "goal", "booking", "identifier"}
        or b.polarity == "unknown"
    )


def default_targets_for_user(
    *,
    user_id: int,
    entity_ids: tuple[str, ...],
    community_ids: tuple[str, ...],
) -> list[tuple[str, str]]:
    uid = user_target_id(user_id)
    targets: list[tuple[str, str]] = [
        (SUMMARY_TYPE_CORE_PROFILE, uid),
        (SUMMARY_TYPE_TIMELINE_USER, uid),
        (SUMMARY_TYPE_ACTIVE_STATE, uid),
    ]
    targets.extend((SUMMARY_TYPE_ENTITY, eid) for eid in entity_ids)
    targets.extend((SUMMARY_TYPE_TIMELINE_ENTITY, eid) for eid in entity_ids)
    from memory.summaries.schemas import SUMMARY_TYPE_COMMUNITY

    targets.extend((SUMMARY_TYPE_COMMUNITY, cid) for cid in community_ids)
    return targets
