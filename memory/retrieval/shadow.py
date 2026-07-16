from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from memory.db import utc_now_iso
from memory.retrieval.channels import (
    search_chat,
    search_documents,
    search_goals,
    search_tools,
    search_vector,
)
from memory.retrieval.context_pack import build_context_pack
from memory.retrieval.corpus import load_belief_heads, load_entities
from memory.retrieval.summary_pack import enrich_context_pack, load_summary_shadow_pack
from memory.retrieval.entity_search import search_entities, search_lexical
from memory.retrieval.fusion import rrf_fuse
from memory.retrieval.graph_search import search_graph
from memory.retrieval.planner import plan_query
from memory.retrieval.schemas import (
    CHANNEL_CHAT,
    CHANNEL_DOCUMENT,
    CHANNEL_ENTITY,
    CHANNEL_GOAL,
    CHANNEL_GRAPH,
    CHANNEL_LEXICAL,
    CHANNEL_TEMPORAL,
    CHANNEL_TOOL,
    CHANNEL_VECTOR,
    ChannelResult,
    MemoryContextPack,
    QueryPlan,
    ShadowRetrievalResult,
)
from memory.retrieval.store import make_shadow_run_id, persist_shadow_run
from memory.retrieval.temporal import search_temporal

if TYPE_CHECKING:
    from memory.service import MemoryService

logger = logging.getLogger(__name__)

_CHANNEL_WEIGHTS = {
    CHANNEL_ENTITY: 1.3,
    CHANNEL_LEXICAL: 1.1,
    CHANNEL_VECTOR: 1.0,
    CHANNEL_GRAPH: 1.2,
    CHANNEL_TEMPORAL: 1.0,
    CHANNEL_GOAL: 1.15,
    CHANNEL_CHAT: 0.7,
    CHANNEL_TOOL: 0.9,
    CHANNEL_DOCUMENT: 0.5,
}


