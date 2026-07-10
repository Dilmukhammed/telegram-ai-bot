import json
import unittest

from agent.run_trace import ToolStep
from agent.tool_checker_evidence import EvidenceResolver
from tools.builtins.google.calendar_checker import GOOGLE_CALENDAR_CREATE_EVENT_QUESTIONS
from tools.builtins.google.calendar_tools import GOOGLE_CALENDAR_CREATE_EVENT
from tools.verification import CheckerRuntimeContext, EvidenceSnippet


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


class EvidenceResolverCalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = EvidenceResolver()

    def test_create_event_tool_has_questions(self) -> None:
        self.assertEqual(
            GOOGLE_CALENDAR_CREATE_EVENT.verification_questions,
            GOOGLE_CALENDAR_CREATE_EVENT_QUESTIONS,
        )

    def test_live_slot_snippet_attached_without_trace_freebusy(self) -> None:
        create = _use_step(
            turn=2,
            tool_name="google.calendar.create_event",
            arguments={
                "calendar_id": "primary",
                "summary": "Sync",
                "start": {"datetime": "2026-07-08T15:00:00+05:00"},
                "end": {"datetime": "2026-07-08T16:00:00+05:00"},
            },
            result={"created": True, "event": {"id": "evt_1"}},
        )
        live_snippets = {
            "slot_conflicts_live": EvidenceSnippet(
                label="slot_conflicts_live",
                kind="live_fetch",
                turn=None,
                tool_name="google.calendar.list_events",
                content='{"fetch_ok":true,"conflicting_events":[]}',
            )
        }
        bundle = self.resolver.resolve_bundle(
            questions=GOOGLE_CALENDAR_CREATE_EVENT_QUESTIONS,
            current_step=create,
            prior_steps=(),
            runtime=CheckerRuntimeContext(bot_timezone="Asia/Tashkent"),
            user_message="meeting tomorrow 3pm",
            live_snippets=live_snippets,
        )
        slot_question = next(item for item in bundle.questions if item.question.id == "slot_not_busy")
        labels = {snippet.label for snippet in slot_question.snippets}
        self.assertIn("slot_conflicts_live", labels)
        self.assertIn("create_event_call", labels)
        self.assertEqual(slot_question.missing_required, [])
        self.assertEqual(bundle.rule_based_verdicts(), [])

    def test_timezone_question_gets_runtime_context(self) -> None:
        create = _use_step(
            turn=0,
            tool_name="google.calendar.create_event",
            arguments={
                "calendar_id": "primary",
                "summary": "Sync",
                "start": {"datetime": "2026-07-08T15:00:00+05:00"},
                "end": {"datetime": "2026-07-08T16:00:00+05:00"},
                "time_zone": "Asia/Tashkent",
            },
            result={"created": True},
        )
        bundle = self.resolver.resolve_bundle(
            questions=GOOGLE_CALENDAR_CREATE_EVENT_QUESTIONS,
            current_step=create,
            prior_steps=(),
            runtime=CheckerRuntimeContext(bot_timezone="Asia/Tashkent"),
            user_message="meeting",
        )
        tz_question = next(item for item in bundle.questions if item.question.id == "timezone_correct")
        labels = {snippet.label for snippet in tz_question.snippets}
        self.assertIn("runtime_context", labels)
        self.assertIn("create_event_call", labels)


if __name__ == "__main__":
    unittest.main()
