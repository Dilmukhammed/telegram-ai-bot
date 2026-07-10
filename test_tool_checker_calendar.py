import json
import unittest
from dataclasses import replace

from agent.run_trace import ToolStep
from agent.tool_checker import should_run_tool_checker
from agent.tool_checker_evidence import EvidenceResolver
from config import get_settings
from tools.builtins.google.calendar_checker import (
    CALENDAR_CHECKER_ALL_TOOL_NAMES,
    CALENDAR_CHECKER_QUESTIONS_BY_TOOL,
    CALENDAR_CHECKER_READ_TOOL_NAMES,
    CALENDAR_CHECKER_WRITE_TOOL_NAMES,
    GOOGLE_CALENDAR_DELETE_EVENT_QUESTIONS,
    GOOGLE_CALENDAR_PATCH_EVENT_QUESTIONS,
)
from tools.builtins.google.calendar_tools import GOOGLE_CALENDAR_TOOLS
from tools.checker.registry import get_checker_questions
from tools.verification import CheckerRuntimeContext, EVIDENCE_LIVE_FETCH, EVIDENCE_PRIOR_TOOL


def _use_step(
    *,
    turn: int,
    tool_name: str,
    arguments: dict,
    result: dict,
) -> ToolStep:
    return ToolStep(
        turn=turn,
        meta_tool="use_tool",
        target_tool=tool_name,
        arguments_raw={"tool_name": tool_name, "arguments": arguments},
        arguments_normalized=arguments,
        result_ok=True,
        result_json=json.dumps(result, ensure_ascii=False),
    )


class CalendarCheckerPackTests(unittest.TestCase):
    def test_all_24_calendar_tools_have_handcrafted_questions(self) -> None:
        tools_by_name = {tool.name: tool for tool in GOOGLE_CALENDAR_TOOLS}
        self.assertEqual(len(CALENDAR_CHECKER_ALL_TOOL_NAMES), 24)
        for name in CALENDAR_CHECKER_ALL_TOOL_NAMES:
            self.assertIn(name, tools_by_name, msg=name)
            questions = get_checker_questions(tools_by_name[name])
            self.assertGreaterEqual(len(questions), 2, msg=name)
            self.assertEqual(questions, CALENDAR_CHECKER_QUESTIONS_BY_TOOL[name], msg=name)

    def test_read_and_write_partitions_cover_all(self) -> None:
        self.assertEqual(
            set(CALENDAR_CHECKER_READ_TOOL_NAMES) | set(CALENDAR_CHECKER_WRITE_TOOL_NAMES),
            set(CALENDAR_CHECKER_ALL_TOOL_NAMES),
        )
        self.assertEqual(len(CALENDAR_CHECKER_READ_TOOL_NAMES), 11)
        self.assertEqual(len(CALENDAR_CHECKER_WRITE_TOOL_NAMES), 13)

    def test_write_tools_with_time_change_have_live_slot_fetch(self) -> None:
        for name in (
            "google.calendar.create_event",
            "google.calendar.create_meet_event",
            "google.calendar.patch_event",
            "google.calendar.import_event",
        ):
            fetches = {
                ref.fetch
                for q in CALENDAR_CHECKER_QUESTIONS_BY_TOOL[name]
                for ref in q.evidence
                if ref.kind == EVIDENCE_LIVE_FETCH
            }
            self.assertIn("calendar_slot_conflicts", fetches, msg=name)

    def test_delete_uses_trace_not_live_fetch(self) -> None:
        fetches = {
            ref.fetch
            for q in GOOGLE_CALENDAR_DELETE_EVENT_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertEqual(fetches, set())
        prior_kinds = {
            ref.kind
            for q in GOOGLE_CALENDAR_DELETE_EVENT_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_PRIOR_TOOL
        }
        self.assertIn(EVIDENCE_PRIOR_TOOL, prior_kinds)

    def test_allowlist_glob_matches_calendar_tools(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="google.calendar.*",
        )
        step = _use_step(
            turn=1,
            tool_name="google.calendar.delete_event",
            arguments={"calendar_id": "primary", "event_id": "evt_1"},
            result={"deleted": True},
        )
        tool = next(t for t in GOOGLE_CALENDAR_TOOLS if t.name == "google.calendar.delete_event")
        self.assertTrue(should_run_tool_checker(spec=tool, step=step, settings=settings))

    def test_delete_does_not_require_prior_get_event_in_trace(self) -> None:
        resolver = EvidenceResolver()
        delete = _use_step(
            turn=2,
            tool_name="google.calendar.delete_event",
            arguments={"calendar_id": "primary", "event_id": "evt_1"},
            result={"deleted": True, "calendar_id": "primary", "event_id": "evt_1"},
        )
        bundle = resolver.resolve_bundle(
            questions=GOOGLE_CALENDAR_DELETE_EVENT_QUESTIONS,
            current_step=delete,
            prior_steps=(),
            runtime=CheckerRuntimeContext(bot_timezone="Asia/Tashkent"),
            user_message="удали встречу",
        )
        self.assertEqual(bundle.rule_based_verdicts(), [])

    def test_patch_includes_live_slot_and_event_state(self) -> None:
        question_ids = {item.id for item in GOOGLE_CALENDAR_PATCH_EVENT_QUESTIONS}
        self.assertIn("slot_not_busy", question_ids)
        self.assertIn("correct_event_targeted", question_ids)
        self.assertIn("mutation_reflected", question_ids)


if __name__ == "__main__":
    unittest.main()
