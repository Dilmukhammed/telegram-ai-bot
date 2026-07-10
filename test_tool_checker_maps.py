import json
import unittest
from dataclasses import replace

from agent.run_trace import ToolStep
from agent.tool_checker import should_run_tool_checker
from config import get_settings
from tools.builtins.google.maps_checker import (
    GOOGLE_MAPS_PLACE_DETAILS_QUESTIONS,
    GOOGLE_MAPS_PLACES_TEXT_SEARCH_QUESTIONS,
    GOOGLE_MAPS_TRAVEL_TIME_QUESTIONS,
    MAPS_CHECKER_ALL_TOOL_NAMES,
    MAPS_CHECKER_QUESTIONS_BY_TOOL,
    MAPS_CHECKER_READ_TOOL_NAMES,
    MAPS_CHECKER_WRITE_TOOL_NAMES,
)
from tools.builtins.google.maps_tools import GOOGLE_MAPS_TOOLS
from tools.checker.registry import get_checker_questions
from tools.verification import EVIDENCE_LIVE_FETCH


class MapsCheckerPackTests(unittest.TestCase):
    def test_all_18_maps_tools_have_handcrafted_questions(self) -> None:
        tools_by_name = {tool.name: tool for tool in GOOGLE_MAPS_TOOLS}
        self.assertEqual(len(MAPS_CHECKER_ALL_TOOL_NAMES), 18)
        self.assertEqual(len(GOOGLE_MAPS_TOOLS), 18)
        for name in MAPS_CHECKER_ALL_TOOL_NAMES:
            self.assertIn(name, tools_by_name, msg=name)
            questions = get_checker_questions(tools_by_name[name])
            self.assertGreaterEqual(len(questions), 1, msg=name)
            self.assertEqual(questions, MAPS_CHECKER_QUESTIONS_BY_TOOL[name], msg=name)

    def test_all_maps_tools_are_read_only(self) -> None:
        self.assertEqual(MAPS_CHECKER_READ_TOOL_NAMES, MAPS_CHECKER_ALL_TOOL_NAMES)
        self.assertEqual(MAPS_CHECKER_WRITE_TOOL_NAMES, ())

    def test_text_search_uses_text_query_question(self) -> None:
        self.assertIn("text_query_matches", {q.id for q in GOOGLE_MAPS_PLACES_TEXT_SEARCH_QUESTIONS})

    def test_place_details_place_id_question(self) -> None:
        self.assertIn("place_id_correct", {q.id for q in GOOGLE_MAPS_PLACE_DETAILS_QUESTIONS})

    def test_travel_time_eta_intent_question(self) -> None:
        self.assertIn("eta_only_intent", {q.id for q in GOOGLE_MAPS_TRAVEL_TIME_QUESTIONS})

    def test_no_live_fetch_on_read_maps_tools(self) -> None:
        for name in MAPS_CHECKER_ALL_TOOL_NAMES:
            fetches = {
                ref.fetch
                for q in MAPS_CHECKER_QUESTIONS_BY_TOOL[name]
                for ref in q.evidence
                if ref.kind == EVIDENCE_LIVE_FETCH
            }
            self.assertEqual(fetches, set(), msg=name)

    def test_allowlist_glob_matches_maps(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="google.maps.*",
        )
        tool = next(t for t in GOOGLE_MAPS_TOOLS if t.name == "google.maps.geocode")
        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="google.maps.geocode",
            arguments_raw={},
            arguments_normalized={"address": "Chorsu Bazaar, Tashkent"},
            result_ok=True,
            result_json=json.dumps({"lat": 41.326, "lng": 69.228}),
        )
        self.assertTrue(should_run_tool_checker(spec=tool, step=step, settings=settings))


if __name__ == "__main__":
    unittest.main()
