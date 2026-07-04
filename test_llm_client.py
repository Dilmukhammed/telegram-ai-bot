import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config import REASONING_EFFORT_LEVELS, get_settings
from llm import LLMClient, LLMRequestTimeoutError


class ReasoningEffortConfigTests(unittest.TestCase):
    def test_default_reasoning_effort_is_high(self) -> None:
        with patch.dict("os.environ", {"REASONING_EFFORT": "high"}, clear=False):
            settings = get_settings()
        self.assertEqual(settings.reasoning_effort, "high")

    def test_empty_reasoning_effort_disables_param(self) -> None:
        with patch.dict("os.environ", {"REASONING_EFFORT": ""}, clear=False):
            settings = get_settings()
        self.assertIsNone(settings.reasoning_effort)

    def test_invalid_reasoning_effort_raises(self) -> None:
        with patch.dict("os.environ", {"REASONING_EFFORT": "turbo"}, clear=False):
            with self.assertRaises(RuntimeError):
                get_settings()

    def test_allowed_levels(self) -> None:
        self.assertIn("high", REASONING_EFFORT_LEVELS)
        self.assertIn("none", REASONING_EFFORT_LEVELS)


class LLMClientReasoningTests(unittest.TestCase):
    def test_completion_kwargs_include_reasoning_effort(self) -> None:
        with patch.dict("os.environ", {"REASONING_EFFORT": "high"}, clear=False):
            settings = get_settings()
        client = LLMClient(settings)
        kwargs = client._completion_kwargs(messages=[], stream=True)
        self.assertEqual(kwargs["reasoning_effort"], "high")
        self.assertEqual(kwargs["model"], settings.openai_model)

    def test_completion_kwargs_omit_when_disabled(self) -> None:
        with patch.dict("os.environ", {"REASONING_EFFORT": ""}, clear=False):
            settings = get_settings()
        client = LLMClient(settings)
        kwargs = client._completion_kwargs(messages=[])
        self.assertNotIn("reasoning_effort", kwargs)


class LLMClientTimeoutRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_escalating_retry_succeeds_on_second_attempt(self) -> None:
        with patch.dict(
            "os.environ",
            {"LLM_REQUEST_TIMEOUTS": "0.05,0.2"},
            clear=False,
        ):
            settings = get_settings()
        client = LLMClient(settings)
        calls = {"count": 0}

        async def slow_call(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                await asyncio.sleep(0.15)
            return MagicMock()

        client._client.chat.completions.create = AsyncMock(side_effect=slow_call)
        retries: list[tuple[int, float]] = []

        async def on_retry(attempt: int, next_timeout: float) -> None:
            retries.append((attempt, next_timeout))

        result = await client.chat_with_tools([], [], on_retry=on_retry)
        self.assertIsNotNone(result)
        self.assertEqual(calls["count"], 2)
        self.assertEqual(retries, [(1, 0.2)])

    async def test_raises_after_all_escalating_attempts(self) -> None:
        with patch.dict(
            "os.environ",
            {"LLM_REQUEST_TIMEOUTS": "0.05,0.05,0.05"},
            clear=False,
        ):
            settings = get_settings()
        client = LLMClient(settings)

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(0.2)
            return MagicMock()

        client._client.chat.completions.create = AsyncMock(side_effect=slow_call)

        with self.assertRaises(LLMRequestTimeoutError):
            await client.chat_with_tools([], [])

    async def test_each_new_call_starts_from_first_timeout(self) -> None:
        with patch.dict(
            "os.environ",
            {"LLM_REQUEST_TIMEOUTS": "0.05,0.2"},
            clear=False,
        ):
            settings = get_settings()
        client = LLMClient(settings)
        calls = {"count": 0}

        async def fast_call(*args, **kwargs):
            calls["count"] += 1
            return MagicMock()

        client._client.chat.completions.create = AsyncMock(side_effect=fast_call)

        await client.chat_with_tools([], [])
        await client.chat_with_tools([], [])
        self.assertEqual(calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
