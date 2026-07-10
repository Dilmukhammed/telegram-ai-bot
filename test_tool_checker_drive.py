import json
import unittest
from dataclasses import replace

from agent.run_trace import ToolStep
from agent.tool_checker import should_run_tool_checker
from config import get_settings
from tools.builtins.google.drive_checker import (
    DRIVE_CHECKER_ALL_TOOL_NAMES,
    DRIVE_CHECKER_QUESTIONS_BY_TOOL,
    DRIVE_CHECKER_READ_TOOL_NAMES,
    DRIVE_CHECKER_WRITE_TOOL_NAMES,
    GOOGLE_DRIVE_DELETE_FILE_QUESTIONS,
    GOOGLE_DRIVE_MOVE_FILE_QUESTIONS,
    GOOGLE_DRIVE_SHARE_FILE_QUESTIONS,
    GOOGLE_DRIVE_TRASH_FILE_QUESTIONS,
)
from tools.builtins.google.drive_tools import GOOGLE_DRIVE_TOOLS
from tools.checker.registry import get_checker_questions
from tools.verification import EVIDENCE_LIVE_FETCH


class DriveCheckerPackTests(unittest.TestCase):
    def test_all_70_drive_tools_have_handcrafted_questions(self) -> None:
        tools_by_name = {tool.name: tool for tool in GOOGLE_DRIVE_TOOLS}
        self.assertEqual(len(DRIVE_CHECKER_ALL_TOOL_NAMES), 70)
        self.assertEqual(len(GOOGLE_DRIVE_TOOLS), 70)
        for name in DRIVE_CHECKER_ALL_TOOL_NAMES:
            self.assertIn(name, tools_by_name, msg=name)
            questions = get_checker_questions(tools_by_name[name])
            self.assertGreaterEqual(len(questions), 1, msg=name)
            self.assertEqual(questions, DRIVE_CHECKER_QUESTIONS_BY_TOOL[name], msg=name)

    def test_read_write_partitions(self) -> None:
        self.assertEqual(
            set(DRIVE_CHECKER_READ_TOOL_NAMES) | set(DRIVE_CHECKER_WRITE_TOOL_NAMES),
            set(DRIVE_CHECKER_ALL_TOOL_NAMES),
        )
        self.assertEqual(len(DRIVE_CHECKER_READ_TOOL_NAMES), 30)
        self.assertEqual(len(DRIVE_CHECKER_WRITE_TOOL_NAMES), 40)

    def test_share_file_has_live_drive_fetch(self) -> None:
        fetches = {
            ref.fetch
            for q in GOOGLE_DRIVE_SHARE_FILE_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertIn("drive_file", fetches)

    def test_move_file_has_live_drive_fetch(self) -> None:
        fetches = {
            ref.fetch
            for q in GOOGLE_DRIVE_MOVE_FILE_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertIn("drive_file", fetches)

    def test_delete_file_requires_confirm(self) -> None:
        self.assertIn("confirm_explicit", {q.id for q in GOOGLE_DRIVE_DELETE_FILE_QUESTIONS})

    def test_trash_vs_delete_questions(self) -> None:
        self.assertIn("trash_not_permanent", {q.id for q in GOOGLE_DRIVE_TRASH_FILE_QUESTIONS})
        self.assertIn("permanent_not_trash", {q.id for q in GOOGLE_DRIVE_DELETE_FILE_QUESTIONS})

    def test_allowlist_glob_matches_drive(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="google.drive.*",
        )
        tool = next(t for t in GOOGLE_DRIVE_TOOLS if t.name == "google.drive.share_file")
        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="google.drive.share_file",
            arguments_raw={},
            arguments_normalized={
                "file_id": "f1",
                "role": "reader",
                "type": "user",
                "email": "a@b.com",
            },
            result_ok=True,
            result_json=json.dumps({"permission_id": "p1"}),
        )
        self.assertTrue(should_run_tool_checker(spec=tool, step=step, settings=settings))


if __name__ == "__main__":
    unittest.main()