async def run_shadow_preflight(
    *,
    user_id: int,
    query: str,
    query_time: datetime | None = None,
    memory_service: "MemoryService | None" = None,
    persist: bool = True,
) -> ShadowRetrievalResult:
    """Full PR8 shadow retrieval. Never mutates agent prompts."""
    if query_time is None:
        query_time = datetime.now(timezone.utc)
    if query_time.tzinfo is None:
        query_time = query_time.replace(tzinfo=timezone.utc)

    service = memory_service
    if service is None:
        from memory.service import peek_memory_service

        service = peek_memory_service()
    if service is None:
        raise RuntimeError("memory service is not available for shadow retrieval")

    cfg = service.config
    query_time_iso = query_time.isoformat()
    run_id = make_shadow_run_id(
        user_id=user_id, query=query, query_time=query_time_iso
    )
    summary_pack_json = None

    with service.db.connection() as conn:
        beliefs = load_belief_heads(conn, user_id=user_id)
        entities = load_entities(conn, user_id=user_id)

    graph_revision = 0
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    try:
        graph_revision = service.graph.current_revision(user_id)
        nodes = service.graph.list_active_nodes(user_id=user_id)
        edges = service.graph.list_active_edges(user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory_shadow_graph_read_failed user_id=%s error=%s", user_id, exc)

    plan = plan_query(
        query,
        known_entity_labels=[item.canonical_label for item in entities],
    )

    empty_pack = MemoryContextPack(
        graph_revision=graph_revision,
        query_time=query_time_iso,
        entities=(),
        beliefs=(),
        uncertainties=(),
        contradictions=(),
        timelines=(),
        chat_hits=(),
        tool_hits=(),
        document_hits=(),
        exact_evidence_available=False,
        token_estimate=0,
    )
    if not plan.memory_needed and CHANNEL_CHAT not in plan.channels:
        result = ShadowRetrievalResult(
            run_id=run_id,
            user_id=user_id,
            plan=plan,
            pack=empty_pack,
            channels=(),
            latency_ms={},
            prompt_mutated=False,
        )
        if persist:
            persist_shadow_run(service.db, result=result, query=query)
        return result

    async def _run_channel(name: str) -> ChannelResult:
        if name == CHANNEL_ENTITY:
            return search_entities(
                query=query, entities=entities, plan_entities=plan.entities
            )
        if name == CHANNEL_LEXICAL:
            return search_lexical(query=query, beliefs=beliefs)
        if name == CHANNEL_VECTOR:
            return await search_vector(query=query, beliefs=beliefs)
        if name == CHANNEL_GRAPH:
            return search_graph(
                query=query,
                plan_entities=plan.entities,
                entities=entities,
                beliefs=beliefs,
                nodes=nodes,
                edges=edges,
                max_hops=cfg.shadow_retrieval_max_hops,
            )
        if name == CHANNEL_TEMPORAL:
            return search_temporal(
                query_time=query_time, beliefs=beliefs, edges=edges
            )
        if name == CHANNEL_GOAL:
            return search_goals(beliefs=beliefs)
        if name == CHANNEL_CHAT:
            return await search_chat(user_id=user_id, query=query)
        if name == CHANNEL_TOOL:
            # chat channel may run in parallel; tool channel will also mine chat below
            return await search_tools(user_id=user_id, query=query, chat_hits=())
        if name == CHANNEL_DOCUMENT:
            return search_documents(
                user_id=user_id, query=query, db=service.db, limit=20
            )
        return ChannelResult(
            channel=name,
            hits=(),
            latency_ms=0.0,
            skipped=True,
            skip_reason="unknown_channel",
        )

    timeout = float(cfg.shadow_retrieval_timeout_seconds)
    tasks = {
        name: asyncio.create_task(_run_channel(name), name=f"shadow:{name}")
        for name in plan.channels
    }
    channel_results: list[ChannelResult] = []
    try:
        done, pending = await asyncio.wait(
            tasks.values(), timeout=timeout, return_when=asyncio.ALL_COMPLETED
        )
        for task in pending:
            task.cancel()
            name = next(key for key, value in tasks.items() if value is task)
            channel_results.append(
                ChannelResult(
                    channel=name,
                    hits=(),
                    latency_ms=timeout * 1000.0,
                    skipped=True,
                    skip_reason="timeout",
                )
            )
        for task in done:
            name = next(key for key, value in tasks.items() if value is task)
            try:
                channel_results.append(task.result())
            except Exception as exc:  # noqa: BLE001
                channel_results.append(
                    ChannelResult(
                        channel=name,
                        hits=(),
                        latency_ms=0.0,
                        error=str(exc),
                    )
                )
    finally:
        for task in tasks.values():
            if not task.done():
                task.cancel()

    # Re-run tool channel with chat hits when both present (enrichment, still bounded).
    chat_result = next(
        (item for item in channel_results if item.channel == CHANNEL_CHAT), None
    )
    if CHANNEL_TOOL in plan.channels and chat_result is not None and chat_result.hits:
        tool_enriched = await search_tools(
            user_id=user_id, query=query, chat_hits=chat_result.hits
        )
        channel_results = [
            tool_enriched if item.channel == CHANNEL_TOOL else item
            for item in channel_results
        ]

    by_channel = {item.channel: item.hits for item in channel_results}
    fused = rrf_fuse(
        by_channel,
        limit=max(cfg.shadow_retrieval_max_beliefs * 3, 40),
        channel_weights=_CHANNEL_WEIGHTS,
    )
    pack = build_context_pack(
        graph_revision=graph_revision,
        query_time=query_time_iso,
        fused_hits=fused,
        beliefs=beliefs,
        entities=entities,
        token_budget=cfg.shadow_retrieval_token_budget,
        max_beliefs=cfg.shadow_retrieval_max_beliefs,
    )
    summary_pack_json = None
    if cfg.summaries_shadow_pack_enabled and cfg.summaries_enabled:
        summary_pack_json = load_summary_shadow_pack(
            service.summaries,
            user_id=user_id,
            entities=pack.entities,
        )
        pack = enrich_context_pack(pack, summary_pack=summary_pack_json)
    latency = {item.channel: item.latency_ms for item in channel_results}
    result = ShadowRetrievalResult(
        run_id=run_id,
        user_id=user_id,
        plan=plan,
        pack=pack,
        channels=tuple(channel_results),
        latency_ms=latency,
        prompt_mutated=False,
    )
    if persist:
        try:
            persist_shadow_run(
                service.db,
                result=result,
                query=query,
                summary_pack_json=summary_pack_json,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "memory_shadow_persist_failed run_id=%s error=%s", run_id, exc
            )
    logger.info(
        "memory_shadow_preflight_done user_id=%s run_id=%s needed=%s "
        "beliefs=%s entities=%s tokens=%s channels=%s revision=%s",
        user_id,
        run_id,
        int(plan.memory_needed),
        len(pack.beliefs),
        len(pack.entities),
        pack.token_estimate,
        {item.channel: len(item.hits) for item in channel_results},
        graph_revision,
    )
    return result


def schedule_shadow_preflight(
    *,
    user_id: int,
    query: str,
    query_time: datetime | None = None,
    memory_service: "MemoryService | None" = None,
) -> asyncio.Task[ShadowRetrievalResult] | None:
    """Fire-and-forget shadow preflight. Failures are logged, never raised to caller."""
    service = memory_service
    if service is None:
        from memory.service import peek_memory_service

        service = peek_memory_service()
    if service is None or not service.config.shadow_retrieval_enabled:
        return None

    async def _runner() -> ShadowRetrievalResult:
        try:
            return await run_shadow_preflight(
                user_id=user_id,
                query=query,
                query_time=query_time,
                memory_service=service,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "memory_shadow_preflight_failed user_id=%s error=%s", user_id, exc
            )
            empty_plan = QueryPlan(
                memory_needed=False,
                intent="error",
                entities=(),
                time_range=None,
                required_exactness="none",
                channels=(),
                subqueries=(),
                reason_codes=("preflight_error",),
            )
            return ShadowRetrievalResult(
                run_id=make_shadow_run_id(
                    user_id=user_id,
                    query=query,
                    query_time=utc_now_iso(),
                ),
                user_id=user_id,
                plan=empty_plan,
                pack=MemoryContextPack(
                    graph_revision=0,
                    query_time=utc_now_iso(),
                    entities=(),
                    beliefs=(),
                    uncertainties=(),
                    contradictions=(),
                    timelines=(),
                    chat_hits=(),
                    tool_hits=(),
                    document_hits=(),
                    exact_evidence_available=False,
                    token_estimate=0,
                ),
                channels=(),
                latency_ms={},
                prompt_mutated=False,
            )

    return asyncio.create_task(_runner(), name=f"memory-shadow:{user_id}")
