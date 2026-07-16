from __future__ import annotations

from typing import Any, Mapping

from memory.retrieval.schemas import MemoryContextPack
from memory.summaries.schemas import (
    SUMMARY_TYPE_ACTIVE_STATE,
    SUMMARY_TYPE_COMMUNITY,
    SUMMARY_TYPE_CORE_PROFILE,
    SUMMARY_TYPE_ENTITY,
    user_target_id,
)
from memory.summaries.store import SummaryStore


def load_summary_shadow_pack(
    summaries: SummaryStore,
    *,
    user_id: int,
    entities: tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    uid = user_target_id(user_id)
    core = summaries.get_active(
        user_id=user_id,
        summary_type=SUMMARY_TYPE_CORE_PROFILE,
        target_id=uid,
    )
    active = summaries.get_active(
        user_id=user_id,
        summary_type=SUMMARY_TYPE_ACTIVE_STATE,
        target_id=uid,
    )
    community_rows = summaries.list_active_for_user(
        user_id=user_id,
        summary_types=(SUMMARY_TYPE_COMMUNITY,),
        limit=20,
    )
    entity_summaries: list[dict[str, Any]] = []
    for entity in entities:
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id:
            continue
        row = summaries.get_active(
            user_id=user_id,
            summary_type=SUMMARY_TYPE_ENTITY,
            target_id=entity_id,
        )
        if row is None:
            continue
        entity_summaries.append(
            {
                "entity_id": entity_id,
                "summary": row.content,
                "belief_ids": list(row.belief_ids),
                "sentence_support": {
                    k: list(v) for k, v in row.sentence_support.items()
                },
                "not_sole_evidence": True,
            }
        )
    return {
        "core_profile": _summary_mapping(core),
        "active_state": _summary_mapping(active),
        "community_summaries": [
            item
            for item in (_summary_mapping(row) for row in community_rows)
            if item is not None
        ],
        "entity_summaries": entity_summaries,
        "not_sole_evidence": True,
    }


def enrich_context_pack(
    pack: MemoryContextPack,
    *,
    summary_pack: Mapping[str, Any],
) -> MemoryContextPack:
    core = summary_pack.get("core_profile")
    active = summary_pack.get("active_state")
    communities = summary_pack.get("community_summaries") or ()
    entities = list(pack.entities)
    by_id = {str(item.get("entity_id")): dict(item) for item in entities}
    for entry in summary_pack.get("entity_summaries") or ():
        if not isinstance(entry, dict):
            continue
        entity_id = str(entry.get("entity_id") or "")
        if not entity_id:
            continue
        current = by_id.get(entity_id, {"entity_id": entity_id})
        current["summary"] = entry.get("summary") or current.get("summary")
        current["belief_ids"] = entry.get("belief_ids")
        current["sentence_support"] = entry.get("sentence_support")
        current["not_sole_evidence"] = True
        by_id[entity_id] = current
    return MemoryContextPack(
        graph_revision=pack.graph_revision,
        query_time=pack.query_time,
        entities=tuple(by_id.values()),
        beliefs=pack.beliefs,
        uncertainties=pack.uncertainties,
        contradictions=pack.contradictions,
        timelines=pack.timelines,
        chat_hits=pack.chat_hits,
        tool_hits=pack.tool_hits,
        document_hits=pack.document_hits,
        exact_evidence_available=pack.exact_evidence_available,
        token_estimate=pack.token_estimate,
        policy_version=pack.policy_version,
        core_profile=dict(core) if isinstance(core, dict) else None,
        active_state=dict(active) if isinstance(active, dict) else None,
        community_summaries=tuple(
            dict(item) for item in communities if isinstance(item, dict)
        ),
        summary_pack=dict(summary_pack),
    )


def _summary_mapping(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "summary_id": row.summary_id,
        "summary_type": row.summary_type,
        "target_id": row.target_id,
        "content": row.content,
        "belief_ids": list(row.belief_ids),
        "sentence_support": {k: list(v) for k, v in row.sentence_support.items()},
        "not_sole_evidence": True,
    }
