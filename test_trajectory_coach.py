import json
import unittest

from agent.coach_dialog import (
    COACH_REPLY_TOOL_NAME,
    is_billable_meta_tool_call,
    record_coach_worker_reply,
    reset_coach_dialog,
)
from agent.coach_sheets import extract_completed_sheet_tabs
from agent.coach_outputs import format_outputs_produced
from agent.coach_progress import (
    detect_coach_trace_conflicts,
    format_coach_coaching_with_trace,
)
from agent.coach_trace import _STEP_SEP, build_coach_trace
from agent.run_trace import RunTrace, ToolStep
from agent.trajectory_coach import (
    format_coach_coaching,
    format_coach_status,
    parse_coach_response,
    should_run_coach_review,
)
from config import get_settings


class CoachTraceTests(unittest.TestCase):
    def test_timeline_format_with_arrows(self) -> None:
        settings = get_settings()
        trace = RunTrace(
            user_id=1,
            user_message="find F1 2020 races",
            started_at=0.0,
            steps=[
                ToolStep(
                    turn=1,
                    meta_tool="search_tools",
                    target_tool=None,
                    arguments_raw={"query": "sheets", "mode": "rank"},
                    arguments_normalized={"query": "sheets", "mode": "rank", "top_k": 5, "tags": []},
                    result_ok=True,
                    result_json=json.dumps({"count": 2, "tools": [{"name": "google.sheets.create_spreadsheet"}]}),
                ),
                ToolStep(
                    turn=1,
                    meta_tool="use_tool",
                    target_tool="exa.web_search",
                    arguments_raw={"tool_name": "exa.web_search", "arguments": {"query": "2020 Austrian GP"}},
                    arguments_normalized={"query": "2020 Austrian GP"},
                    result_ok=True,
                    result_json=json.dumps(
                        {
                            "archived": True,
                            "ref": 7,
                            "tool_name": "exa.web_search",
                            "summary": "Found Austrian GP Wikipedia and Autosport reports.",
                        }
                    ),
                ),
            ],
            worker_turns_used=1,
            worker_turns_budget=30,
        )
        text = build_coach_trace(trace, settings=settings)
        self.assertIn("User goal:", text)
        self.assertIn("Cycle log:", text)
        self.assertIn(_STEP_SEP, text)
        self.assertIn("[turn 1] worker → search_tools OK", text)
        self.assertIn("[turn 1] worker → exa.web_search OK", text)
        self.assertIn("Austrian GP", text)
        self.assertNotIn("Discovery", text)

    def test_each_step_respects_field_limit(self) -> None:
        settings = get_settings()
        long_summary = "x" * 800
        trace = RunTrace(
            user_id=1,
            user_message="test",
            started_at=0.0,
            steps=[
                ToolStep(
                    turn=1,
                    meta_tool="use_tool",
                    target_tool="exa.web_search",
                    arguments_raw={"tool_name": "exa.web_search", "arguments": {"query": "q"}},
                    arguments_normalized={"query": "q"},
                    result_ok=True,
                    result_json=json.dumps(
                        {"archived": True, "ref": 1, "tool_name": "exa.web_search", "summary": long_summary}
                    ),
                )
            ],
            worker_turns_used=1,
            worker_turns_budget=30,
        )
        text = build_coach_trace(trace, settings=settings)
        step_line = text.split(_STEP_SEP)[-1]
        self.assertLessEqual(len(step_line), 500)

    def test_sheets_step_shows_range_not_values_blob(self) -> None:
        settings = get_settings()
        trace = RunTrace(
            user_id=1,
            user_message="F1",
            started_at=0.0,
            steps=[
                ToolStep(
                    turn=2,
                    meta_tool="use_tool",
                    target_tool="google.sheets.update_values",
                    arguments_raw={
                        "tool_name": "google.sheets.update_values",
                        "arguments": {"range": "Тоскана!A1:F40", "values": [["a"]] * 40},
                    },
                    arguments_normalized={"range": "Тоскана!A1:F40", "values": [["a"]] * 40},
                    result_ok=True,
                    result_json=json.dumps(
                        {"ok": True, "result": {"updated_range": "Тоскана!A1:F40", "updated_cells": 240}}
                    ),
                )
            ],
            worker_turns_used=2,
            worker_turns_budget=60,
        )
        text = build_coach_trace(trace, settings=settings)
        self.assertIn("Тоскана!A1:F40", text)
        self.assertIn("values=40x1", text)
        self.assertIn("updated_cells=240", text)

    def test_parse_coach_response(self) -> None:
        raw = json.dumps(
            {
                "intervene": True,
                "on_track": False,
                "confidence": 0.9,
                "assessment": "Searching many races without writing.",
                "strategy": "Finish R01 completely before R02.",
                "warnings": ["collapse in 10 steps"],
                "focus_now": "R01_Bahrain",
                "do_not": ["batch search all GPs"],
                "collapse_risk": "high",
            }
        )
        decision = parse_coach_response(raw)
        self.assertTrue(decision.intervene)
        self.assertFalse(decision.on_track)
        self.assertEqual(decision.focus_now, "R01_Bahrain")
        self.assertTrue(decision.should_inject_hint())

    def test_coach_skip_when_not_intervening(self) -> None:
        decision = parse_coach_response(
            json.dumps(
                {
                    "intervene": False,
                    "on_track": True,
                    "assessment": "",
                    "strategy": "",
                }
            )
        )
        self.assertFalse(decision.should_inject_hint())
        self.assertIn("без вмешательства", format_coach_status(decision))

    def test_hot_data_countdown_in_trace(self) -> None:
        settings = get_settings()
        long_body = "x" * (settings.tool_result_archive_min_chars + 100)
        trace = RunTrace(
            user_id=1,
            user_message="F1",
            started_at=0.0,
            steps=[
                ToolStep(
                    turn=2,
                    meta_tool="use_tool",
                    target_tool="exa.web_search",
                    arguments_raw={"tool_name": "exa.web_search", "arguments": {"query": "q"}},
                    arguments_normalized={"query": "q"},
                    result_ok=True,
                    result_json=json.dumps({"ok": True, "result": {"body": long_body}}),
                )
            ],
            worker_turns_used=5,
            worker_turns_budget=30,
        )
        text = build_coach_trace(trace, settings=settings)
        self.assertIn("data: full", text)
        self.assertIn("until collapse", text)

    def test_should_run_coach_review_after_parallel_batch(self) -> None:
        self.assertTrue(
            should_run_coach_review(
                tool_calls_completed=11,
                last_coach_at_tool_count=0,
                every_n=5,
            )
        )

    def test_worker_replies_full_text_in_coach_trace(self) -> None:
        settings = get_settings()
        long_reply = "Austrian GP tab complete. Now filling Styrian GP (race 2)." + ("!" * 600)
        reset_coach_dialog()
        record_coach_worker_reply(
            message=long_reply,
            turn=3,
            tool_calls_at=12,
            tool_step_index=14,
        )
        trace = RunTrace(
            user_id=1,
            user_message="F1 2020",
            started_at=0.0,
            steps=[],
            worker_turns_used=3,
            worker_turns_budget=30,
            worker_coach_replies=[
                {
                    "message": long_reply,
                    "turn": 3,
                    "tool_calls_at": 12,
                    "tool_step_index": 14,
                }
            ],
        )
        text = build_coach_trace(trace, settings=settings)
        self.assertIn("Worker replies to coach", text)
        self.assertIn(long_reply, text)
        self.assertNotIn(COACH_REPLY_TOOL_NAME, text)

    def test_coach_reply_not_billable(self) -> None:
        self.assertFalse(
            is_billable_meta_tool_call("use_tool", COACH_REPLY_TOOL_NAME),
        )
        self.assertTrue(is_billable_meta_tool_call("use_tool", "exa.web_search"))

    def test_format_coach_coaching_mentions_reply(self) -> None:
        trace = RunTrace(
            user_id=1,
            user_message="F1",
            started_at=0.0,
            steps=[
                ToolStep(
                    turn=14,
                    meta_tool="use_tool",
                    target_tool="google.sheets.update_values",
                    arguments_raw={},
                    arguments_normalized={
                        "range": "01_Austrian_GP!A2:F40",
                        "values": [["a", "b"]] * 20,
                    },
                    result_ok=True,
                )
            ],
        )
        decision = parse_coach_response(
            json.dumps(
                {
                    "intervene": True,
                    "on_track": False,
                    "strategy": "Rebuild Austrian GP tab first.",
                }
            )
        )
        messages = format_coach_coaching_with_trace(decision, trace)
        self.assertEqual(len(messages), 2)
        self.assertIn("coach.reply", messages[1]["content"])
        self.assertIn("REQUIRED", messages[1]["content"])
        self.assertIn("01_Austrian_GP", messages[1]["content"])

    def test_sheets_progress_in_coach_trace(self) -> None:
        settings = get_settings()
        trace = RunTrace(
            user_id=1,
            user_message="F1",
            started_at=0.0,
            steps=[
                ToolStep(
                    turn=10,
                    meta_tool="use_tool",
                    target_tool="google.sheets.update_values",
                    arguments_raw={},
                    arguments_normalized={
                        "range": "02_Styrian_GP!A2:F40",
                        "values": [["h"]] * 15,
                    },
                    result_ok=True,
                )
            ],
            worker_turns_used=10,
            worker_turns_budget=30,
        )
        text = build_coach_trace(trace, settings=settings)
        self.assertIn("Sheets units with data written", text)
        self.assertIn("02_Styrian_GP", text)

    def test_detect_coach_conflict(self) -> None:
        steps = [
            ToolStep(
                turn=14,
                meta_tool="use_tool",
                target_tool="google.sheets.update_values",
                arguments_raw={},
                arguments_normalized={
                    "range": "01_Austrian_GP!A2:F40",
                    "values": [["x"]] * 10,
                },
                result_ok=True,
            )
        ]
        decision = parse_coach_response(
            json.dumps(
                {
                    "intervene": True,
                    "focus_now": "Rebuild Austrian GP tab before Styrian GP",
                }
            )
        )
        conflicts = detect_coach_trace_conflicts(steps, decision)
        self.assertIn("01_Austrian_GP", conflicts)
        self.assertEqual(list(extract_completed_sheet_tabs(steps).keys()), ["01_Austrian_GP"])


