from __future__ import annotations

import json
import logging
import time
from typing import Any, Sequence

from memory.retrieval.corpus import BeliefHeadDoc
from memory.retrieval.schemas import (
    CHANNEL_CHAT,
    CHANNEL_DOCUMENT,
    CHANNEL_GOAL,
    CHANNEL_TOOL,
    CHANNEL_VECTOR,
    ChannelResult,
    RetrievalHit,
)
from tools.keyword_index import cosine_similarity

logger = logging.getLogger(__name__)

_GOAL_KINDS = frozenset({"goal", "task"})
_GOAL_SCHEMAS = frozenset(
    {
        "goal",
        "task",
        "created_task",
        "has_goal",
        "has_task",
        "todo",
        "deadline",
    }
)


async def search_vector(
    *,
    query: str,
    beliefs: Sequence[BeliefHeadDoc],
    limit: int = 40,
) -> ChannelResult:
    started = time.perf_counter()
    if not beliefs:
        return ChannelResult(
            channel=CHANNEL_VECTOR,
            hits=(),
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
    try:
        from tools.embeddings import (
            create_embedding_provider,
            get_embedding_provider_mode,
            get_embedding_settings,
        )

        mode = get_embedding_provider_mode()
        if mode == "keyword":
            return ChannelResult(
                channel=CHANNEL_VECTOR,
                hits=(),
                latency_ms=(time.perf_counter() - started) * 1000.0,
                skipped=True,
                skip_reason="embedding_provider_keyword",
            )
        base_url, api_key, api_model, local_model = get_embedding_settings()
        if not api_key and mode == "api":
            return ChannelResult(
                channel=CHANNEL_VECTOR,
                hits=(),
                latency_ms=(time.perf_counter() - started) * 1000.0,
                skipped=True,
                skip_reason="embedding_api_key_missing",
            )
        provider = await create_embedding_provider(
            base_url=base_url,
            api_key=api_key,
            api_model=api_model,
            local_model=local_model,
            provider_mode=mode,
        )
        if provider is None:
            return ChannelResult(
                channel=CHANNEL_VECTOR,
                hits=(),
                latency_ms=(time.perf_counter() - started) * 1000.0,
                skipped=True,
                skip_reason="embedding_provider_unavailable",
            )
        query_vec = await provider.embed(query)
        texts = [doc.search_text[:2000] for doc in beliefs]
        # Batch if provider supports; fall back to sequential.
        doc_vecs: list[list[float]] = []
        embed_many = getattr(provider, "embed_many", None)
        if callable(embed_many):
            doc_vecs = await embed_many(texts)
        else:
            for text in texts:
                doc_vecs.append(await provider.embed(text))
        scored: list[tuple[float, BeliefHeadDoc]] = []
        for doc, vec in zip(beliefs, doc_vecs):
            if not vec:
                continue
            score = float(cosine_similarity(query_vec, vec))
            if score > 0.15:
                scored.append((score, doc))
        scored.sort(key=lambda item: (-item[0], item[1].belief_id))
        hits = [
            RetrievalHit(
                channel=CHANNEL_VECTOR,
                item_id=doc.belief_id,
                item_kind="belief",
                score=score,
                label=doc.schema_name,
                statement=doc.statement,
                belief_id=doc.belief_id,
                status=doc.belief_status,
                utility_class=doc.utility_class,
                polarity=doc.polarity,
                support_pointers=doc.support_pointers,
            )
            for score, doc in scored[:limit]
        ]
        return ChannelResult(
            channel=CHANNEL_VECTOR,
            hits=tuple(hits),
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
    except Exception as exc:  # noqa: BLE001 — shadow channel must not fail preflight
        logger.warning("memory_shadow_vector_channel_failed error=%s", exc)
        return ChannelResult(
            channel=CHANNEL_VECTOR,
            hits=(),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            error=str(exc),
        )


def search_goals(
    *,
    beliefs: Sequence[BeliefHeadDoc],
    limit: int = 40,
) -> ChannelResult:
    started = time.perf_counter()
    hits: list[RetrievalHit] = []
    for doc in beliefs:
        if doc.belief_status not in {"active", "uncertain"}:
            continue
        kind_hit = any(kind in _GOAL_KINDS for kind in doc.candidate_kinds)
        schema_hit = doc.schema_name.casefold() in _GOAL_SCHEMAS or any(
            token in doc.schema_name.casefold() for token in ("goal", "task", "todo")
        )
        if not (kind_hit or schema_hit):
            continue
        hits.append(
            RetrievalHit(
                channel=CHANNEL_GOAL,
                item_id=doc.belief_id,
                item_kind="belief",
                score=1.0 if doc.belief_status == "active" else 0.6,
                label=doc.schema_name,
                statement=doc.statement,
                belief_id=doc.belief_id,
                status=doc.belief_status,
                utility_class=doc.utility_class,
                polarity=doc.polarity,
                support_pointers=doc.support_pointers,
            )
        )
    hits.sort(key=lambda item: (-item.score, item.item_id))
    return ChannelResult(
        channel=CHANNEL_GOAL,
        hits=tuple(hits[:limit]),
        latency_ms=(time.perf_counter() - started) * 1000.0,
    )


async def search_chat(*, user_id: int, query: str, top_k: int = 8) -> ChannelResult:
    started = time.perf_counter()
    try:
        from bot.chat_index.search import search_chat_chunks

        raw = await search_chat_chunks(user_id, query, top_k=top_k)
        hits = [
            RetrievalHit(
                channel=CHANNEL_CHAT,
                item_id=f"chat:{item.get('session_id')}:{item.get('turn_number')}:{item.get('seq_start')}",
                item_kind="chat_chunk",
                score=float(item.get("score") or 0.0),
                label=str(item.get("title") or item.get("session_id") or "chat"),
                statement=str(item.get("text") or "")[:500],
                metadata={
                    "session_id": item.get("session_id"),
                    "tool_ref": item.get("tool_ref"),
                    "source_type": item.get("source_type"),
                },
            )
            for item in raw
        ]
        return ChannelResult(
            channel=CHANNEL_CHAT,
            hits=tuple(hits),
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory_shadow_chat_channel_failed error=%s", exc)
        return ChannelResult(
            channel=CHANNEL_CHAT,
            hits=(),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            error=str(exc),
        )


async def search_tools(
    *,
    user_id: int,
    query: str,
    chat_hits: Sequence[RetrievalHit] = (),
) -> ChannelResult:
    started = time.perf_counter()
    try:
        from tools.tool_results.store import get_tool_result_store

        store = get_tool_result_store()
        refs: list[str] = []
        for hit in chat_hits:
            ref = hit.metadata.get("tool_ref")
            if ref:
                refs.append(str(ref))
        # Also scan recent summarized tool results for lexical overlap.
        try:
            summarized = store.list_summarized(user_id)
        except Exception:  # noqa: BLE001
            summarized = []
        q = query.casefold()
        for record in summarized[:50]:
            blob = " ".join(
                [
                    str(getattr(record, "tool_name", "") or ""),
                    str(getattr(record, "summary", "") or ""),
                    str(getattr(record, "ref", "") or ""),
                ]
            ).casefold()
            if q and any(tok in blob for tok in q.split() if len(tok) > 2):
                refs.append(str(getattr(record, "ref", "") or getattr(record, "id", "")))

        hits: list[RetrievalHit] = []
        seen: set[str] = set()
        for ref in refs:
            if not ref or ref in seen:
                continue
            seen.add(ref)
            record = store.get(ref, user_id=user_id)
            if record is None:
                continue
            payload_preview = ""
            try:
                payload = json.loads(record.payload_json)
                payload_preview = json.dumps(payload, ensure_ascii=False)[:400]
            except Exception:  # noqa: BLE001
                payload_preview = (record.payload_json or "")[:400]
            hits.append(
                RetrievalHit(
                    channel=CHANNEL_TOOL,
                    item_id=f"tool:{ref}",
                    item_kind="tool_result",
                    score=0.8,
                    label=str(getattr(record, "tool_name", None) or ref),
                    statement=payload_preview,
                    metadata={"tool_ref": ref},
                )
            )
        return ChannelResult(
            channel=CHANNEL_TOOL,
            hits=tuple(hits[:20]),
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory_shadow_tool_channel_failed error=%s", exc)
        return ChannelResult(
            channel=CHANNEL_TOOL,
            hits=(),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            error=str(exc),
        )


def search_documents(
    *,
    user_id: int,
    query: str,
    db,
    limit: int = 20,
) -> ChannelResult:
    from memory.retrieval.document_search import search_documents as _search

    return _search(user_id=user_id, query=query, db=db, limit=limit)
