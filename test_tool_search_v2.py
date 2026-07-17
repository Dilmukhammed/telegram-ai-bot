import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.query_normalization import (
    infer_query_tags,
    normalize_tool_query,
)
from tools.search_feedback import SearchFeedbackStore


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


if __name__ == "__main__":
    unittest.main()
