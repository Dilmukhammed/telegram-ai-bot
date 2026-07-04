import os
import unittest
from unittest.mock import patch

from tools.builtins.echo import ECHO_TOOL
from tools.builtins.exa_search import EXA_WEB_SEARCH
from tools.schema import ToolSpec
from tools.search_enrichment import matching_tag_profiles
from tools.tags import filter_tools_by_tags


class FilterToolsByTagsTests(unittest.TestCase):
    def test_no_tags_returns_all(self) -> None:
        tools = [ECHO_TOOL, EXA_WEB_SEARCH]
        self.assertEqual(filter_tools_by_tags(tools, None), tools)
        self.assertEqual(filter_tools_by_tags(tools, []), tools)

    def test_requires_all_tags(self) -> None:
        calendar_tool = ToolSpec(
            name="google.calendar.list_today",
            description="List today's events",
            parameters={"type": "object", "properties": {}},
            handler=lambda _: None,
            tags=("google", "calendar", "read"),
        )
        tools = [ECHO_TOOL, EXA_WEB_SEARCH, calendar_tool]

        self.assertEqual(
            filter_tools_by_tags(tools, ["google", "calendar"]),
            [calendar_tool],
        )
        self.assertEqual(filter_tools_by_tags(tools, ["google"]), [calendar_tool])
        self.assertEqual(filter_tools_by_tags(tools, ["calendar", "read"]), [calendar_tool])
        self.assertEqual(filter_tools_by_tags(tools, ["web"]), [EXA_WEB_SEARCH])


class TagProfileMatchingTests(unittest.TestCase):
    def test_google_calendar_is_one_profile(self) -> None:
        profiles = matching_tag_profiles("show my google calendar today")
        self.assertEqual(profiles, [("google", "calendar")])

    def test_calendar_alone_does_not_match_compound_profile(self) -> None:
        profiles = matching_tag_profiles("calendar events today")
        self.assertEqual(profiles, [])

    def test_max_three_profiles(self) -> None:
        query = "google calendar auth web search"
        profiles = matching_tag_profiles(query)
        self.assertLessEqual(len(profiles), 3)


class SearchToolsTagFilterTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_tools_filters_by_tags(self) -> None:
        from tools.bootstrap import get_tool_runtime

        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            runtime = await get_tool_runtime()

        web_only = await runtime.search_tools("search", top_k=5, tags=["web"])
        self.assertTrue(all("web" in tool["tags"] for tool in web_only["tools"]))

        test_only = await runtime.search_tools("", tags=["test"], mode="catalog")
        self.assertEqual([tool["name"] for tool in test_only["tools"]], ["echo.test"])
        self.assertNotIn("parameters", test_only["tools"][0])

    async def test_catalog_mode_lists_all_google_calendar_tools(self) -> None:
        from tools.bootstrap import get_tool_runtime

        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            runtime = await get_tool_runtime()

        result = await runtime.search_tools(
            "",
            tags=["google", "calendar"],
            mode="catalog",
        )
        self.assertEqual(result["mode"], "catalog")
        self.assertGreaterEqual(result["tag_scope"]["total_in_scope"], 21)
        self.assertEqual(result["tag_scope"]["returned"], result["tag_scope"]["total_in_scope"])
        self.assertTrue(all("parameters" not in tool for tool in result["tools"]))

    async def test_rank_mode_requires_query(self) -> None:
        from tools.bootstrap import get_tool_runtime

        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            runtime = await get_tool_runtime()

        result = await runtime.dispatch_meta_tool(
            "search_tools",
            {"tags": ["google", "calendar"], "mode": "rank", "query": ""},
        )
        self.assertIn("error", result)

        google_only = await runtime.search_tools("events", top_k=10, tags=["google", "calendar"])
        self.assertGreater(google_only["count"], 0)
        self.assertTrue(all("google" in tool["tags"] for tool in google_only["tools"]))

    async def test_explicit_tags_include_total_in_scope(self) -> None:
        from tools.bootstrap import get_tool_runtime

        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            runtime = await get_tool_runtime()

        result = await runtime.search_tools("events", top_k=5, tags=["google", "calendar"])
        self.assertIn("tag_scope", result)
        self.assertEqual(result["tag_scope"]["tags"], ["google", "calendar"])
        self.assertGreaterEqual(result["tag_scope"]["total_in_scope"], result["tag_scope"]["returned"])
        self.assertGreater(result["tag_scope"]["total_in_scope"], 5)

    async def test_untagged_search_adds_tag_hints_without_duplicates(self) -> None:
        from tools.bootstrap import get_tool_runtime

        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            runtime = await get_tool_runtime()

        result = await runtime.search_tools("google calendar events today", top_k=5)
        self.assertIn("tag_hints", result)
        self.assertEqual(result["tag_hints"][0]["tags"], ["google", "calendar"])
        self.assertLessEqual(result["tag_hints"][0]["returned"], 3)
        self.assertGreater(result["tag_hints"][0]["total_in_scope"], 5)

        main_names = {tool["name"] for tool in result["tools"]}
        hint_names = {tool["name"] for tool in result["tag_hints"][0]["tools"]}
        self.assertFalse(main_names & hint_names)


if __name__ == "__main__":
    unittest.main()
