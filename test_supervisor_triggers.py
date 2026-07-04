import json
import unittest

from agent.run_trace import ToolStep
from agent.supervisor import format_supervisor_retry, parse_supervisor_response
from agent.supervisor_triggers import detect_soft_trigger


def _search_step(turn: int) -> ToolStep:
    return ToolStep(
        turn=turn,
        meta_tool="search_tools",
        target_tool=None,
        arguments_raw={"mode": "catalog", "tags": ["google", "maps"]},
        arguments_normalized={"mode": "catalog", "tags": ["google", "maps"], "query": "", "top_k": 5},
        result_ok=True,
        result_json='{"count": 5, "tools": []}',
    )


def _failed_use_step(turn: int, tool: str, error: str) -> ToolStep:
    return ToolStep(
        turn=turn,
        meta_tool="use_tool",
        target_tool=tool,
        arguments_raw={"tool_name": tool, "arguments": {}},
        arguments_normalized={},
        result_ok=False,
        result_error=error,
        result_json=json.dumps({"ok": False, "error": error}),
    )


class SoftTriggerTests(unittest.TestCase):
    def test_loop_search_trigger(self) -> None:
        steps = [_search_step(1), _search_step(2), _search_step(3)]
        trigger = detect_soft_trigger(
            steps,
            completed_turns=3,
            soft_triggers_enabled=True,
            periodic_every=0,
        )
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.reason, "loop_search")

    def test_loop_search_not_triggered_after_successful_use(self) -> None:
        steps = [
            _search_step(1),
            _search_step(2),
            ToolStep(
                turn=3,
                meta_tool="use_tool",
                target_tool="google.maps.places_text_search",
                arguments_raw={},
                arguments_normalized={"text_query": "coffee"},
                result_ok=True,
                result_json='{"ok": true}',
            ),
            _search_step(4),
        ]
        trigger = detect_soft_trigger(
            steps,
            completed_turns=4,
            soft_triggers_enabled=True,
            periodic_every=0,
        )
        self.assertIsNone(trigger)

    def test_loop_fail_trigger(self) -> None:
        steps = [
            _failed_use_step(1, "google.maps.places_text_search", "missing text_query"),
            _failed_use_step(2, "google.maps.places_text_search", "missing text_query"),
        ]
        trigger = detect_soft_trigger(
            steps,
            completed_turns=2,
            soft_triggers_enabled=True,
            periodic_every=0,
        )
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.reason, "loop_fail")

    def test_periodic_trigger(self) -> None:
        trigger = detect_soft_trigger(
            [_search_step(1)],
            completed_turns=15,
            soft_triggers_enabled=True,
            periodic_every=15,
        )
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.reason, "periodic")

    def test_soft_triggers_disabled(self) -> None:
        trigger = detect_soft_trigger(
            [_search_step(1), _search_step(2), _search_step(3)],
            completed_turns=3,
            soft_triggers_enabled=False,
            periodic_every=0,
        )
        self.assertIsNone(trigger)


class StopRetryParseTests(unittest.TestCase):
    def test_parse_stop_retry(self) -> None:
        decision = parse_supervisor_response(
            json.dumps(
                {
                    "decision": "STOP_RETRY",
                    "remaining_steps": ["geocode first", "then create_event"],
                    "bonus_turns": 8,
                }
            ),
            default_bonus_turns=10,
        )
        self.assertEqual(decision.decision, "STOP_RETRY")
        self.assertEqual(decision.bonus_turns, 8)
        text = format_supervisor_retry(decision, 8)
        self.assertIn("revised plan", text)


if __name__ == "__main__":
    unittest.main()
