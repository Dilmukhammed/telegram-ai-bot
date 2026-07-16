from __future__ import annotations

from typing import Any, Mapping, Sequence

from memory.retrieval.corpus import BeliefHeadDoc, EntityDoc
from memory.retrieval.schemas import MemoryContextPack, RetrievalHit


def build_context_pack(
    *,
    graph_revision: int,
    query_time: str,
    fused_hits: Sequence[RetrievalHit],
    beliefs: Sequence[BeliefHeadDoc],
    entities: Sequence[EntityDoc],
    token_budget: int,
    max_beliefs: int,
) -> MemoryContextPack:
    belief_by_id = {doc.belief_id: doc for doc in beliefs}
    entity_by_id = {doc.entity_id: doc for doc in entities}

    pack_entities: list[dict[str, Any]] = []
    pack_beliefs: list[dict[str, Any]] = []
    uncertainties: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    timelines: list[dict[str, Any]] = []
    chat_hits: list[dict[str, Any]] = []
    tool_hits: list[dict[str, Any]] = []
    document_hits: list[dict[str, Any]] = []
    exact = False
    used_tokens = 80  # envelope overhead

    seen_beliefs: set[str] = set()
    seen_entities: set[str] = set()

    for hit in fused_hits:
        if hit.item_kind == "entity" and hit.entity_id:
            if hit.entity_id in seen_entities:
                continue
            entity = entity_by_id.get(hit.entity_id)
            entry = {
                "entity_id": hit.entity_id,
                "label": hit.label,
                "summary": hit.statement,
                "match_status": entity.status if entity else "unknown",
                "score": hit.score,
            }
            cost = _estimate_tokens(entry)
            if used_tokens + cost > token_budget:
                break
            pack_entities.append(entry)
            seen_entities.add(hit.entity_id)
            used_tokens += cost
            continue

        if hit.item_kind == "chat_chunk":
            entry = {
                "item_id": hit.item_id,
                "label": hit.label,
                "text": hit.statement,
                "score": hit.score,
                "metadata": dict(hit.metadata),
            }
            cost = _estimate_tokens(entry)
            if used_tokens + cost > token_budget:
                break
            chat_hits.append(entry)
            used_tokens += cost
            continue

        if hit.item_kind == "tool_result":
            entry = {
                "item_id": hit.item_id,
                "label": hit.label,
                "text": hit.statement,
                "score": hit.score,
                "metadata": dict(hit.metadata),
            }
            cost = _estimate_tokens(entry)
            if used_tokens + cost > token_budget:
                break
            tool_hits.append(entry)
            used_tokens += cost
            continue

        if hit.item_kind == "document":
            entry = {
                "item_id": hit.item_id,
                "label": hit.label,
                "text": hit.statement,
                "score": hit.score,
                "metadata": dict(hit.metadata),
                "support_pointers": list(hit.support_pointers),
            }
            cost = _estimate_tokens(entry)
            if used_tokens + cost > token_budget:
                break
            document_hits.append(entry)
            if hit.support_pointers:
                exact = True
            used_tokens += cost
            continue

        belief_id = hit.belief_id or (hit.item_id if hit.item_kind == "belief" else None)
        if not belief_id or belief_id in seen_beliefs:
            continue
        if len(pack_beliefs) + len(uncertainties) >= max_beliefs:
            break
        doc = belief_by_id.get(belief_id)
        entry = {
            "belief_id": belief_id,
            "statement": hit.statement or (doc.statement if doc else ""),
            "status": hit.status or (doc.belief_status if doc else None),
            "utility_class": hit.utility_class or (doc.utility_class if doc else None),
            "polarity": hit.polarity or (doc.polarity if doc else None),
            "schema_name": doc.schema_name if doc else hit.label,
            "valid_time": dict(doc.temporal) if doc and doc.temporal else None,
            "support_pointers": list(hit.support_pointers or (doc.support_pointers if doc else ())),
            "score": hit.score,
            "hop_distance": hit.hop_distance,
        }
        cost = _estimate_tokens(entry)
        if used_tokens + cost > token_budget:
            break
        status = str(entry.get("status") or "")
        if status in {"uncertain"}:
            uncertainties.append(entry)
        elif status == "historical" or (doc and doc.polarity == "unknown"):
            timelines.append(entry)
        else:
            pack_beliefs.append(entry)
        if entry["support_pointers"]:
            exact = True
        seen_beliefs.add(belief_id)
        used_tokens += cost

        for entity_id in doc.entity_ids if doc else ():
            if entity_id in seen_entities:
                continue
            entity = entity_by_id.get(entity_id)
            if entity is None:
                continue
            ent_entry = {
                "entity_id": entity.entity_id,
                "label": entity.canonical_label,
                "summary": f"{entity.entity_type}: {entity.canonical_label}",
                "match_status": entity.status,
            }
            cost = _estimate_tokens(ent_entry)
            if used_tokens + cost > token_budget:
                break
            pack_entities.append(ent_entry)
            seen_entities.add(entity_id)
            used_tokens += cost

    # Soft contradiction signal: active positive+negative same schema in pack.
    by_schema: dict[str, set[str]] = {}
    for entry in pack_beliefs:
        schema = str(entry.get("schema_name") or "")
        pol = str(entry.get("polarity") or "")
        by_schema.setdefault(schema, set()).add(pol)
    for schema, pols in by_schema.items():
        if {"positive", "negative"} <= pols:
            contradictions.append(
                {
                    "schema_name": schema,
                    "reason": "polarity_conflict_in_pack",
                }
            )

    return MemoryContextPack(
        graph_revision=graph_revision,
        query_time=query_time,
        entities=tuple(pack_entities),
        beliefs=tuple(pack_beliefs),
        uncertainties=tuple(uncertainties),
        contradictions=tuple(contradictions),
        timelines=tuple(timelines),
        chat_hits=tuple(chat_hits),
        tool_hits=tuple(tool_hits),
        document_hits=tuple(document_hits),
        exact_evidence_available=exact,
        token_estimate=used_tokens,
    )


def _estimate_tokens(payload: Mapping[str, Any]) -> int:
    text = str(payload)
    return max(1, len(text) // 4)
