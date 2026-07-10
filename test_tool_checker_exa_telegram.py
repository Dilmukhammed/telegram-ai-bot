import json
import unittest
from dataclasses import replace

from agent.run_trace import ToolStep
from agent.tool_checker import should_run_tool_checker
from config import get_settings
from tools.builtins.exa_checker import (
    EXA_CHECKER_ALL_TOOL_NAMES,
    EXA_CHECKER_QUESTIONS_BY_TOOL,
    EXA_WEB_FETCH_QUESTIONS,
    EXA_WEB_SEARCH_QUESTIONS,
)
from tools.builtins.exa_fetch import EXA_WEB_FETCH
from tools.builtins.exa_search import EXA_WEB_SEARCH
from tools.builtins.telegram_checker import (
    TELEGRAM_CHECKER_ALL_TOOL_NAMES,
    TELEGRAM_CHECKER_QUESTIONS_BY_TOOL,
    TELEGRAM_SEND_FILE_QUESTIONS,
)
from tools.builtins.telegram_send import TELEGRAM_SEND_FILE
from tools.checker.registry import get_checker_questions
from tools.verification import EVIDENCE_LIVE_FETCH, FETCH_WORKSPACE_STAT


class ExaCheckerPackTests(unittest.TestCase):
    def test_both_exa_tools_have_handcrafted_questions(self) -> None:
        tools = (EXA_WEB_SEARCH, EXA_WEB_FETCH)
        self.assertEqual(len(EXA_CHECKER_ALL_TOOL_NAMES), 2)
        for tool in tools:
            questions = get_checker_questions(tool)
            self.assertGreaterEqual(len(questions), 3, msg=tool.name)
            self.assertEqual(questions, EXA_CHECKER_QUESTIONS_BY_TOOL[tool.name], msg=tool.name)

    def test_web_search_has_wrong_tool_question(self) -> None:
        self.assertIn("web_search_not_wrong_tool", {q.id for q in EXA_WEB_SEARCH_QUESTIONS})

    def test_web_search_has_timeframe_questions(self) -> None:
        question_ids = {q.id for q in EXA_WEB_SEARCH_QUESTIONS}
        self.assertIn("query_timeframe", question_ids)
        self.assertIn("results_recency", question_ids)

    def test_web_fetch_has_urls_from_trusted_source(self) -> None:
        self.assertIn("urls_from_trusted_source", {q.id for q in EXA_WEB_FETCH_QUESTIONS})

    def test_exa_tools_no_live_fetch(self) -> None:
        for name in EXA_CHECKER_ALL_TOOL_NAMES:
            fetches = {
                ref.fetch
                for q in EXA_CHECKER_QUESTIONS_BY_TOOL[name]
                for ref in q.evidence
                if ref.kind == EVIDENCE_LIVE_FETCH
            }
            self.assertEqual(fetches, set(), msg=name)

    def test_allowlist_glob_matches_exa(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="exa.*",
        )
        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="exa.web_search",
            arguments_raw={},
            arguments_normalized={"query": "latest AI news"},
            result_ok=True,
            result_json=json.dumps({"ok": True, "result": {"count": 0, "results": []}}),
        )
        self.assertTrue(should_run_tool_checker(spec=EXA_WEB_SEARCH, step=step, settings=settings))


class TelegramCheckerPackTests(unittest.TestCase):
    def test_send_file_has_handcrafted_questions(self) -> None:
        self.assertEqual(len(TELEGRAM_CHECKER_ALL_TOOL_NAMES), 1)
        questions = get_checker_questions(TELEGRAM_SEND_FILE)
        self.assertEqual(questions, TELEGRAM_CHECKER_QUESTIONS_BY_TOOL["telegram.send_file"])
        self.assertGreaterEqual(len(questions), 5)

    def test_send_file_has_path_xor_and_delivery_intent(self) -> None:
        question_ids = {q.id for q in TELEGRAM_SEND_FILE_QUESTIONS}
        self.assertIn("path_xor_file_ref", question_ids)
        self.assertIn("delivery_intent", question_ids)
        self.assertIn("file_ref_from_prior", question_ids)

    def test_send_file_path_mode_has_live_stat(self) -> None:
        fetches = {
            ref.fetch
            for q in TELEGRAM_SEND_FILE_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertEqual(fetches, {FETCH_WORKSPACE_STAT})

    def test_allowlist_matches_telegram_send_file(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="telegram.send_file",
        )
        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="telegram.send_file",
            arguments_raw={},
            arguments_normalized={"file_ref": "run:abc123"},
            result_ok=True,
            result_json=json.dumps({"ok": True, "result": {"queued": True}}),
        )
        self.assertTrue(should_run_tool_checker(spec=TELEGRAM_SEND_FILE, step=step, settings=settings))


if __name__ == "__main__":
    unittest.main()
