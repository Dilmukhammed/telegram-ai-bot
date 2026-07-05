import unittest
from unittest.mock import AsyncMock, MagicMock

from agent.worker_content_summarize import (
    _should_summarize_assistant_content,
    _truncate_fallback,
    summarize_worker_assistant_content,
)


def _mock_settings(**overrides) -> MagicMock:
    s = MagicMock()
    s.worker_content_summarize_max_chars = overrides.get(
        "worker_content_summarize_max_chars", 200
    )
    return s


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

    def test_truncate_fallback(self) -> None:
        text = "A" * 300
        result = _truncate_fallback(text)
        self.assertEqual(len(result), 200)
        self.assertTrue(result.endswith("…"))

        short = "Short text"
        self.assertEqual(_truncate_fallback(short), short)

    async def test_apply_single_summaries(self) -> None:
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
        llm.chat_without_reasoning = AsyncMock(return_value="Запустил OAuth Yandex")

        result = await summarize_worker_assistant_content(worker, llm=llm, settings=_mock_settings())

        self.assertEqual(result[0]["content"], "Запустил OAuth Yandex")
        self.assertEqual(result[2]["content"], "Final reply")
        llm.chat_without_reasoning.assert_awaited_once()

    async def test_fallback_truncate_on_llm_error(self) -> None:
        long_content = "A" * 500
        worker = [
            {
                "role": "assistant",
                "content": long_content,
                "tool_calls": [{"id": "1", "type": "function", "function": {"name": "use_tool", "arguments": "{}"}}],
            },
        ]
        llm = MagicMock()
        llm.chat_without_reasoning = AsyncMock(side_effect=RuntimeError("boom"))

        result = await summarize_worker_assistant_content(worker, llm=llm, settings=_mock_settings())

        self.assertEqual(len(result[0]["content"]), 200)
        self.assertTrue(result[0]["content"].endswith("…"))

    async def test_fallback_truncate_on_empty_summary(self) -> None:
        long_content = "A" * 500
        worker = [
            {
                "role": "assistant",
                "content": long_content,
                "tool_calls": [{"id": "1", "type": "function", "function": {"name": "use_tool", "arguments": "{}"}}],
            },
        ]
        llm = MagicMock()
        llm.chat_without_reasoning = AsyncMock(return_value="")

        result = await summarize_worker_assistant_content(worker, llm=llm, settings=_mock_settings())

        self.assertEqual(len(result[0]["content"]), 200)
        self.assertTrue(result[0]["content"].endswith("…"))

    async def test_multiple_summaries_concurrent(self) -> None:
        worker = [
            {
                "role": "assistant",
                "content": "Searching the web for Python 3.13 release notes now.",
                "tool_calls": [{"id": "1", "type": "function", "function": {"name": "use_tool", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "1", "content": "{}"},
            {
                "role": "assistant",
                "content": "Now I will create a calendar event for tomorrow at 18:00.",
                "tool_calls": [{"id": "2", "type": "function", "function": {"name": "use_tool", "arguments": "{}"}}],
            },
        ]
        llm = MagicMock()
        llm.chat_without_reasoning = AsyncMock(side_effect=["Ищу Python 3.13", "Создаю событие в календаре"])

        result = await summarize_worker_assistant_content(worker, llm=llm, settings=_mock_settings())

        self.assertEqual(result[0]["content"], "Ищу Python 3.13")
        self.assertEqual(result[2]["content"], "Создаю событие в календаре")
        self.assertEqual(llm.chat_without_reasoning.await_count, 2)


if __name__ == "__main__":
    unittest.main()
