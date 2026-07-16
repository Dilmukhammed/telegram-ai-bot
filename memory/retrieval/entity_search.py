from __future__ import annotations

import math
import time
from collections import Counter
from typing import Sequence

from bot.chat_index.chunking import token_list
from memory.retrieval.corpus import (
    BeliefHeadDoc,
    EntityDoc,
    match_entity_surface,
)
from memory.retrieval.schemas import (
    CHANNEL_ENTITY,
    CHANNEL_LEXICAL,
    ChannelResult,
    RetrievalHit,
)


def search_entities(
    *,
    query: str,
    entities: Sequence[EntityDoc],
    plan_entities: Sequence[str],
) -> ChannelResult:
    started = time.perf_counter()
    hits: list[RetrievalHit] = []
    surfaces = list(plan_entities) + _tokens(query)
    seen: set[str] = set()
    for entity in entities:
        score = 0.0
        for surface in surfaces:
            if match_entity_surface(entity, surface):
                score = max(score, 1.0 if surface in plan_entities else 0.75)
        if score <= 0:
            continue
        if entity.entity_id in seen:
            continue
        seen.add(entity.entity_id)
        hits.append(
            RetrievalHit(
                channel=CHANNEL_ENTITY,
                item_id=entity.entity_id,
                item_kind="entity",
                score=score,
                label=entity.canonical_label,
                statement=f"{entity.entity_type}: {entity.canonical_label}",
                entity_id=entity.entity_id,
                status=entity.status,
                metadata={"aliases": list(entity.aliases)},
            )
        )
    hits.sort(key=lambda item: (-item.score, item.label, item.item_id))
    return ChannelResult(
        channel=CHANNEL_ENTITY,
        hits=tuple(hits[:50]),
        latency_ms=(time.perf_counter() - started) * 1000.0,
    )


def search_lexical(
    *,
    query: str,
    beliefs: Sequence[BeliefHeadDoc],
    limit: int = 40,
) -> ChannelResult:
    started = time.perf_counter()
    scores = _bm25(query, [doc.search_text for doc in beliefs])
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    hits: list[RetrievalHit] = []
    for idx, score in ranked[:limit]:
        doc = beliefs[idx]
        hits.append(
            RetrievalHit(
                channel=CHANNEL_LEXICAL,
                item_id=doc.belief_id,
                item_kind="belief",
                score=float(score),
                label=doc.schema_name,
                statement=doc.statement,
                belief_id=doc.belief_id,
                status=doc.belief_status,
                utility_class=doc.utility_class,
                polarity=doc.polarity,
                support_pointers=doc.support_pointers,
                metadata={"schema_name": doc.schema_name},
            )
        )
    return ChannelResult(
        channel=CHANNEL_LEXICAL,
        hits=tuple(hits),
        latency_ms=(time.perf_counter() - started) * 1000.0,
    )


def _tokens(query: str) -> list[str]:
    return [token for token in token_list(query) if len(token) >= 3][:20]


def _bm25(query: str, documents: Sequence[str]) -> dict[int, float]:
    query_tokens = list(dict.fromkeys(token_list(query)))
    if not query_tokens or not documents:
        return {}
    doc_tokens = [token_list(doc) for doc in documents]
    avg_len = sum(len(tokens) for tokens in doc_tokens) / max(1, len(doc_tokens))
    document_frequency = Counter(
        token
        for tokens in doc_tokens
        for token in set(tokens)
        if token in query_tokens
    )
    total_docs = len(documents)
    k1 = 1.2
    b = 0.75
    scores: dict[int, float] = {}
    for idx, tokens in enumerate(doc_tokens):
        counts = Counter(tokens)
        doc_len = max(1, len(tokens))
        score = 0.0
        for token in query_tokens:
            frequency = counts.get(token, 0)
            if not frequency:
                continue
            df = document_frequency.get(token, 0)
            idf = math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5))
            norm = frequency + k1 * (1.0 - b + b * doc_len / max(1.0, avg_len))
            score += idf * (frequency * (k1 + 1.0) / norm)
        if score > 0:
            scores[idx] = score
    return scores
