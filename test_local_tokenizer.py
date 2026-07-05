import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from local_tokenizer import count_prompt_tokens_local, count_text
from tools.tool_results.archive import archived_content_json
from tools.tool_results.stats import (
    ArchiveCompressionStats,
    format_compression_percent,
    load_history_archive_compression,
)
from tools.tool_results.store import StoredToolResult, ToolResultStore, reset_tool_result_store


class LocalTokenizerTests(unittest.TestCase):
    def test_count_text_nonempty(self) -> None:
        self.assertGreater(count_text("hello world"), 0)

    def test_count_prompt_includes_tools(self) -> None:
        messages = [{"role": "user", "content": "hi"}]
        tools = [{"type": "function", "function": {"name": "search_tools", "parameters": {}}}]
        self.assertGreater(
            count_prompt_tokens_local(messages, tools=tools),
            count_prompt_tokens_local(messages),
        )


class ArchiveCompressionStatsTests(unittest.TestCase):
    def test_saved_percent(self) -> None:
        stats = ArchiveCompressionStats(
            sample_count=2,
            stub_tokens=200,
            full_tokens=2000,
            stub_chars=800,
            full_chars=8000,
        )
        self.assertAlmostEqual(stats.token_kept_percent, 10.0)
        self.assertAlmostEqual(stats.token_saved_percent, 90.0)
        self.assertEqual(format_compression_percent(stats.token_saved_percent), "90%")

    def test_history_archive_compression(self) -> None:
        store = ToolResultStore(":memory:")
        reset_tool_result_store(store)
        ref = store.insert(
            user_id=7,
            run_id="r1",
            tool_name="exa.web_search",
            turn=0,
            args_json="{}",
            payload_json='{"tool_name":"exa.web_search","ok":true,"result":{"hits":[' + ",".join(['{"id":%d}' % i for i in range(200)]) + "]}}",
            ok=True,
            cached=False,
        )
        store.update_summary(ref, summary="Three hits about GraphRAG.", summarize_status="ok", summarize_attempts=1)
        record = store.get(ref, user_id=7)
        assert record is not None
        stub = archived_content_json(record)
        history = [{"role": "tool", "content": stub}]

        with patch("tools.tool_results.stats.count_text", side_effect=lambda text: len(text)):
            stats = load_history_archive_compression(history, user_id=7)
        assert stats is not None
        self.assertEqual(stats.archived_in_history, 1)
        self.assertLess(stats.stub_tokens, stats.full_tokens)


if __name__ == "__main__":
    unittest.main()
