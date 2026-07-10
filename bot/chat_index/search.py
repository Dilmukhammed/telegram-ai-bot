from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

from bot.chat_index.chunking import token_list
from bot.chat_index.index_store import ChatSearchChunk, load_chunks_for_search, update_chunk_embeddings
from config import get_settings
from tools.embeddings import create_embedding_provider, get_embedding_provider_mode, get_embedding_settings
from tools.keyword_index import cosine_similarity

logger = logging.getLogger(__name__)

_RRF_K = 60
_EMBED_BATCH_SIZE = 64
_TURN_CONTEXT_MAX_CHARS = 3200
_provider = None
_provider_ready = False


async def _get_embedding_provider():
    global _provider, _provider_ready
    if _provider_ready:
        return _provider

    base_url, api_key, api_model, local_model = get_embedding_settings()
    provider_mode = get_embedding_provider_mode()
    if provider_mode != "keyword" and api_key:
        _provider = await create_embedding_provider(
            base_url=base_url,
            api_key=api_key,
            api_model=api_model,
            local_model=local_model,
            provider_mode=provider_mode,
        )
    _provider_ready = True
    return _provider


def reset_chat_search_embedding_provider() -> None:
    global _provider, _provider_ready
    _provider = None
    _provider_ready = False


def _bm25_scores(query: str, chunks: list[ChatSearchChunk]) -> dict[int, float]:
    query_tokens = list(dict.fromkeys(token_list(query)))
    if not query_tokens or not chunks:
        return {}

    doc_tokens = [token_list(chunk.text) for chunk in chunks]
    avg_len = sum(len(tokens) for tokens in doc_tokens) / max(1, len(doc_tokens))
    document_frequency = Counter(
        token
        for tokens in doc_tokens
        for token in set(tokens)
        if token in query_tokens
    )
    total_docs = len(chunks)
    k1 = 1.2
    b = 0.75
    scores: dict[int, float] = {}

    for chunk, tokens in zip(chunks, doc_tokens):
        counts = Counter(tokens)
        doc_len = max(1, len(tokens))
        score = 0.0
        matched = 0
        for token in query_tokens:
            frequency = counts.get(token, 0)
            if not frequency:
                continue
            matched += 1
            df = document_frequency.get(token, 0)
            idf = math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5))
            norm = frequency + k1 * (1.0 - b + b * doc_len / max(1.0, avg_len))
            score += idf * (frequency * (k1 + 1.0) / norm)

        if matched:
            coverage = matched / len(query_tokens)
            score *= 1.0 + 0.35 * coverage
            chunk_casefold = chunk.text.casefold()
            for token in query_tokens:
                if ("_" in token or "-" in token) and token in chunk_casefold:
                    score += 2.0
            scores[chunk.chunk_id] = score
    return scores


def _rank_lexical(query: str, chunks: list[ChatSearchChunk]) -> list[ChatSearchHit]:
    scores = _bm25_scores(query, chunks)
    ranked = [
        ChatSearchHit(score=scores.get(chunk.chunk_id, 0.0), chunk=chunk)
        for chunk in chunks
        if scores.get(chunk.chunk_id, 0.0) > 0
    ]
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


@dataclass(frozen=True)
class ChatSearchHit:
    score: float
    chunk: ChatSearchChunk


def _chunk_payload(
    chunk: ChatSearchChunk,
    score: float,
    *,
    turn_context: str | None = None,
) -> dict[str, Any]:
    return {
        "score": round(score, 4),
        "session_id": chunk.session_id,
        "started_at": chunk.session_started_at,
        "title": chunk.session_title,
        "session_summary": chunk.session_summary,
        "turn_number": chunk.turn_number,
        "seq_start": chunk.seq_start,
        "seq_end": chunk.seq_end,
        "tool_ref": chunk.tool_ref,
        "source_type": chunk.source_type,
        "text": chunk.text,
        "turn_context": turn_context,
    }


