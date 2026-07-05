import unittest
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

from agent.context_stats import format_context_fill_percent, format_context_stats
from agent.loop import Agent
from config import get_settings
from tools.index import HybridToolIndex
from tools.registry import ToolRegistry
from tools.runtime import ToolRuntime


@dataclass(frozen=True)
class _StatsSettings:
    openai_model: str
    reasoning_effort: str | None
    llm_context_window_tokens: int


class ContextStatsFormatTests(unittest.TestCase):
    def test_format_context_stats(self) -> None:
        settings = _StatsSettings(
            openai_model="ag/gemini-3.5-flash-low",
            reasoning_effort="high",
            llm_context_window_tokens=1_000_000,
        )
        report = format_context_stats(settings, 100_000)  # type: ignore[arg-type]
        self.assertIn("ag/gemini-3.5-flash-low", report)
        self.assertIn("Reasoning: `high`", report)
        self.assertIn("100,000", report)
        self.assertIn("1,000,000", report)
        self.assertIn("10.0%", report)

    def test_format_context_fill_percent_small(self) -> None:
        self.assertEqual(format_context_fill_percent(5_000, 1_000_000), "0.50%")

    def test_format_context_fill_percent_tiny(self) -> None:
        self.assertEqual(format_context_fill_percent(1, 1_000_000), "<0.01%")


class ContextStatsAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_stats_report_uses_token_counter(self) -> None:
        settings = get_settings()
        registry = ToolRegistry()
        runtime = ToolRuntime(registry, HybridToolIndex(registry, settings))
        agent = Agent(settings, runtime)

        with patch.object(
            agent._llm,
            "count_prompt_tokens",
            new=AsyncMock(return_value=5427),
        ) as counter:
            report = await agent.context_stats_report([])

        counter.assert_awaited_once()
        self.assertIn("5,427", report)
        self.assertIn("0.54%", report)


if __name__ == "__main__":
    unittest.main()
