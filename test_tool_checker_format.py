import unittest

from agent.tool_checker import ToolCheckerReview
from agent.tool_checker_format import (
    critical_failures,
    format_checker_hint,
    format_checker_hint_message,
    should_inject_checker_hint,
    user_prefers_russian,
)
from tools.verification import SEVERITY_CRITICAL, SEVERITY_WARN, QuestionVerdict, VERDICT_FAIL, VERDICT_PASS


def _review(*verdicts: QuestionVerdict) -> ToolCheckerReview:
    return ToolCheckerReview(
        tool_name="google.calendar.create_event",
        turn=2,
        step_index=1,
        overall="fail",
        verdicts=list(verdicts),
    )


class ToolCheckerFormatTests(unittest.TestCase):
    def test_should_inject_on_critical_fail_only(self) -> None:
        critical = _review(
            QuestionVerdict(
                question_id="slot_not_busy",
                verdict=VERDICT_FAIL,
                severity=SEVERITY_CRITICAL,
                reason="Overlapping events",
            )
        )
        warn_only = _review(
            QuestionVerdict(
                question_id="calendar_correct",
                verdict=VERDICT_FAIL,
                severity=SEVERITY_WARN,
                reason="Maybe wrong calendar",
            )
        )
        passed = _review(
            QuestionVerdict(
                question_id="slot_not_busy",
                verdict=VERDICT_PASS,
                severity=SEVERITY_CRITICAL,
                reason="ok",
            )
        )
        self.assertTrue(should_inject_checker_hint(critical))
        self.assertFalse(should_inject_checker_hint(warn_only))
        self.assertFalse(should_inject_checker_hint(passed))

    def test_format_checker_hint_russian(self) -> None:
        review = _review(
            QuestionVerdict(
                question_id="slot_not_busy",
                verdict=VERDICT_FAIL,
                severity=SEVERITY_CRITICAL,
                reason="Overlapping events in slot: Busy meeting",
            )
        )
        text = format_checker_hint(review, user_message="создай встречу завтра в 15")
        self.assertIn("tool checker", text)
        self.assertIn("slot_not_busy", text)
        self.assertIn("Overlapping events", text)
        self.assertIn("Не сообщай пользователю", text)

    def test_format_checker_hint_english(self) -> None:
        review = _review(
            QuestionVerdict(
                question_id="slot_not_busy",
                verdict=VERDICT_FAIL,
                severity=SEVERITY_CRITICAL,
                reason="Slot busy",
            )
        )
        text = format_checker_hint(review, user_message="create meeting tomorrow at 3pm")
        self.assertIn("Do not mention this review", text)
        self.assertNotIn("Не сообщай", text)

    def test_format_checker_hint_message_shape(self) -> None:
        review = _review(
            QuestionVerdict(
                question_id="slot_not_busy",
                verdict=VERDICT_FAIL,
                severity=SEVERITY_CRITICAL,
                reason="busy",
            )
        )
        message = format_checker_hint_message(review, user_message="встреча")
        self.assertEqual(message["role"], "user")
        self.assertIn("slot_not_busy", message["content"])

    def test_user_prefers_russian(self) -> None:
        self.assertTrue(user_prefers_russian("создай встречу"))
        self.assertFalse(user_prefers_russian("create meeting"))

    def test_critical_failures_filters_empty_reason(self) -> None:
        review = _review(
            QuestionVerdict(
                question_id="slot_not_busy",
                verdict=VERDICT_FAIL,
                severity=SEVERITY_CRITICAL,
                reason="",
            )
        )
        self.assertEqual(critical_failures(review), [])


if __name__ == "__main__":
    unittest.main()
