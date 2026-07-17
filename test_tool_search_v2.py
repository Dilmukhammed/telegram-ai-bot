import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.query_normalization import (
    infer_query_tags,
    normalize_tool_query,
)
from tools.search_feedback import SearchFeedbackStore
from tools.bootstrap import create_tool_runtime
from tools.context import RunContext
from tools.embeddings import EmbeddingProvider
from tools.index import HybridToolIndex
from tools.registry import ToolRegistry
from tools.schema import ToolSpec


async def _noop_handler(_: dict) -> dict:
    return {}


class _AdversarialEmbeddingProvider(EmbeddingProvider):
    async def embed(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            if "exact.read" in text:
                vectors.append([0.0, 1.0])
            elif "semantic.noise" in text:
                vectors.append([1.0, 0.0])
            else:
                # Query vector intentionally favors the wrong semantic tool.
                vectors.append([1.0, 0.0])
        return vectors


class QueryNormalizationTests(unittest.TestCase):
    def test_russian_yandex_playlists(self) -> None:
        normalized = normalize_tool_query("покажи мои плейлисты в Яндекс Музыке")
        self.assertIn("list", normalized)
        self.assertIn("playlists", normalized)
        self.assertEqual(infer_query_tags(normalized), ("yandex", "music"))

    def test_russian_workspace_glob(self) -> None:
        normalized = normalize_tool_query("найди файлы по маске в рабочей папке")
        self.assertIn("glob", normalized)
        self.assertEqual(infer_query_tags(normalized), ("workspace", "filesystem"))

    def test_terse_music_query_infers_yandex_tags(self) -> None:
        self.assertEqual(infer_query_tags("music playlist"), ("yandex", "music"))

    def test_unlike_expands_to_remove_like(self) -> None:
        normalized = normalize_tool_query("music unlike track")
        self.assertIn("remove", normalized)
        self.assertIn("like", normalized)


class SearchFeedbackTests(unittest.TestCase):
    def test_successful_selection_is_promoted_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict("os.environ", {"TOOL_SEARCH_FEEDBACK_ENABLED": "1"}):
                store = SearchFeedbackStore(
                    str(root / "feedback.json"),
                    str(root / "eval.jsonl"),
                )
            tools = [{"name": "wrong"}, {"name": "right"}]
            store.record(
                query="list user playlists",
                tags=["yandex", "music"],
                selected_tool="right",
                ok=True,
                candidates=["wrong", "right"],
            )
            ranked = store.rerank(
                "list user playlists",
                ["yandex", "music"],
                tools,
            )
            self.assertEqual(ranked[0]["name"], "right")
            self.assertTrue((root / "feedback.json").exists())
            self.assertTrue((root / "eval.jsonl").exists())


class HybridFusionTests(unittest.IsolatedAsyncioTestCase):
    async def test_precise_keyword_match_survives_noisy_embedding_rank(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="exact.read",
                description="read spreadsheet cell values",
                parameters={"type": "object", "properties": {}},
                handler=_noop_handler,
                tags=("google", "sheets"),
            )
        )
        registry.register(
            ToolSpec(
                name="semantic.noise",
                description="unrelated operation",
                parameters={"type": "object", "properties": {}},
                handler=_noop_handler,
                tags=("google", "sheets"),
            )
        )
        index = HybridToolIndex(registry, _AdversarialEmbeddingProvider())
        results = await index.search("read spreadsheet cell values", top_k=2)
        self.assertEqual(results[0].name, "exact.read")


class BotToolSearchIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_production_meta_tool_routes_terse_music_query(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "DOTENV_OVERRIDE": "0",
                "TOOL_EMBEDDING_PROVIDER": "keyword",
                "TOOL_SEARCH_FEEDBACK_ENABLED": "0",
            },
        ):
            runtime = await create_tool_runtime()
        raw = await runtime.dispatch_meta_tool(
            "search_tools",
            {"mode": "rank", "query": "music playlist", "top_k": 5},
            ctx=RunContext(user_id=991, turn=1, meta_tool="search_tools"),
        )
        payload = json.loads(raw)
        self.assertEqual(payload["tools"][0]["name"], "yandex.music.users_playlists_list")
        self.assertEqual(payload["inferred_tags"], ["yandex", "music"])

    async def test_production_meta_tool_respects_explicit_music_tags(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "DOTENV_OVERRIDE": "0",
                "TOOL_EMBEDDING_PROVIDER": "keyword",
                "TOOL_SEARCH_FEEDBACK_ENABLED": "0",
            },
        ):
            runtime = await create_tool_runtime()
        raw = await runtime.dispatch_meta_tool(
            "search_tools",
            {
                "mode": "rank",
                "query": "like track",
                "tags": ["yandex", "music"],
                "top_k": 5,
            },
            ctx=RunContext(user_id=992, turn=1, meta_tool="search_tools"),
        )
        payload = json.loads(raw)
        self.assertEqual(payload["tools"][0]["name"], "yandex.music.users_likes_tracks_add")


if __name__ == "__main__":
    unittest.main()
