import unittest

from agent.run_trace import RunTrace, RunTraceCollector, ToolStep
from agent.supervisor_telemetry import SupervisorTelemetry
from agent.trace_store import TraceStore


def _sample_trace(*, user_id: int = 42, outcome: str = "completed") -> RunTrace:
    return RunTrace(
        user_id=user_id,
        user_message="find coffee and add to calendar",
        started_at=1.0,
        steps=[
            ToolStep(
                turn=1,
                meta_tool="search_tools",
                target_tool=None,
                arguments_raw={"query": "calendar"},
                arguments_normalized={"query": "calendar"},
                result_ok=True,
            )
        ],
        worker_turns_used=3,
        worker_turns_budget=30,
        final_outcome=outcome,
        successful_tools=["google.calendar.list_events"],
        failed_tools=[],
    )


class TraceStoreTests(unittest.TestCase):
    def test_put_and_get(self) -> None:
        store = TraceStore()
        trace = _sample_trace()
        store.put(42, trace)
        self.assertIs(store.get(42), trace)
        self.assertIsNone(store.get(99))

    def test_put_ignores_none_user(self) -> None:
        store = TraceStore()
        store.put(None, _sample_trace())
        self.assertEqual(len(store._last_by_user), 0)

    def test_format_for_telegram_missing(self) -> None:
        store = TraceStore()
        text = store.format_for_telegram(1)
        self.assertIn("Нет сохранённого trace", text)

    def test_format_for_telegram_includes_summary(self) -> None:
        store = TraceStore()
        store.put(42, _sample_trace(outcome="supervisor_stop"))
        text = store.format_for_telegram(42)
        self.assertIn("Last RunTrace", text)
        self.assertIn("supervisor_stop", text)
        self.assertIn("google.calendar.list_events", text)
        self.assertLessEqual(len(text), 3500)

    def test_format_coach_last_includes_trace_input(self) -> None:
        store = TraceStore()
        trace = _sample_trace()
        trace.coach_reviews.append(
            {
                "turn": 2,
                "tool_calls": 5,
                "trace_input": "Goal: F1 2020\nDiscovery:\nT1 exa.web_search query='austria'",
                "on_track": False,
                "focus_now": "Австрия",
                "assessment": "test",
                "collapse_risk": "low",
            }
        )
        store.put(42, trace)
        text = store.format_coach_last_for_telegram(42)
        self.assertIn("Last coach input", text)
        self.assertIn("exa.web_search query='austria'", text)
        self.assertIn("focus_now: `Австрия`", text)


class SupervisorTelemetryTests(unittest.TestCase):
    def test_record_and_summary(self) -> None:
        telemetry = SupervisorTelemetry()
        telemetry.record(user_id=1, trigger="cap_hit", decision="CONTINUE", bonus_turns=10)
        telemetry.record(user_id=1, trigger="loop_search", decision="STOP_GRACEFUL")

        summary = telemetry.summary()
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["by_decision"]["CONTINUE"], 1)
        self.assertEqual(summary["by_trigger"]["cap_hit"], 1)

    def test_format_report_empty(self) -> None:
        telemetry = SupervisorTelemetry()
        self.assertIn("Пока нет вызовов", telemetry.format_report())

    def test_format_report_with_data(self) -> None:
        telemetry = SupervisorTelemetry()
        telemetry.record(user_id=1, trigger="cap_hit", decision="CONTINUE", bonus_turns=10)
        report = telemetry.format_report()
        self.assertIn("Supervisor stats", report)
        self.assertIn("cap_hit", report)
        self.assertIn("+10 turns", report)


class RunTraceCollectorDebugTests(unittest.TestCase):
    def test_user_id_property(self) -> None:
        collector = RunTraceCollector(
            user_id=7,
            user_message="test",
            worker_turns_budget=30,
        )
        self.assertEqual(collector.user_id, 7)


if __name__ == "__main__":
    unittest.main()
