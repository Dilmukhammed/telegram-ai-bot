import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from tools.tool_results.summarize import _summary_acceptable, summarize_tool_result


class SummaryAcceptableTests(unittest.TestCase):
    def test_rejects_short_summary(self) -> None:
        self.assertFalse(_summary_acceptable("Too short.", min_chars=80))

    def test_accepts_long_enough_summary(self) -> None:
        text = "The search returned multiple GraphRAG repositories with Python implementations and architecture notes."
        self.assertTrue(_summary_acceptable(text, min_chars=80))

    def test_rejects_truncated_ellipsis(self) -> None:
        text = "A" * 79 + "…"
        self.assertFalse(_summary_acceptable(text, min_chars=80))


class SummarizeToolResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_when_summary_too_short(self) -> None:
        llm = MagicMock()
        llm.chat_without_reasoning = AsyncMock(
            side_effect=[
                "The search returned results from the NirDiamant/R",
                (
                    "The search returned multiple GraphRAG repositories including "
                    "NirDiamant/RAG_Techniques with Python architecture examples."
                ),
            ]
        )
        store = MagicMock()
        settings = SimpleNamespace(
            tool_result_summarize_max_retries=3,
            tool_result_summarize_min_chars=80,
            tool_result_summarize_max_input_chars=12_000,
        )

        await summarize_tool_result(
            llm,
            settings,
            store,
            ref="tr_test",
            tool_name="exa.web_search",
            args_json='{"query":"graphrag"}',
            payload_json='{"ok": true, "hits": []}',
        )

        self.assertEqual(llm.chat_without_reasoning.await_count, 2)
        store.update_summary.assert_called_once()
        kwargs = store.update_summary.call_args.kwargs
        self.assertEqual(kwargs["summarize_status"], "ok")
        self.assertGreaterEqual(len(kwargs["summary"]), 80)

    async def test_marks_failed_after_short_summaries_exhausted(self) -> None:
        llm = MagicMock()
        llm.chat_without_reasoning = AsyncMock(return_value="tiny")
        store = MagicMock()
        settings = SimpleNamespace(
            tool_result_summarize_max_retries=2,
            tool_result_summarize_min_chars=80,
            tool_result_summarize_max_input_chars=12_000,
        )

        await summarize_tool_result(
            llm,
            settings,
            store,
            ref="tr_test",
            tool_name="exa.web_search",
            args_json=None,
            payload_json='{"ok": true}',
        )

        self.assertEqual(llm.chat_without_reasoning.await_count, 2)
        store.update_summary.assert_called_once_with(
            "tr_test",
            summary=None,
            summarize_status="failed",
            summarize_attempts=2,
        )


if __name__ == "__main__":
    unittest.main()
