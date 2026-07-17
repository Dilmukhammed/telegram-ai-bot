import logging

from tools.embeddings import (
    EmbeddingProvider,
    create_embedding_provider,
    get_embedding_provider_mode,
    get_embedding_settings,
)
from tools.keyword_index import KeywordToolIndex, cosine_similarity, expand_query_terms
from tools.query_normalization import infer_query_tags, normalize_tool_query
from tools.registry import ToolRegistry
from tools.schema import ToolSpec
from tools.tags import filter_tools_by_tags

logger = logging.getLogger(__name__)


class HybridToolIndex:
    # Reciprocal-rank fusion is deliberately lexical-first. Tool names,
    # aliases and action rules are high-precision signals; embeddings provide
    # recall and reorder the tail, but must not displace a strong exact match.
    RRF_K = 0
    EMBEDDING_RRF_WEIGHT = 0.20
    KEYWORD_RRF_WEIGHT = 0.80
    CANDIDATE_POOL_MIN = 20

    def __init__(
        self,
        registry: ToolRegistry,
        embedding_provider: EmbeddingProvider | None,
    ) -> None:
        self._registry = registry
        self._embeddings = embedding_provider
        self._keyword = KeywordToolIndex()
        self._vectors: dict[str, list[float]] = {}
        self._ready = False

    async def _ensure_ready(self) -> None:
        if self._ready:
            return

        if self._embeddings is None:
            self._ready = True
            return

        tools = self._registry.all()
        texts = [tool.index_text() for tool in tools]
        vectors = await self._embeddings.embed_many(texts)
        self._vectors = {tool.name: vector for tool, vector in zip(tools, vectors)}
        self._ready = True
        logger.info("Indexed %s tools for embedding search", len(self._vectors))

    def invalidate(self) -> None:
        self._vectors.clear()
        self._ready = False

    async def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        tags: list[str] | None = None,
    ) -> list[ToolSpec]:
        await self._ensure_ready()

        effective_tags = tags
        if not effective_tags:
            inferred = infer_query_tags(query)
            if inferred:
                effective_tags = list(inferred)

        candidates = filter_tools_by_tags(self._registry.all(), effective_tags)
        if not candidates:
            return []

        if not query.strip():
            return candidates[:top_k]

        normalized_query = normalize_tool_query(query)
        queries = expand_query_terms(normalized_query)
        if not self._vectors or self._embeddings is None:
            return self._keyword.search_multi(queries, candidates, top_k=top_k)

        query_vectors = await self._embeddings.embed_many(queries)
        embedding_scored: list[tuple[float, ToolSpec]] = []

        for tool in candidates:
            vector = self._vectors.get(tool.name)
            if vector is None:
                continue

            term_scores: list[float] = []
            for query_vector in query_vectors:
                embedding_score = cosine_similarity(query_vector, vector)
                term_scores.append(embedding_score)

            embedding_scored.append((max(term_scores), tool))

        embedding_scored.sort(key=lambda item: (-item[0], item[1].name))
        keyword_scored = self._keyword.rank_multi(queries, candidates)

        pool_size = min(
            len(candidates),
            max(self.CANDIDATE_POOL_MIN, top_k * 4),
        )
        embedding_rank = {
            tool.name: rank
            for rank, (_, tool) in enumerate(embedding_scored[:pool_size], start=1)
        }
        keyword_rank = {
            tool.name: rank
            for rank, (score, tool) in enumerate(keyword_scored[:pool_size], start=1)
            if score > 0
        }
        by_name = {tool.name: tool for tool in candidates}
        fused: list[tuple[float, ToolSpec]] = []
        for name in embedding_rank.keys() | keyword_rank.keys():
            score = 0.0
            if name in embedding_rank:
                score += self.EMBEDDING_RRF_WEIGHT / (self.RRF_K + embedding_rank[name])
            if name in keyword_rank:
                score += self.KEYWORD_RRF_WEIGHT / (self.RRF_K + keyword_rank[name])
            fused.append((score, by_name[name]))

        fused.sort(key=lambda item: (-item[0], item[1].name))
        if fused:
            return [tool for _, tool in fused[:top_k]]

        return self._keyword.search_multi(queries, candidates, top_k=top_k)


async def create_tool_index(registry: ToolRegistry) -> HybridToolIndex:
    base_url, api_key, api_model, local_model = get_embedding_settings()
    provider_mode = get_embedding_provider_mode()

    provider = None
    if provider_mode != "keyword" and api_key:
        provider = await create_embedding_provider(
            base_url=base_url,
            api_key=api_key,
            api_model=api_model,
            local_model=local_model,
            provider_mode=provider_mode,
        )
    elif provider_mode != "keyword":
        logger.warning("OPENAI_API_KEY missing; falling back to keyword tool search")

    return HybridToolIndex(registry, provider)
