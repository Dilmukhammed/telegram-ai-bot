import asyncio
import os
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

    def test_summarize_profile_uses_separate_model_without_reasoning(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_MODEL": "accounts/fireworks/models/glm-5p2",
                "SUMMARIZE_MODEL": "accounts/fireworks/models/qwen3-8b",
                "REASONING_EFFORT": "high",
            },
            clear=False,
        ):
            settings = get_settings()
        agent = LLMClient(settings)
        summarize = LLMClient(settings, profile="summarize")
        self.assertEqual(agent._completion_kwargs(messages=[])["model"], "accounts/fireworks/models/glm-5p2")
        self.assertEqual(
            summarize._completion_kwargs(messages=[])["model"],
            "accounts/fireworks/models/qwen3-8b",
        )
        self.assertIn("reasoning_effort", agent._completion_kwargs(messages=[]))
        self.assertNotIn("reasoning_effort", summarize._completion_kwargs(messages=[]))

    def test_thorough_profiles_use_dedicated_model_env(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SUMMARIZE_MODEL": "accounts/fireworks/models/deepseek-v4-flash",
                "THOROUGH_PLANNER_UNIT_MODEL": "accounts/fireworks/models/unit-model",
                "THOROUGH_MERGER_MODEL": "accounts/fireworks/models/merger-model",
            },
            clear=False,
        ):
            settings = get_settings()
        unit = LLMClient(settings, profile="thorough_planner_unit")
        merger = LLMClient(settings, profile="thorough_merger")
        self.assertEqual(
            unit._completion_kwargs(messages=[])["model"],
            "accounts/fireworks/models/unit-model",
        )
        self.assertEqual(
            merger._completion_kwargs(messages=[])["model"],
            "accounts/fireworks/models/merger-model",
        )
        self.assertNotIn("reasoning_effort", unit._completion_kwargs(messages=[]))

    def test_thorough_planner_defaults_when_model_env_empty(self) -> None:
        env = {
            k: v for k, v in os.environ.items() if not k.startswith("THOROUGH_PLANNER_")
        }
        with patch.dict("os.environ", env, clear=True):
            settings = get_settings()
        self.assertEqual(
            LLMClient(settings, profile="thorough_planner_unit")._completion_kwargs(
                messages=[]
            )["model"],
            "accounts/fireworks/models/kimi-k2p6",
        )
        self.assertEqual(
            LLMClient(settings, profile="thorough_planner_surface")._completion_kwargs(
                messages=[]
            )["model"],
            "accounts/fireworks/models/glm-5p2",
        )
        self.assertEqual(
            LLMClient(settings, profile="thorough_planner_hot")._completion_kwargs(
                messages=[]
            )["model"],
            "accounts/fireworks/models/qwen3p7-plus",
        )

    def test_thorough_merger_defaults_to_glm(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("THOROUGH_MERGER_")}
        with patch.dict("os.environ", env, clear=True):
            settings = get_settings()
        self.assertEqual(
            LLMClient(settings, profile="thorough_merger")._completion_kwargs(messages=[])[
                "model"
            ],
            "accounts/fireworks/models/glm-5p2",
        )
        self.assertEqual(settings.thorough_planner_max_output_tokens, 4096)
        self.assertEqual(settings.thorough_merger_max_output_tokens, 8192)


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
