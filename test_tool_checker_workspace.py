import json
import unittest
from dataclasses import replace

from agent.run_trace import ToolStep
from agent.tool_checker import should_run_tool_checker
from config import get_settings
from tools.builtins.workspace import WORKSPACE_TOOLS
from tools.builtins.workspace.workspace_checker import (
    WORKSPACE_CHECKER_ALL_TOOL_NAMES,
    WORKSPACE_CHECKER_QUESTIONS_BY_TOOL,
    WORKSPACE_CHECKER_READ_TOOL_NAMES,
    WORKSPACE_CHECKER_WRITE_TOOL_NAMES,
    WORKSPACE_CLEAR_QUESTIONS,
    WORKSPACE_DELETE_QUESTIONS,
    WORKSPACE_READ_LINES_QUESTIONS,
    WORKSPACE_WRITE_FILE_QUESTIONS,
)
from tools.checker.registry import get_checker_questions
from tools.verification import EVIDENCE_LIVE_FETCH


class WorkspaceCheckerPackTests(unittest.TestCase):
    def test_all_16_workspace_tools_have_handcrafted_questions(self) -> None:
        tools_by_name = {tool.name: tool for tool in WORKSPACE_TOOLS}
        self.assertEqual(len(WORKSPACE_CHECKER_ALL_TOOL_NAMES), 16)
        self.assertEqual(len(WORKSPACE_TOOLS), 16)
        for name in WORKSPACE_CHECKER_ALL_TOOL_NAMES:
            self.assertIn(name, tools_by_name, msg=name)
            questions = get_checker_questions(tools_by_name[name])
            self.assertGreaterEqual(len(questions), 1, msg=name)
            self.assertEqual(questions, WORKSPACE_CHECKER_QUESTIONS_BY_TOOL[name], msg=name)

    def test_read_write_partitions(self) -> None:
        self.assertEqual(
            set(WORKSPACE_CHECKER_READ_TOOL_NAMES) | set(WORKSPACE_CHECKER_WRITE_TOOL_NAMES),
            set(WORKSPACE_CHECKER_ALL_TOOL_NAMES),
        )
        self.assertEqual(len(WORKSPACE_CHECKER_READ_TOOL_NAMES), 7)
        self.assertEqual(len(WORKSPACE_CHECKER_WRITE_TOOL_NAMES), 9)

    def test_write_file_has_live_stat_fetch(self) -> None:
        fetches = {
            ref.fetch
            for q in WORKSPACE_WRITE_FILE_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertIn("workspace_stat", fetches)

    def test_delete_and_clear_require_confirm(self) -> None:
        self.assertIn("confirm_explicit", {q.id for q in WORKSPACE_DELETE_QUESTIONS})
        self.assertIn("confirm_explicit", {q.id for q in WORKSPACE_CLEAR_QUESTIONS})

    def test_delete_no_live_fetch(self) -> None:
        fetches = {
            ref.fetch
            for q in WORKSPACE_DELETE_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertEqual(fetches, set())

    def test_read_lines_range_question(self) -> None:
        self.assertIn("line_range_matches", {q.id for q in WORKSPACE_READ_LINES_QUESTIONS})

    def test_allowlist_glob_matches_workspace(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="workspace.*",
        )
        tool = next(t for t in WORKSPACE_TOOLS if t.name == "workspace.write_file")
        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="workspace.write_file",
            arguments_raw={},
            arguments_normalized={"path": "agent/notes.md", "content_text": "# hi"},
            result_ok=True,
            result_json=json.dumps({"path": "agent/notes.md", "bytes": 4}),
        )
        self.assertTrue(should_run_tool_checker(spec=tool, step=step, settings=settings))


if __name__ == "__main__":
    unittest.main()
