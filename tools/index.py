import logging

from tools.embeddings import (
    EmbeddingProvider,
    create_embedding_provider,
    get_embedding_provider_mode,
    get_embedding_settings,
)
from tools.keyword_index import KeywordToolIndex, cosine_similarity, expand_query_terms
from tools.registry import ToolRegistry
from tools.schema import ToolSpec
from tools.tags import filter_tools_by_tags

logger = logging.getLogger(__name__)


class HybridToolIndex:
    EMBEDDING_WEIGHT = 0.75
    KEYWORD_WEIGHT = 0.25

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

        candidates = filter_tools_by_tags(self._registry.all(), tags)
        if not candidates:
            return []

        if not query.strip():
            return candidates[:top_k]

        queries = expand_query_terms(query)
        if not self._vectors or self._embeddings is None:
            return self._keyword.search_multi(queries, candidates, top_k=top_k)

        query_vectors = await self._embeddings.embed_many(queries)
        scored: list[tuple[float, ToolSpec]] = []

        for tool in candidates:
            vector = self._vectors.get(tool.name)
            if vector is None:
                continue

            term_scores: list[float] = []
            for term, query_vector in zip(queries, query_vectors):
                embedding_score = cosine_similarity(query_vector, vector)
                keyword_score = self._keyword.score(term, tool)
                term_scores.append(
                    self.EMBEDDING_WEIGHT * embedding_score
                    + self.KEYWORD_WEIGHT * keyword_score
                )

            scored.append((max(term_scores), tool))

        scored.sort(key=lambda item: item[0], reverse=True)
        if scored:
            return [tool for _, tool in scored[:top_k]]

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
