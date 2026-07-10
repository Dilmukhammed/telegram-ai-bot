import json
import unittest
from dataclasses import replace

from agent.run_trace import ToolStep
from agent.tool_checker import should_run_tool_checker
from agent.tool_checker_evidence import EvidenceResolver
from config import get_settings
from tools.builtins.google.gmail_checker import (
    GMAIL_CHECKER_ALL_TOOL_NAMES,
    GMAIL_CHECKER_QUESTIONS_BY_TOOL,
    GMAIL_CHECKER_READ_TOOL_NAMES,
    GMAIL_CHECKER_WRITE_TOOL_NAMES,
    GOOGLE_GMAIL_DELETE_MESSAGE_QUESTIONS,
    GOOGLE_GMAIL_REPLY_TO_MESSAGE_QUESTIONS,
    GOOGLE_GMAIL_SEND_MESSAGE_QUESTIONS,
)
from tools.builtins.google.gmail_tools import GOOGLE_GMAIL_TOOLS
from tools.checker.registry import get_checker_questions
from tools.verification import EVIDENCE_LIVE_FETCH, EVIDENCE_PRIOR_TOOL


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


class GmailCheckerPackTests(unittest.TestCase):
    def test_all_45_gmail_tools_have_handcrafted_questions(self) -> None:
        tools_by_name = {tool.name: tool for tool in GOOGLE_GMAIL_TOOLS}
        self.assertEqual(len(GMAIL_CHECKER_ALL_TOOL_NAMES), 45)
        self.assertEqual(len(GOOGLE_GMAIL_TOOLS), 45)
        for name in GMAIL_CHECKER_ALL_TOOL_NAMES:
            self.assertIn(name, tools_by_name, msg=name)
            questions = get_checker_questions(tools_by_name[name])
            self.assertGreaterEqual(len(questions), 1, msg=name)
            self.assertEqual(questions, GMAIL_CHECKER_QUESTIONS_BY_TOOL[name], msg=name)

    def test_read_write_partitions(self) -> None:
        self.assertEqual(
            set(GMAIL_CHECKER_READ_TOOL_NAMES) | set(GMAIL_CHECKER_WRITE_TOOL_NAMES),
            set(GMAIL_CHECKER_ALL_TOOL_NAMES),
        )
        self.assertEqual(len(GMAIL_CHECKER_READ_TOOL_NAMES), 18)
        self.assertEqual(len(GMAIL_CHECKER_WRITE_TOOL_NAMES), 27)

    def test_send_has_live_sent_fetch(self) -> None:
        fetches = {
            ref.fetch
            for q in GOOGLE_GMAIL_SEND_MESSAGE_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertIn("gmail_sent_message", fetches)

    def test_reply_has_source_and_sent_live(self) -> None:
        fetches = {
            ref.fetch
            for q in GOOGLE_GMAIL_REPLY_TO_MESSAGE_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertIn("gmail_message", fetches)
        self.assertIn("gmail_sent_message", fetches)

    def test_permanent_delete_no_live_fetch(self) -> None:
        fetches = {
            ref.fetch
            for q in GOOGLE_GMAIL_DELETE_MESSAGE_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertEqual(fetches, set())
        self.assertIn("confirm_explicit", {q.id for q in GOOGLE_GMAIL_DELETE_MESSAGE_QUESTIONS})

    def test_reply_resolves_prior_get_message(self) -> None:
        resolver = EvidenceResolver()
        prior = _use_step(
            turn=1,
            tool_name="google.gmail.get_message",
            arguments={"message_id": "msg_abc"},
            result={"message": {"id": "msg_abc", "subject": "Budget"}},
        )
        reply = _use_step(
            turn=2,
            tool_name="google.gmail.reply_to_message",
            arguments={"message_id": "msg_abc", "body_text": "Thanks"},
            result={"sent": True, "message_id": "msg_new"},
        )
        bundle = resolver.resolve_bundle(
            questions=GOOGLE_GMAIL_REPLY_TO_MESSAGE_QUESTIONS,
            current_step=reply,
            prior_steps=(prior,),
            runtime=__import__(
                "tools.verification", fromlist=["CheckerRuntimeContext"]
            ).CheckerRuntimeContext(bot_timezone="Asia/Tashkent"),
            user_message="ответь на письмо про бюджет",
        )
        thread_q = next(item for item in bundle.questions if item.question.id == "correct_message_thread")
        labels = {snippet.label for snippet in thread_q.snippets}
        self.assertIn("prior_message_in_trace", labels)

    def test_allowlist_glob_matches_gmail(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="google.gmail.*",
        )
        tool = next(t for t in GOOGLE_GMAIL_TOOLS if t.name == "google.gmail.send_message")
        step = _use_step(
            turn=1,
            tool_name="google.gmail.send_message",
            arguments={"to": ["a@b.com"], "subject": "x", "body_text": "y"},
            result={"sent": True, "message_id": "msg_out"},
        )
        self.assertTrue(should_run_tool_checker(spec=tool, step=step, settings=settings))

    def test_trash_vs_delete_questions_differ(self) -> None:
        trash = GMAIL_CHECKER_QUESTIONS_BY_TOOL["google.gmail.trash_message"]
        delete = GMAIL_CHECKER_QUESTIONS_BY_TOOL["google.gmail.delete_message"]
        self.assertIn("trash_not_permanent_delete", {q.id for q in trash})
        self.assertIn("permanent_not_trash", {q.id for q in delete})


if __name__ == "__main__":
    unittest.main()
