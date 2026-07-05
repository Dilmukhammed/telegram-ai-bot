import unittest
from unittest.mock import AsyncMock, MagicMock

from agent.worker_content_summarize import (
    _parse_summary_array,
    _should_summarize_assistant_content,
    summarize_worker_assistant_content,
)


class WorkerContentSummarizeTests(unittest.IsolatedAsyncioTestCase):
    def test_should_summarize_assistant_with_tool_calls(self) -> None:
        message = {
            "role": "assistant",
            "content": "Let's check yandex.auth.status before fetching likes.",
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "use_tool", "arguments": "{}"}}],
        }
        self.assertTrue(_should_summarize_assistant_content(message))

    def test_skip_short_or_final_messages(self) -> None:
        self.assertFalse(
            _should_summarize_assistant_content(
                {"role": "assistant", "content": "ok", "tool_calls": [{}]}
            )
        )
        self.assertFalse(
            _should_summarize_assistant_content(
                {"role": "assistant", "content": "Final answer for the user."}
            )
        )

    def test_parse_summary_array(self) -> None:
        parsed = _parse_summary_array('["a", "b"]', expected_len=2)
        self.assertEqual(parsed, ["a", "b"])
        self.assertIsNone(_parse_summary_array('["a"]', expected_len=2))

    async def test_apply_batch_summaries(self) -> None:
        worker = [
            {
                "role": "assistant",
                "content": "Let's start the Yandex OAuth flow for this user now.",
                "tool_calls": [{"id": "1", "type": "function", "function": {"name": "use_tool", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "1", "content": "{}"},
            {"role": "assistant", "content": "Final reply"},
        ]
        llm = MagicMock()
        llm.chat_without_reasoning = AsyncMock(return_value='["Запустил OAuth Yandex"]')

        result = await summarize_worker_assistant_content(worker, llm=llm, settings=MagicMock())

        self.assertEqual(result[0]["content"], "Запустил OAuth Yandex")
        self.assertEqual(result[2]["content"], "Final reply")
        llm.chat_without_reasoning.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
