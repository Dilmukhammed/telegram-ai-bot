import os
import unittest
from unittest.mock import AsyncMock, patch

from tools.bootstrap import create_tool_runtime
from tools.cache import ToolResultCache, cache_key
from tools.coerce import normalize_use_tool_call
from tools.context import RunContext
from tools.phase4_config import cache_max_ttl_seconds, cache_ttl_for_tool
from tools.ratelimit import SlidingWindowRateLimiter
from tools.runtime import ToolRuntime
from tools.telemetry import ToolTelemetry


class ToolRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def _runtime(self):
        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            return await create_tool_runtime()

    async def test_search_finds_echo_tool(self) -> None:
        runtime = await self._runtime()
        result = await runtime.search_tools("echo message back", top_k=3)
        names = [tool["name"] for tool in result["tools"]]
        self.assertIn("echo.test", names)

    async def test_use_echo_tool(self) -> None:
        runtime = await self._runtime()
        result = await runtime.use_tool("echo.test", {"message": "hello"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["message"], "hello")

    async def test_unknown_tool_fails(self) -> None:
        runtime = await self._runtime()
        payload = await runtime.dispatch_meta_tool(
            "use_tool",
            {"tool_name": "missing.tool", "arguments": {}},
        )
        self.assertIn("Unknown tool", payload)

    async def test_search_finds_exa_tools(self) -> None:
        runtime = await self._runtime()
        result = await runtime.search_tools("search the web for news", top_k=5)
        names = [tool["name"] for tool in result["tools"]]
        self.assertIn("exa.web_search", names)

    async def test_use_tool_ignores_extra_reason_field(self) -> None:
        runtime = await self._runtime()
        payload = await runtime.dispatch_meta_tool(
            "use_tool",
            {
                "tool_name": "echo.test",
                "arguments": {"message": "hello", "reason": "testing"},
            },
        )
        self.assertIn('"ok": true', payload.lower())
        self.assertIn("hello", payload)

    async def test_use_tool_coerces_nested_exa_args(self) -> None:
        runtime = await self._runtime()
        payload = await runtime.dispatch_meta_tool(
            "use_tool",
            {
                "arguments": {
                    "tool_name": "exa.web_search",
                    "url_or_query_arguments": {"query": "weather in Tashkent"},
                    "reason": "need current weather",
                }
            },
        )
        self.assertNotIn("Unknown arguments", payload)
        self.assertNotIn("Missing required argument", payload)


class CoerceTests(unittest.TestCase):
    def test_nested_tool_name_and_query(self) -> None:
        tool_name, args = normalize_use_tool_call(
            {
                "arguments": {
                    "tool_name": "exa.web_search",
                    "url_or_query_arguments": {"query": "weather in Tashkent"},
                    "reason": "need weather",
                }
            }
        )
        self.assertEqual(tool_name, "exa.web_search")
        self.assertEqual(args, {"query": "weather in Tashkent"})

    def test_reason_stripped_from_valid_call(self) -> None:
        tool_name, args = normalize_use_tool_call(
            {
                "tool_name": "exa.web_search",
                "arguments": {"query": "weather Tashkent", "reason": "lookup"},
            }
        )
        self.assertEqual(tool_name, "exa.web_search")
        self.assertEqual(args, {"query": "weather Tashkent"})

    def test_places_text_search_query_alias(self) -> None:
        tool_name, args = normalize_use_tool_call(
            {
                "tool_name": "google.maps.places_text_search",
                "arguments": {"query": "B&B Coffee House Tashkent"},
            }
        )
        self.assertEqual(tool_name, "google.maps.places_text_search")
        self.assertEqual(args, {"text_query": "B&B Coffee House Tashkent"})

    def test_places_text_search_keeps_text_query(self) -> None:
        tool_name, args = normalize_use_tool_call(
            {
                "tool_name": "google.maps.places_text_search",
                "arguments": {
                    "text_query": "coffee Tashkent",
                    "query": "ignored",
                },
            }
        )
        self.assertEqual(args["text_query"], "coffee Tashkent")
        self.assertNotIn("query", args)

    def test_explicit_none_tool_name_does_not_block_nested_name(self) -> None:
        tool_name, args = normalize_use_tool_call(
            {
                "tool_name": None,
                "arguments": {
                    "tool_name": "google.maps.places_text_search",
                    "reason": "Searching for Samarqand Darvoza in Tashkent",
                },
            }
        )
        self.assertEqual(tool_name, "google.maps.places_text_search")
        self.assertEqual(args, {"text_query": "Searching for Samarqand Darvoza in Tashkent"})

    def test_double_nested_arguments(self) -> None:
        tool_name, args = normalize_use_tool_call(
            {
                "reason": "Find the coordinates",
                "arguments": {
                    "tool_name": "google.maps.places_text_search",
                    "arguments": {"text_query": "Samarqand Darvoza Tashkent"},
                },
            }
        )
        self.assertEqual(tool_name, "google.maps.places_text_search")
        self.assertEqual(args, {"text_query": "Samarqand Darvoza Tashkent"})


class Phase4Tests(unittest.IsolatedAsyncioTestCase):
    async def _runtime(self):
        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            return await create_tool_runtime()

    async def test_cache_hit_on_repeated_echo(self) -> None:
        runtime = await self._runtime()
        runtime._cache = ToolResultCache(86400)

        calls = {"count": 0}

        async def counting_handler(arguments: dict) -> dict:
            calls["count"] += 1
            return {"message": arguments["message"]}

        spec = runtime._registry.get("echo.test")
        object.__setattr__(spec, "handler", counting_handler)
        object.__setattr__(spec, "cache_ttl_seconds", 60)

        first = await runtime.use_tool("echo.test", {"message": "cached"})
        second = await runtime.use_tool("echo.test", {"message": "cached"})

        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(calls["count"], 1)

    async def test_rate_limit_blocks_after_threshold(self) -> None:
        runtime = await self._runtime()
        runtime._rate_limiter = SlidingWindowRateLimiter()
        runtime._cache = ToolResultCache(86400)

        spec = runtime._registry.get("echo.test")
        object.__setattr__(spec, "rate_limit", (2, 60))
        object.__setattr__(spec, "cache_ttl_seconds", None)

        ctx = RunContext(user_id=42, turn=1, meta_tool="use_tool")
        first = await runtime.use_tool("echo.test", {"message": "one"}, ctx=ctx)
        second = await runtime.use_tool("echo.test", {"message": "two"}, ctx=ctx)
        third = await runtime.use_tool("echo.test", {"message": "three"}, ctx=ctx)

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertFalse(third["ok"])
        self.assertEqual(third["error"], "rate_limited")

    def test_cache_ttl_capped_at_one_day(self) -> None:
        with patch.dict(os.environ, {"TOOL_CACHE_MAX_TTL": "86400", "EXA_SEARCH_CACHE_TTL": "999999"}, clear=False):
            ttl = cache_ttl_for_tool("exa.web_search", 300)
            self.assertEqual(ttl, 86400)
            self.assertEqual(cache_max_ttl_seconds(), 86400)

    def test_cache_key_stable(self) -> None:
        left = cache_key("echo.test", {"message": "hello"})
        right = cache_key("echo.test", {"message": "hello"})
        self.assertEqual(left, right)

    async def test_telemetry_records_calls(self) -> None:
        telemetry = ToolTelemetry()
        runtime = await self._runtime()
        runtime._telemetry = telemetry
        await runtime.use_tool("echo.test", {"message": "stats"}, ctx=RunContext(user_id=1))
        summary = telemetry.summary()
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["by_tool"]["echo.test"], 1)


    def test_format_report_empty(self) -> None:
        telemetry = ToolTelemetry()
        report = telemetry.format_report(cache_entries=3)
        self.assertIn("Пока нет вызовов", report)
        self.assertIn("Cache entries: 3", report)

    async def test_stats_report_on_runtime(self) -> None:
        runtime = await self._runtime()
        await runtime.use_tool("echo.test", {"message": "stats"}, ctx=RunContext(user_id=1))
        report = runtime.stats_report()
        self.assertIn("echo.test", report)
        self.assertIn("Total calls", report)


if __name__ == "__main__":
    unittest.main()
