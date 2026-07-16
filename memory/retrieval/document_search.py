from __future__ import annotations

import math
import time
from collections import Counter
from typing import TYPE_CHECKING

from bot.chat_index.chunking import token_list
from memory.documents.models import EXTRACTABLE_DOCUMENT_SEGMENT_TYPES
from memory.retrieval.schemas import CHANNEL_DOCUMENT, ChannelResult, RetrievalHit

if TYPE_CHECKING:
    from memory.db import MemoryDatabase


def search_documents(
    *,
    user_id: int,
    query: str,
    db: "MemoryDatabase",
    limit: int = 20,
) -> ChannelResult:
    started = time.perf_counter()
    types = sorted(EXTRACTABLE_DOCUMENT_SEGMENT_TYPES)
    placeholders = ",".join("?" for _ in types)
    with db.connection() as conn:
        rows = conn.execute(
            f"""
            SELECT seg.segment_id, seg.segment_type, seg.text, seg.pointer_json,
                   seg.source_version_id
            FROM memory_segments seg
            JOIN memory_source_versions v
              ON v.source_version_id = seg.source_version_id
            JOIN memory_sources s ON s.source_id = v.source_id
            WHERE s.user_id = ?
              AND s.source_type = 'document'
              AND seg.status = 'active'
              AND seg.segment_type IN ({placeholders})
              AND seg.text IS NOT NULL
              AND TRIM(seg.text) != ''
            ORDER BY seg.created_at DESC
            LIMIT 500
            """,
            (user_id, *types),
        ).fetchall()
    docs = [dict(row) for row in rows]
    texts = [str(row["text"] or "") for row in docs]
    scores = _bm25(query, texts)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    hits: list[RetrievalHit] = []
    for idx, score in ranked[:limit]:
        row = docs[idx]
        hits.append(
            RetrievalHit(
                channel=CHANNEL_DOCUMENT,
                item_id=str(row["segment_id"]),
                item_kind="document",
                score=float(score),
                label=str(row["segment_type"]),
                statement=str(row["text"] or "")[:800],
                support_pointers=(str(row["pointer_json"]),),
                metadata={
                    "segment_id": row["segment_id"],
                    "segment_type": row["segment_type"],
                    "source_version_id": row["source_version_id"],
                    "pointer_json": row["pointer_json"],
                },
            )
        )
    return ChannelResult(
        channel=CHANNEL_DOCUMENT,
        hits=tuple(hits),
        latency_ms=(time.perf_counter() - started) * 1000.0,
        skipped=False,
    )


def _bm25(query: str, documents: list[str]) -> dict[int, float]:
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