class CoachOutputsTests(unittest.TestCase):
    @staticmethod
    def _step(turn: int, tool: str, args: dict, res: dict) -> ToolStep:
        return ToolStep(
            turn=turn,
            meta_tool="use_tool",
            target_tool=tool,
            arguments_raw={},
            arguments_normalized=args,
            result_ok=True,
            result_json=json.dumps(res),
        )

    def test_outputs_block_covers_all_families(self) -> None:
        steps = [
            self._step(
                1,
                "google.calendar.create_event",
                {"summary": "Standup"},
                {"ok": True, "result": {"event": {"id": "ev1", "summary": "Standup"}}},
            ),
            self._step(
                2,
                "google.drive.upload_file",
                {"name": "report.pdf"},
                {"ok": True, "result": {"id": "d9", "name": "report.pdf"}},
            ),
            self._step(
                3,
                "workspace.write_file",
                {"path": "data/out.csv"},
                {"ok": True, "result": {"path": "data/out.csv"}},
            ),
            self._step(
                4,
                "google.gmail.send_message",
                {"to": "a@b.com", "subject": "Hi"},
                {"ok": True, "result": {"message_id": "m1"}},
            ),
            self._step(
                5,
                "google.sheets.create_spreadsheet",
                {"title": "Budget"},
                {"ok": True, "result": {"spreadsheet_id": "s1", "title": "Budget"}},
            ),
            self._step(
                6,
                "pdf.create",
                {"output_path": "data/final.pdf"},
                {"ok": True, "result": {"path": "data/final.pdf"}},
            ),
        ]
        block = format_outputs_produced(steps)
        self.assertIn("do not ask to redo", block.lower())
        self.assertIn("Standup", block)
        self.assertIn("report.pdf", block)
        self.assertIn("data/out.csv", block)
        self.assertIn("a@b.com", block)
        self.assertIn("Budget", block)
        self.assertIn("final.pdf", block)

    def test_outputs_block_skips_readonly_and_failures(self) -> None:
        steps = [
            self._step(1, "google.drive.search_files", {"q": "x"}, {"ok": True, "result": {"files": []}}),
            ToolStep(
                turn=2,
                meta_tool="use_tool",
                target_tool="google.calendar.create_event",
                arguments_raw={},
                arguments_normalized={"summary": "Nope"},
                result_ok=False,
                result_json=json.dumps({"ok": False, "error": "boom"}),
            ),
        ]
        self.assertEqual(format_outputs_produced(steps), "")

    def test_outputs_block_in_coach_trace(self) -> None:
        settings = get_settings()
        trace = RunTrace(
            user_id=1,
            user_message="plan week",
            started_at=0.0,
            steps=[
                self._step(
                    1,
                    "google.calendar.create_event",
                    {"summary": "Sync"},
                    {"ok": True, "result": {"event": {"id": "ev1", "summary": "Sync"}}},
                )
            ],
            worker_turns_used=1,
            worker_turns_budget=30,
        )
        text = build_coach_trace(trace, settings=settings)
        self.assertIn("Outputs already produced this run", text)
        self.assertIn("Sync", text)


class CoachWindowingTests(unittest.TestCase):
    def test_window_keeps_newest_drops_oldest(self) -> None:
        import dataclasses

        settings = dataclasses.replace(get_settings(), coach_max_trace_chars=1500)
        steps = [
            ToolStep(
                turn=i,
                meta_tool="use_tool",
                target_tool="exa.web_fetch",
                arguments_raw={},
                arguments_normalized={"urls": [f"http://example.com/{i}"]},
                result_ok=True,
                result_json=json.dumps({"ok": True, "result": {"body": "z" * 400}}),
            )
            for i in range(1, 40)
        ]
        trace = RunTrace(
            user_id=1,
            user_message="fetch many",
            started_at=0.0,
            steps=steps,
            worker_turns_used=39,
            worker_turns_budget=200,
        )
        text = build_coach_trace(trace, settings=settings)
        self.assertLessEqual(len(text), 1500)
        self.assertIn("example.com/39", text)
        self.assertNotIn("example.com/1]", text)
        self.assertIn("omitted", text)


if __name__ == "__main__":
    unittest.main()
