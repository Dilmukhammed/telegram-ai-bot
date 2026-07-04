import asyncio
import logging
from abc import ABC, abstractmethod

from openai import AsyncOpenAI

from config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]


class ApiEmbeddingProvider(EmbeddingProvider):
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(model=self._model, input=text)
        return list(response.data[0].embedding)

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(model=self._model, input=texts)
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]


class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    async def embed(self, text: str) -> list[float]:
        vectors = await asyncio.to_thread(lambda: list(self._get_model().embed([text])))
        return vectors[0].tolist()

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = await asyncio.to_thread(lambda: list(self._get_model().embed(texts)))
        return [vector.tolist() for vector in vectors]


async def create_embedding_provider(
    *,
    base_url: str,
    api_key: str,
    api_model: str,
    local_model: str,
    provider_mode: str,
) -> EmbeddingProvider | None:
    mode = provider_mode.strip().lower()

    if mode == "keyword":
        return None

    if mode in {"api", "auto", "hybrid"}:
        client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        api_provider = ApiEmbeddingProvider(client, api_model)
        try:
            await api_provider.embed("tool index probe")
            logger.info("Tool embeddings: using API model %s", api_model)
            return api_provider
        except Exception as exc:
            logger.warning("API embeddings unavailable via %s (%s)", base_url, exc)
            if mode == "api":
                raise

    if mode in {"local", "auto", "hybrid"}:
        local_provider = LocalEmbeddingProvider(local_model)
        try:
            await local_provider.embed("tool index probe")
            logger.info("Tool embeddings: using local model %s", local_model)
            return local_provider
        except Exception as exc:
            logger.warning("Local embeddings unavailable (%s)", exc)
            if mode == "local":
                raise

    return None


def get_embedding_settings() -> tuple[str, str, str, str]:
    settings = get_settings()
    return (
        settings.embedding_base_url,
        settings.embedding_api_key,
        settings.openai_embedding_model,
        settings.local_embedding_model,
    )


def get_embedding_provider_mode() -> str:
    return get_settings().tool_embedding_provider
