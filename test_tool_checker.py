import json
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from agent.run_trace import RunTrace, RunTraceCollector, ToolStep
from agent.tool_checker import (
    ToolChecker,
    compute_overall,
    parse_checker_response,
    should_run_tool_checker,
)
from agent.trace_store import TraceStore
from config import get_settings
from tools.builtins.google.calendar_tools import GOOGLE_CALENDAR_CREATE_EVENT
from tools.verification import SEVERITY_CRITICAL, VERDICT_FAIL, VERDICT_PASS


def _create_step(*, turn: int = 2) -> ToolStep:
    return ToolStep(
        turn=turn,
        meta_tool="use_tool",
        target_tool="google.calendar.create_event",
        arguments_raw={},
        arguments_normalized={
            "calendar_id": "primary",
            "summary": "Sync",
            "start": {"datetime": "2026-07-08T15:00:00+05:00"},
            "end": {"datetime": "2026-07-08T16:00:00+05:00"},
        },
        result_ok=True,
        result_json=json.dumps({"ok": True, "event_id": "evt_1"}),
    )


class ToolCheckerParseTests(unittest.TestCase):
    def test_parse_checker_response(self) -> None:
        raw = json.dumps(
            {
                "verdicts": [
                    {
                        "question_id": "time_matches_user",
                        "verdict": "pass",
                        "reason": "Matches 15:00 request",
                    }
                ],
                "overall": "pass",
            }
        )
        verdicts, overall = parse_checker_response(
            raw,
            question_ids={"time_matches_user"},
        )
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].verdict, VERDICT_PASS)
        self.assertEqual(overall, "pass")

    def test_compute_overall_critical_fail(self) -> None:
        from tools.verification import QuestionVerdict

        overall = compute_overall(
            [
                QuestionVerdict(
                    question_id="slot_not_busy",
                    verdict=VERDICT_FAIL,
                    severity=SEVERITY_CRITICAL,
                    reason="missing freebusy",
                )
            ]
        )
        self.assertEqual(overall, "fail")


class ToolCheckerGateTests(unittest.TestCase):
    def test_disabled_when_env_off(self) -> None:
        settings = replace(get_settings(), agent_checker_enabled=False)
        self.assertFalse(should_run_tool_checker(
            spec=GOOGLE_CALENDAR_CREATE_EVENT,
            step=_create_step(),
            settings=settings,
        ))

    def test_enabled_by_default(self) -> None:
        settings = get_settings()
        self.assertTrue(settings.agent_checker_enabled)
        self.assertTrue(should_run_tool_checker(
            spec=GOOGLE_CALENDAR_CREATE_EVENT,
            step=_create_step(),
            settings=settings,
        ))

    def test_enabled_with_allowlist(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="google.calendar.create_event",
        )
        self.assertTrue(should_run_tool_checker(
            spec=GOOGLE_CALENDAR_CREATE_EVENT,
            step=_create_step(),
            settings=settings,
        ))


class ToolCheckerReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_freebusy_still_runs_llm_for_other_questions(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="google.calendar.create_event",
        )
        mock_llm = AsyncMock()
        mock_llm.chat_without_reasoning = AsyncMock(
            return_value=json.dumps({"verdicts": [], "overall": "unknown"})
        )
        runtime = AsyncMock()
        runtime.use_tool = AsyncMock(return_value={"ok": False, "error": "no oauth"})
        checker = ToolChecker(mock_llm, settings)
        review = await checker.review_step(
            spec=GOOGLE_CALENDAR_CREATE_EVENT,
            current_step=_create_step(),
            prior_steps=(),
            user_message="meeting tomorrow 3pm",
            user_id=42,
            runtime=runtime,
        )
        slot = next(item for item in review.verdicts if item.question_id == "slot_not_busy")
        self.assertEqual(slot.verdict, "unknown")
        mock_llm.chat_without_reasoning.assert_awaited()

    async def test_trace_collector_records_checker_review(self) -> None:
        settings = replace(get_settings(), agent_checker_enabled=True)
        mock_llm = AsyncMock()
        mock_llm.chat_without_reasoning = AsyncMock(return_value='{"verdicts":[],"overall":"pass"}')
        runtime = AsyncMock()
        runtime.use_tool = AsyncMock(return_value={"ok": True, "result": {"events": []}})
        checker = ToolChecker(mock_llm, settings)
        collector = RunTraceCollector(
            user_id=1,
            user_message="meeting",
            worker_turns_budget=30,
        )
        review = await checker.review_step(
            spec=GOOGLE_CALENDAR_CREATE_EVENT,
            current_step=_create_step(),
            prior_steps=(),
            user_message="meeting",
            user_id=1,
            runtime=runtime,
        )
        collector.record_checker_review(review)
        trace = collector.finish("completed")
        self.assertEqual(len(trace.checker_reviews), 1)
        self.assertEqual(trace.checker_reviews[0]["tool_name"], "google.calendar.create_event")


