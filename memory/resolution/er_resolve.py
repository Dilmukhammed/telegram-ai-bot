from __future__ import annotations

import sqlite3
from typing import Any, Mapping, Sequence

from memory.ids import make_alias_id, make_entity_id, make_mention_link_id
from memory.resolution.candidates import generate_candidates
from memory.resolution.cluster import gate_t2_with_critics
from memory.resolution.critics import LinkCriticModel, critique_proposed_alias
from memory.resolution.entities import accept_proposed_alias
from memory.resolution.er_types import ErConfig, ErMentionResult, MergeEventRecord, PairVerdict
from memory.resolution.events_store import build_merge_event
from memory.resolution.normalization import display_label, lookup_key
from memory.resolution.pairwise import (
    deterministic_gate,
    proposal_from_candidate,
    unique_winner,
)
from memory.resolution.schemas import (
    EXACT_ALIAS_TYPES,
    RESOLVER_VERSION,
    AliasRecord,
    EntityRecord,
    MentionLinkRecord,
    ResolutionVerdictRecord,
    ResolvedArgument,
)


async def resolve_mention_with_er(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    role: str,
    mention: Mapping[str, Any],
    support_model: LinkCriticModel | None,
    adversarial_model: LinkCriticModel | None,
    neighboring_arguments: Sequence[Mapping[str, Any]] | None = None,
    source_authority: str | None = None,
    source_occurred_at: str | None = None,
    config: ErConfig,
    resolution_run_id: str | None = None,
) -> ErMentionResult:
    """Full PR11 mention resolution. Fail-closed; person merges only on stable_id.

    When ``config.candidate_generation_enabled`` is False this returns a provisional
    entity only. The pipeline must not call this helper unless that flag is on;
    the classic PR5 ``resolve_mention_argument`` path stays byte-identical when ER
    flags are off.
    """
    mention_id = str(mention["mention_id"])
    mention_type = str(mention.get("mention_type") or "unknown")
    surface = display_label(mention.get("surface_text") or "")
    normalized = lookup_key(surface)
    neighbors = list(neighboring_arguments or ())

    provisional_entity = _provisional_entity(
        user_id=user_id,
        mention_id=mention_id,
        mention_type=mention_type,
        surface=surface,
    )
    provisional_link = _provisional_link(
        mention_id=mention_id,
        entity=provisional_entity,
        mention_type=mention_type,
        normalized=normalized,
        decision="provisional_new",
    )
    provisional_alias = _provisional_alias(
        user_id=user_id,
        mention_id=mention_id,
        entity_id=provisional_entity.entity_id,
        surface=surface,
        normalized=normalized,
        mention_type=mention_type,
    )

    if not config.candidate_generation_enabled:
        return ErMentionResult(
            resolved=ResolvedArgument(
                role=role,
                value_kind="entity",
                entity_id=provisional_entity.entity_id,
            ),
            entity=provisional_entity,
            alias=provisional_alias,
            link=provisional_link,
            verdicts=(),
            merge_events=(),
            provisional_entity=provisional_entity,
        )

    candidate_set = generate_candidates(
        conn,
        user_id,
        mention,
        fuzzy_enabled=config.fuzzy_blocking_enabled,
        fuzzy_min_trigram=config.fuzzy_min_trigram,
        cross_language_enabled=config.cross_language_enabled,
        max_candidates=config.max_candidates,
    )

    pair_verdicts: list[PairVerdict] = []
    critic_verdicts: list[ResolutionVerdictRecord] = []

    for candidate in candidate_set.candidates:
        reject_reason = deterministic_gate(mention_type, candidate)
        if reject_reason is not None:
            continue

        if candidate.tier == "stable_id":
            pair_verdicts.append(
                PairVerdict(
                    entity_id=candidate.entity_id,
                    accepted=True,
                    reason="stable_id_auto",
                    tier=candidate.tier,
                    decided_by="deterministic",
                )
            )
            continue

        proposal = proposal_from_candidate(
            conn,
            user_id=user_id,
            mention=mention,
            role=role,
            candidate=candidate,
        )

        if candidate.tier == "exact_alias":
            accepted, verdicts, reason = await critique_proposed_alias(
                proposal,
                support_model=support_model,
                adversarial_model=adversarial_model,
                neighboring_arguments=neighbors,
                source_authority=source_authority,
                source_occurred_at=source_occurred_at,
            )
            critic_verdicts.extend(verdicts)
            pair_verdicts.append(
                PairVerdict(
                    entity_id=candidate.entity_id,
                    accepted=accepted,
                    reason=reason,
                    tier=candidate.tier,
                    decided_by="critic",
                )
            )
            continue

        cluster_verdict, cluster_critic_verdicts = await gate_t2_with_critics(
            conn,
            user_id=user_id,
            mention=mention,
            role=role,
            proposal=proposal,
            incoming_mention_type=mention_type,
            support_model=support_model,
            adversarial_model=adversarial_model,
            neighboring_arguments=neighbors,
            source_authority=source_authority,
            source_occurred_at=source_occurred_at,
            cluster_critic_enabled=config.cluster_critic_enabled,
        )
        critic_verdicts.extend(cluster_critic_verdicts)
        pair_verdicts.append(
            PairVerdict(
                entity_id=candidate.entity_id,
                accepted=cluster_verdict.accepted,
                reason=cluster_verdict.reason,
                tier=candidate.tier,
                decided_by=cluster_verdict.decided_by,
            )
        )

    winner = unique_winner(pair_verdicts)
    if winner is None:
        return ErMentionResult(
            resolved=ResolvedArgument(
                role=role,
                value_kind="entity",
                entity_id=provisional_entity.entity_id,
            ),
            entity=provisional_entity,
            alias=provisional_alias,
            link=_provisional_link(
                mention_id=mention_id,
                entity=provisional_entity,
                mention_type=mention_type,
                normalized=normalized,
                decision="provisional_new",
                extra_components={
                    "er_reason": "no_unique_winner",
                    "candidate_count": len(candidate_set.candidates),
                },
            ),
            verdicts=tuple(critic_verdicts),
            merge_events=(),
            provisional_entity=provisional_entity,
        )

    winning_candidate = next(
        item for item in candidate_set.candidates if item.entity_id == winner.entity_id
    )
    proposal = proposal_from_candidate(
        conn,
        user_id=user_id,
        mention=mention,
        role=role,
        candidate=winning_candidate,
    )
    resolved, entity, alias, link = accept_proposed_alias(
        user_id=user_id,
        role=role,
        mention=mention,
        proposal=proposal,
    )
    link = MentionLinkRecord(
        link_id=link.link_id,
        mention_id=link.mention_id,
        entity_id=link.entity_id,
        decision=link.decision,
        resolution_components={
            **dict(link.resolution_components),
            "er_tier": winner.tier,
            "er_reason": winner.reason,
            "er_decided_by": winner.decided_by,
            "audit_provisional_entity_id": provisional_entity.entity_id,
        },
    )

    merge_events: list[MergeEventRecord] = []
    if (
        config.merge_events_enabled
        and provisional_entity.entity_id != entity.entity_id
        and not (
            mention_type == "person" and winning_candidate.tier != "stable_id"
        )
    ):
        merge_events.append(
            build_merge_event(
                user_id=user_id,
                winner_entity_id=entity.entity_id,
                loser_entity_id=provisional_entity.entity_id,
                cluster_key=mention_id,
                tier=winner.tier,
                evidence={
                    "mention_id": mention_id,
                    "mention_type": mention_type,
                    "normalized_alias": normalized,
                    "pair_reason": winner.reason,
                    "resolution_verdict_ids": [
                        item.resolution_verdict_id for item in critic_verdicts
                    ],
                },
                reason=winner.reason,
                decided_by=winner.decided_by,
                resolution_run_id=resolution_run_id,
            )
        )

    return ErMentionResult(
        resolved=resolved,
        entity=entity,
        alias=alias if mention_type in EXACT_ALIAS_TYPES and normalized else None,
        link=link,
        verdicts=tuple(critic_verdicts),
        merge_events=tuple(merge_events),
        provisional_entity=provisional_entity,
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


def _provisional_link(
    *,
    mention_id: str,
    entity: EntityRecord,
    mention_type: str,
    normalized: str,
    decision: str,
    extra_components: Mapping[str, Any] | None = None,
) -> MentionLinkRecord:
    components: dict[str, Any] = {
        "mention_type": mention_type,
        "normalized_alias": normalized,
        "decision": decision,
    }
    if extra_components:
        components.update(dict(extra_components))
    return MentionLinkRecord(
        link_id=make_mention_link_id(
            mention_id=mention_id,
            entity_id=entity.entity_id,
            resolver_version=RESOLVER_VERSION,
        ),
        mention_id=mention_id,
        entity_id=entity.entity_id,
        decision=decision,
        resolution_components=components,
    )


def _provisional_alias(
    *,
    user_id: int,
    mention_id: str,
    entity_id: str,
    surface: str,
    normalized: str,
    mention_type: str,
) -> AliasRecord | None:
    if mention_type not in EXACT_ALIAS_TYPES or not normalized:
        return None
    return AliasRecord(
        alias_id=make_alias_id(
            user_id=user_id,
            entity_id=entity_id,
            normalized_alias=normalized,
            source_mention_id=mention_id,
        ),
        entity_id=entity_id,
        source_mention_id=mention_id,
        alias=surface,
        normalized_alias=normalized,
    )