async def _rank_vector(
    conn,
    provider,
    query: str,
    chunks: list[ChatSearchChunk],
) -> list[ChatSearchHit]:
    if provider is None or not chunks:
        return []

    vector_by_id = {
        chunk.chunk_id: chunk.embedding
        for chunk in chunks
        if chunk.embedding
    }
    missing = [chunk for chunk in chunks if not chunk.embedding]
    for start in range(0, len(missing), _EMBED_BATCH_SIZE):
        batch = missing[start : start + _EMBED_BATCH_SIZE]
        vectors = await provider.embed_many([chunk.text for chunk in batch])
        updates = {
            chunk.chunk_id: vector
            for chunk, vector in zip(batch, vectors)
        }
        update_chunk_embeddings(conn, updates)
        vector_by_id.update(updates)
    if missing:
        conn.commit()

    query_vector = await provider.embed(query)
    ranked = [
        ChatSearchHit(
            score=cosine_similarity(query_vector, vector_by_id.get(chunk.chunk_id, [])),
            chunk=chunk,
        )
        for chunk in chunks
        if vector_by_id.get(chunk.chunk_id)
    ]
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def _rrf_fuse(
    lexical: list[ChatSearchHit],
    vector: list[ChatSearchHit],
    *,
    candidate_count: int,
) -> list[ChatSearchHit]:
    fused: dict[int, float] = {}
    chunks: dict[int, ChatSearchChunk] = {}
    for ranking in (lexical[:candidate_count], vector[:candidate_count]):
        for rank, item in enumerate(ranking, start=1):
            chunks[item.chunk.chunk_id] = item.chunk
            fused[item.chunk.chunk_id] = fused.get(item.chunk.chunk_id, 0.0) + 1.0 / (
                _RRF_K + rank
            )
    ranked = [
        ChatSearchHit(score=score, chunk=chunks[chunk_id])
        for chunk_id, score in fused.items()
    ]
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def _diversify(
    ranked: list[ChatSearchHit],
    *,
    limit: int,
    max_per_session: int,
) -> list[ChatSearchHit]:
    selected: list[ChatSearchHit] = []
    seen_contexts: set[tuple[Any, ...]] = set()
    per_session: Counter[str] = Counter()
    deferred: list[ChatSearchHit] = []

    for item in ranked:
        chunk = item.chunk
        if chunk.turn_number is not None:
            context_key = ("turn", chunk.session_id, chunk.turn_number)
        elif chunk.tool_ref is not None:
            context_key = ("tool_ref", chunk.tool_ref, chunk.source_type)
        else:
            context_key = ("source", chunk.source_type, chunk.source_key)
        if context_key in seen_contexts or per_session[chunk.session_id] >= max_per_session:
            deferred.append(item)
            continue
        seen_contexts.add(context_key)
        per_session[chunk.session_id] += 1
        selected.append(item)
        if len(selected) >= limit:
            return selected

    for item in deferred:
        if item in selected:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _turn_context(store, chunk: ChatSearchChunk) -> str | None:
    if chunk.turn_number is None:
        return None
    grouped = store.read_turns(chunk.session_id, [chunk.turn_number])
    messages = grouped.get(chunk.turn_number) or []
    parts: list[str] = []
    for message in messages:
        content = (message.content or "").strip()
        if not content:
            continue
        if len(content) > 1600:
            content = content[:1599] + "…"
        label = message.role
        if message.tool_name:
            label = f"{label}:{message.tool_name}"
        parts.append(f"{label}: {content}")
    context = "\n".join(parts).strip()
    if len(context) > _TURN_CONTEXT_MAX_CHARS:
        context = context[: _TURN_CONTEXT_MAX_CHARS - 1] + "…"
    return context or None


async def search_chat_chunks(
    user_id: int,
    query: str,
    *,
    session_id: str | None = None,
    date: str | None = None,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    limit = top_k or settings.chat_search_top_k
    limit = max(1, min(limit, 20))
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    from bot.chat_store import get_chat_store

    store = get_chat_store()
    selected: list[ChatSearchHit]
    with store._connect() as conn:
        chunks = load_chunks_for_search(
            conn,
            user_id,
            session_id=session_id,
            date=date,
        )
        if not chunks:
            from bot.chat_index.sync import rebuild_user_index

            rebuild_user_index(store, user_id)
            chunks = load_chunks_for_search(
                conn,
                user_id,
                session_id=session_id,
                date=date,
            )
        if not chunks:
            return []

        candidate_count = max(limit, settings.chat_search_keyword_candidates)
        lexical = _rank_lexical(cleaned_query, chunks)
        provider = await _get_embedding_provider()
        if provider is not None:
            scan_limit = max(candidate_count, settings.chat_search_vector_scan_limit)
            vector_scan = chunks[:scan_limit]
            vector = await _rank_vector(conn, provider, cleaned_query, vector_scan)
            ranked = _rrf_fuse(
                lexical,
                vector,
                candidate_count=candidate_count,
            )
        else:
            ranked = lexical

        selected = _diversify(
            ranked,
            limit=limit,
            max_per_session=max(1, settings.chat_search_max_per_session),
        )

    return [
        _chunk_payload(
            item.chunk,
            item.score,
            turn_context=_turn_context(store, item.chunk),
        )
        for item in selected
    ]
