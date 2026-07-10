import json
import unittest

from agent.run_cycle_log import (
    build_cycle_log_for_checker,
    build_run_cycle_log,
    format_checker_review_line,
    format_worker_step_line,
)
from agent.run_trace import RunTrace, ToolStep
from config import get_settings


def _worker_step(
    *,
    turn: int,
    tool: str,
    args: dict | None = None,
    result: dict | None = None,
) -> ToolStep:
    result_payload = {
        "tool_name": tool,
        "ok": True,
        "result": result or {"created": True},
    }
    return ToolStep(
        turn=turn,
        meta_tool="use_tool",
        target_tool=tool,
        arguments_raw={},
        arguments_normalized=args or {},
        result_ok=True,
        result_json=json.dumps(result_payload),
    )


class RunCycleLogTests(unittest.TestCase):
    def test_interleaves_worker_and_checker_lines(self) -> None:
        settings = get_settings()
        trace = RunTrace(
            user_id=1,
            user_message="создай встречу завтра в 15",
            started_at=0.0,
            steps=[
                _worker_step(
                    turn=2,
                    tool="google.calendar.quick_add_event",
                    args={"text": "Встреча завтра 15:00"},
                    result={
                        "created": True,
                        "event": {"id": "evt_a", "start": "2026-07-09T15:00:00+05:00"},
                    },
                ),
                _worker_step(
                    turn=3,
                    tool="google.calendar.delete_event",
                    args={"event_id": "evt_a"},
                    result={"deleted": True},
                ),
            ],
            checker_reviews=[
                {
                    "tool_name": "google.calendar.quick_add_event",
                    "turn": 2,
                    "overall": "pass",
                    "verdicts": [
                        {"question_id": "slot_not_busy", "verdict": "pass", "severity": "critical"},
                    ],
                }
            ],
        )
        text = build_run_cycle_log(trace, settings=settings)
        self.assertIn("worker → google.calendar.quick_add_event", text)
        self.assertIn("checker → google.calendar.quick_add_event", text)
        self.assertIn("worker → google.calendar.delete_event", text)
        self.assertIn("slot_not_busy=pass", text)

    def test_checker_snapshot_excludes_same_turn_prior_checker(self) -> None:
        settings = get_settings()
        steps = (
            _worker_step(
                turn=2,
                tool="google.calendar.quick_add_event",
                args={"text": "Встреча завтра 15:00"},
            ),
            _worker_step(
                turn=3,
                tool="google.calendar.delete_event",
                args={"event_id": "evt_a"},
            ),
        )
        prior_reviews = (
            {
                "tool_name": "google.calendar.quick_add_event",
                "turn": 2,
                "overall": "warn",
                "verdicts": [],
            },
        )
        log = build_cycle_log_for_checker(
            user_message="создай встречу",
            steps=steps,
            checker_reviews=prior_reviews,
            current_step=steps[1],
            settings=settings,
        )
        self.assertIn("quick_add_event", log)
        self.assertIn("delete_event", log)
        self.assertIn("checker → google.calendar.quick_add_event", log)
        self.assertNotIn("checker → google.calendar.delete_event", log)

    def test_format_checker_includes_pass_and_fail(self) -> None:
        line = format_checker_review_line(
            {
                "tool_name": "google.calendar.delete_event",
                "turn": 3,
                "overall": "fail",
                "verdicts": [
                    {"question_id": "user_intent_to_delete", "verdict": "fail", "severity": "critical"},
                    {"question_id": "correct_event_targeted", "verdict": "pass", "severity": "critical"},
                ],
            }
        )
        self.assertIn("user_intent_to_delete=fail", line)
        self.assertIn("correct_event_targeted=pass", line)

    def test_worker_line_calendar_args(self) -> None:
        step = _worker_step(
            turn=2,
            tool="google.calendar.create_event",
            args={
                "summary": "Sync",
                "start": {"datetime": "2026-07-09T15:00:00"},
                "end": {"datetime": "2026-07-09T16:00:00"},
            },
        )
        line = format_worker_step_line(
            step,
            step_limit=200,
            current_turn=2,
            stale_steps=3,
            archive_min=500,
            include_collapse_tags=False,
        )
        self.assertIn("summary=", line)
        self.assertIn("start=2026-07-09T15:00:00", line)


if __name__ == "__main__":
    unittest.main()
