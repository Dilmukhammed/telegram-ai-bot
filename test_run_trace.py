import json
import unittest
from unittest.mock import patch

from agent.context_collapse import SearchContextCollapser, collapse_search_tools_exchange
from agent.run_trace import RunTraceCollector, _detect_repeated_patterns, _normalize_arguments
from tools.coerce import normalize_use_tool_call


class RunTraceCollectorTests(unittest.TestCase):
    def test_records_search_and_use_tool(self) -> None:
        collector = RunTraceCollector(
            user_id=1,
            user_message="find coffee after meeting",
            worker_turns_budget=30,
        )
        collector.begin_worker_turn(0)
        collector.on_tool_dispatch(
            turn=0,
            meta_tool="search_tools",
            arguments_raw={"mode": "catalog", "tags": ["google", "maps"]},
            call_id="call_search",
        )
        collector.on_tool_result(
            turn=0,
            call_id="call_search",
            result_json=json.dumps({"count": 5, "tools": [{"name": "google.maps.places_text_search"}]}),
            duration_ms=12,
        )

        collector.on_tool_dispatch(
            turn=1,
            meta_tool="use_tool",
            arguments_raw={
                "tool_name": "google.maps.places_text_search",
                "arguments": {"query": "coffee Tashkent"},
            },
            call_id="call_use",
        )
        collector.on_tool_result(
            turn=1,
            call_id="call_use",
            result_json=json.dumps({"ok": True, "tool_name": "google.maps.places_text_search", "result": {"count": 1}}),
            duration_ms=400,
        )

        trace = collector.finish("completed")

        self.assertEqual(len(trace.steps), 2)
        self.assertEqual(len(trace.search_history), 1)
        self.assertEqual(trace.search_history[0]["mode"], "catalog")
        self.assertIn("google.maps.places_text_search", trace.successful_tools)
        self.assertIn("places_text_search OK", trace.progress_summary)

        from agent.run_cycle_log import build_run_cycle_log
        from config import get_settings

        log = build_run_cycle_log(trace, settings=get_settings())
        self.assertIn("google.maps.places_text_search OK", log)

    def test_shows_raw_vs_normalized_mistake(self) -> None:
        collector = RunTraceCollector(
            user_id=1,
            user_message="coffee",
            worker_turns_budget=30,
        )
        raw_args = {
            "tool_name": "google.maps.places_text_search",
            "arguments": {"query": "coffee"},
        }
        target, normalized = _normalize_arguments("use_tool", raw_args)
        self.assertEqual(normalized, {"text_query": "coffee"})

        collector.on_tool_dispatch(
            turn=0,
            meta_tool="use_tool",
            arguments_raw=raw_args,
            call_id="call_use",
        )
        collector.on_tool_result(
            turn=0,
            call_id="call_use",
            result_json=json.dumps({"ok": True, "tool_name": target, "result": {}}),
            duration_ms=50,
        )

        trace = collector.finish("completed")
        self.assertTrue(any("raw keys" in item for item in trace.repeated_patterns))

    def test_search_history_survives_collapse_flag(self) -> None:
        collector = RunTraceCollector(user_id=1, user_message="test", worker_turns_budget=30)
        collector.on_tool_dispatch(
            turn=0,
            meta_tool="search_tools",
            arguments_raw={"mode": "rank", "query": "directions", "tags": ["google", "maps"]},
            call_id="c1",
        )
        collector.on_tool_result(
            turn=0,
            call_id="c1",
            result_json=json.dumps({"count": 2, "tools": [{"name": "google.maps.directions"}]}),
            duration_ms=10,
        )
        collector.mark_last_search_collapsed()

        trace = collector.finish("cap_hit")
        self.assertEqual(len(trace.search_history), 1)
        self.assertTrue(trace.search_history[0]["collapsed_from_context"])

    def test_repeated_search_pattern(self) -> None:
        from agent.run_trace import ToolStep

        steps = [
            ToolStep(
                turn=1,
                meta_tool="search_tools",
                target_tool=None,
                arguments_raw={},
                arguments_normalized={"mode": "catalog", "tags": ["google", "maps"], "query": ""},
            ),
            ToolStep(
                turn=3,
                meta_tool="search_tools",
                target_tool=None,
                arguments_raw={},
                arguments_normalized={"mode": "catalog", "tags": ["google", "maps"], "query": ""},
            ),
        ]
        patterns = _detect_repeated_patterns(steps)
        self.assertTrue(any("search_tools×2" in item for item in patterns))


class RunTraceCollapseIntegrationTests(unittest.TestCase):
    def test_collapser_notifies_trace_hook(self) -> None:
        collapsed: list[str] = []

        def on_collapsed() -> None:
            collapsed.append("yes")

        collapser = SearchContextCollapser(on_search_collapsed=on_collapsed)
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "search_tools", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "content": json.dumps({"count": 1, "tools": []}),
            },
        ]
        self.assertTrue(collapse_search_tools_exchange(messages, (2, 3)))
        collapser._on_search_collapsed and collapser._on_search_collapsed()
        self.assertEqual(collapsed, ["yes"])


class CoerceTraceIntegrationTests(unittest.TestCase):
    def test_places_query_coerced_in_trace_path(self) -> None:
        tool_name, args = normalize_use_tool_call(
            {
                "tool_name": "google.maps.places_text_search",
                "arguments": {"query": "B&B Coffee"},
            }
        )
        self.assertEqual(tool_name, "google.maps.places_text_search")
        self.assertEqual(args["text_query"], "B&B Coffee")


if __name__ == "__main__":
    unittest.main()
