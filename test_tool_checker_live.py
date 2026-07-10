import json
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from agent.run_trace import ToolStep
from agent.tool_checker import ToolChecker
from agent.tool_checker_live import rule_verdict_for_slot_conflicts
from config import get_settings
from tools.builtins.google.calendar_tools import (
    GOOGLE_CALENDAR_CREATE_EVENT,
    GOOGLE_CALENDAR_QUICK_ADD_EVENT,
)
from tools.verification import VERDICT_FAIL, VERDICT_PASS, EvidenceSnippet


class TimezoneParseTests(unittest.TestCase):
    def test_parse_event_time_applies_nested_time_zone(self) -> None:
        from agent.tool_checker_evidence import _parse_event_time

        parsed = _parse_event_time(
            {"datetime": "2026-07-09T15:00:00", "time_zone": "Asia/Tashkent"},
            None,
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.isoformat(), "2026-07-09T15:00:00+05:00")

    def test_datetimes_overlap_across_naive_and_aware(self) -> None:
        from agent.tool_checker_evidence import datetimes_overlap
        from datetime import datetime
        from zoneinfo import ZoneInfo

        slot_start = datetime(2026, 7, 9, 15, 0, tzinfo=ZoneInfo("Asia/Tashkent"))
        slot_end = datetime(2026, 7, 9, 16, 0, tzinfo=ZoneInfo("Asia/Tashkent"))
        event_start = datetime.fromisoformat("2026-07-09T14:30:00+05:00")
        event_end = datetime.fromisoformat("2026-07-09T15:30:00+05:00")
        self.assertTrue(datetimes_overlap(event_start, event_end, slot_start, slot_end))


class WrappedToolResultTests(unittest.TestCase):
    def test_call_value_map_reads_event_from_use_tool_envelope(self) -> None:
        from agent.tool_checker_evidence import _call_value_map

        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="google.calendar.quick_add_event",
            arguments_raw={},
            arguments_normalized={"text": "Встреча завтра в 15:00"},
            result_ok=True,
            result_json=json.dumps(
                {
                    "tool_name": "google.calendar.quick_add_event",
                    "ok": True,
                    "cached": False,
                    "result": {
                        "created": True,
                        "event": {
                            "id": "evt_abc",
                            "summary": "Встреча",
                            "start": "2026-07-08T15:00:00+05:00",
                            "end": "2026-07-08T16:00:00+05:00",
                        },
                    },
                }
            ),
        )
        values = _call_value_map(step)
        self.assertIn("start", values)
        self.assertIn("end", values)


class LiveSlotConflictRuleTests(unittest.TestCase):
    def test_no_conflicts_is_pass(self) -> None:
        snippet = EvidenceSnippet(
            label="slot_conflicts_live",
            kind="live_fetch",
            turn=None,
            tool_name="google.calendar.list_events",
            content=json.dumps(
                {
                    "fetch_ok": True,
                    "conflicting_events": [],
                    "conflict_count": 0,
                }
            ),
        )
        verdict = rule_verdict_for_slot_conflicts(
            question_id="slot_not_busy",
            severity="critical",
            snippet=snippet,
        )
        self.assertIsNotNone(verdict)
        assert verdict is not None
        self.assertEqual(verdict.verdict, VERDICT_PASS)

    def test_conflicts_is_fail(self) -> None:
        snippet = EvidenceSnippet(
            label="slot_conflicts_live",
            kind="live_fetch",
            turn=None,
            tool_name="google.calendar.list_events",
            content=json.dumps(
                {
                    "fetch_ok": True,
                    "conflicting_events": [{"id": "other", "summary": "Busy meeting"}],
                }
            ),
        )
        verdict = rule_verdict_for_slot_conflicts(
            question_id="slot_not_busy",
            severity="critical",
            snippet=snippet,
        )
        self.assertIsNotNone(verdict)
        assert verdict is not None
        self.assertEqual(verdict.verdict, VERDICT_FAIL)


class ToolCheckerLiveIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_without_prior_freebusy_can_pass_with_live_fetch(self) -> None:
        settings = replace(get_settings(), agent_checker_enabled=True)
        mock_llm = AsyncMock()
        mock_llm.chat_without_reasoning = AsyncMock(
            return_value=json.dumps(
                {
                    "verdicts": [
                        {
                            "question_id": "time_matches_user",
                            "verdict": "pass",
                            "reason": "ok",
                        },
                        {
                            "question_id": "timezone_correct",
                            "verdict": "pass",
                            "reason": "ok",
                        },
                        {
                            "question_id": "calendar_correct",
                            "verdict": "pass",
                            "reason": "ok",
                        },
                        {
                            "question_id": "duration_sane",
                            "verdict": "pass",
                            "reason": "ok",
                        },
                        {
                            "question_id": "summary_present",
                            "verdict": "pass",
                            "reason": "ok",
                        },
                    ],
                    "overall": "pass",
                }
            )
        )
        runtime = AsyncMock()
        runtime.use_tool = AsyncMock(
            return_value={
                "ok": True,
                "result": {
                    "count": 1,
                    "events": [
                        {
                            "id": "evt_1",
                            "summary": "Sync",
                            "start": "2026-07-08T15:00:00+05:00",
                            "end": "2026-07-08T16:00:00+05:00",
                        },
                    ],
                },
            }
        )
        checker = ToolChecker(mock_llm, settings)
        step = ToolStep(
            turn=2,
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
            result_json=json.dumps(
                {
                    "tool_name": "google.calendar.create_event",
                    "ok": True,
                    "cached": False,
                    "result": {
                        "created": True,
                        "event": {
                            "id": "evt_1",
                            "summary": "Sync",
                            "start": "2026-07-08T15:00:00+05:00",
                            "end": "2026-07-08T16:00:00+05:00",
                        },
                    },
                }
            ),
        )
        review = await checker.review_step(
            spec=GOOGLE_CALENDAR_CREATE_EVENT,
            current_step=step,
            prior_steps=(),
            user_message="встреча завтра в 15:00",
            user_id=42,
            runtime=runtime,
        )
        slot = next(item for item in review.verdicts if item.question_id == "slot_not_busy")
        self.assertEqual(slot.verdict, VERDICT_PASS)
        self.assertTrue(slot.rule_based)

    async def test_overlap_detected_as_fail(self) -> None:
        settings = replace(get_settings(), agent_checker_enabled=True)
        mock_llm = AsyncMock()
        mock_llm.chat_without_reasoning = AsyncMock(
            return_value=json.dumps({"verdicts": [], "overall": "fail"})
        )
        runtime = AsyncMock()
        runtime.use_tool = AsyncMock(
            return_value={
                "ok": True,
                "result": {
                    "count": 2,
                    "events": [
                        {
                            "id": "evt_new",
                            "summary": "New",
                            "start": "2026-07-08T15:00:00+05:00",
                            "end": "2026-07-08T16:00:00+05:00",
                        },
                        {
                            "id": "evt_old",
                            "summary": "Existing",
                            "start": "2026-07-08T14:30:00+05:00",
                            "end": "2026-07-08T15:30:00+05:00",
                        },
                    ],
                },
            }
        )
        checker = ToolChecker(mock_llm, settings)
        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="google.calendar.quick_add_event",
            arguments_raw={},
            arguments_normalized={"text": "Встреча завтра в 15:00"},
            result_ok=True,
            result_json=json.dumps(
                {
                    "tool_name": "google.calendar.quick_add_event",
                    "ok": True,
                    "result": {
                        "created": True,
                        "event": {
                            "id": "evt_new",
                            "start": "2026-07-08T15:00:00+05:00",
                            "end": "2026-07-08T16:00:00+05:00",
                        },
                    },
                }
            ),
        )
        review = await checker.review_step(
            spec=GOOGLE_CALENDAR_QUICK_ADD_EVENT,
            current_step=step,
            prior_steps=(),
            user_message="встреча завтра 15",
            user_id=42,
            runtime=runtime,
        )
        slot = next(item for item in review.verdicts if item.question_id == "slot_not_busy")
        self.assertEqual(slot.verdict, VERDICT_FAIL)
        self.assertIn("Existing", slot.reason)


    async def test_create_event_naive_args_do_not_crash_checker(self) -> None:
        settings = replace(get_settings(), agent_checker_enabled=True)
        mock_llm = AsyncMock()
        mock_llm.chat_without_reasoning = AsyncMock(
            return_value=json.dumps({"verdicts": [], "overall": "pass"})
        )
        runtime = AsyncMock()
        runtime.use_tool = AsyncMock(
            return_value={
                "ok": True,
                "result": {
                    "count": 1,
                    "events": [
                        {
                            "id": "evt_1",
                            "summary": "Встреча",
                            "start": "2026-07-09T15:00:00+05:00",
                            "end": "2026-07-09T16:00:00+05:00",
                        },
                    ],
                },
            }
        )
        checker = ToolChecker(mock_llm, settings)
        step = ToolStep(
            turn=4,
            meta_tool="use_tool",
            target_tool="google.calendar.create_event",
            arguments_raw={},
            arguments_normalized={
                "summary": "Встреча",
                "start": {"datetime": "2026-07-09T15:00:00", "time_zone": "Asia/Tashkent"},
                "end": {"datetime": "2026-07-09T16:00:00", "time_zone": "Asia/Tashkent"},
            },
            result_ok=True,
            result_json=json.dumps(
                {
                    "tool_name": "google.calendar.create_event",
                    "ok": True,
                    "result": {
                        "created": True,
                        "event": {
                            "id": "evt_1",
                            "start": "2026-07-09T15:00:00+05:00",
                            "end": "2026-07-09T16:00:00+05:00",
                        },
                    },
                }
            ),
        )
        review = await checker.review_step(
            spec=GOOGLE_CALENDAR_CREATE_EVENT,
            current_step=step,
            prior_steps=(),
            user_message="создай на завтра встречу в 15",
            user_id=42,
            runtime=runtime,
        )
        slot = next(item for item in review.verdicts if item.question_id == "slot_not_busy")
        self.assertEqual(slot.verdict, VERDICT_PASS)


if __name__ == "__main__":
    unittest.main()