class TraceStoreCheckerTests(unittest.TestCase):
    def test_format_checker_last(self) -> None:
        store = TraceStore()
        trace = RunTrace(
            user_id=42,
            user_message="meeting",
            started_at=0.0,
            checker_reviews=[
                {
                    "tool_name": "google.calendar.create_event",
                    "turn": 2,
                    "overall": "fail",
                    "rule_based_only": False,
                    "verdicts": [
                        {
                            "question_id": "slot_not_busy",
                            "severity": "critical",
                            "verdict": "fail",
                            "reason": "Required evidence not found",
                        }
                    ],
                    "checker_input": "Goal: meeting",
                }
            ],
        )
        store.put(42, trace)
        text = store.format_checker_last_for_telegram(42)
        self.assertIn("google.calendar.create_event", text)
        self.assertIn("slot_not_busy", text)
        self.assertIn("Required evidence not found", text)


class TraceCollectorHelperTests(unittest.TestCase):
    def test_checker_dedup_first_seen_only(self) -> None:
        collector = RunTraceCollector(user_id=1, user_message="x", worker_turns_budget=30)
        self.assertTrue(collector.register_checker_dedup("a"))
        self.assertFalse(collector.register_checker_dedup("a"))
        self.assertTrue(collector.register_checker_dedup("b"))

    def test_steps_before_uses_identity(self) -> None:
        collector = RunTraceCollector(user_id=1, user_message="x", worker_turns_budget=30)
        collector.on_tool_dispatch(
            turn=0, meta_tool="use_tool",
            arguments_raw={"tool_name": "google.calendar.list_events", "arguments": {}},
            call_id="c1",
        )
        collector.on_tool_dispatch(
            turn=0, meta_tool="use_tool",
            arguments_raw={"tool_name": "google.calendar.list_colors", "arguments": {}},
            call_id="c2",
        )
        # Results arrive out of dispatch order (parallel gather).
        step2 = collector.on_tool_result(turn=0, call_id="c2", result_json='{"ok":true}', duration_ms=1)
        step1 = collector.on_tool_result(turn=0, call_id="c1", result_json='{"ok":true}', duration_ms=1)
        assert step1 is not None and step2 is not None
        self.assertEqual(step1.target_tool, "google.calendar.list_events")
        self.assertEqual(step2.target_tool, "google.calendar.list_colors")
        # steps_before(step2) must exclude step2 and include step1 (correct prior set).
        prior_of_step2 = collector.steps_before(step2)
        self.assertIn(step1, prior_of_step2)
        self.assertNotIn(step2, prior_of_step2)


class RuleCheckKindTests(unittest.TestCase):
    def test_declarative_and_legacy_id_resolution(self) -> None:
        from agent.tool_checker import _rule_check_kind
        from tools.verification import (
            RULE_CHECK_RESOURCE_EXISTS,
            RULE_CHECK_SLOT_FREE,
            VerificationQuestion,
        )

        declared = VerificationQuestion(id="whatever", text="t", rule_check=RULE_CHECK_RESOURCE_EXISTS)
        self.assertEqual(_rule_check_kind(declared), RULE_CHECK_RESOURCE_EXISTS)
        legacy_slot = VerificationQuestion(id="slot_not_busy", text="t")
        self.assertEqual(_rule_check_kind(legacy_slot), RULE_CHECK_SLOT_FREE)
        legacy_exists = VerificationQuestion(id="target_resource_exists", text="t")
        self.assertEqual(_rule_check_kind(legacy_exists), RULE_CHECK_RESOURCE_EXISTS)
        plain = VerificationQuestion(id="calendar_correct", text="t")
        self.assertEqual(_rule_check_kind(plain), "")

    def test_resource_exists_unknown_when_no_exists_field(self) -> None:
        from agent.tool_checker_live import rule_verdict_for_resource_exists
        from tools.verification import EVIDENCE_LIVE_FETCH, EvidenceSnippet, VERDICT_UNKNOWN

        snippet = EvidenceSnippet(
            label="sheets_range_live",
            kind=EVIDENCE_LIVE_FETCH,
            turn=None,
            tool_name="google.sheets.get_values",
            content=json.dumps({"fetch_ok": True, "range": "A1:B2"}),
        )
        verdict = rule_verdict_for_resource_exists(
            question_id="target_resource_exists",
            severity=SEVERITY_CRITICAL,
            snippet=snippet,
        )
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict.verdict, VERDICT_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
