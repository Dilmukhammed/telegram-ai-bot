import json
import unittest
from dataclasses import replace

from agent.run_trace import ToolStep
from agent.tool_checker import should_run_tool_checker
from config import get_settings
from tools.builtins.google.sheets_checker import (
    GOOGLE_SHEETS_DELETE_DIMENSION_QUESTIONS,
    GOOGLE_SHEETS_FIND_REPLACE_QUESTIONS,
    GOOGLE_SHEETS_UPDATE_VALUES_QUESTIONS,
    SHEETS_CHECKER_ALL_TOOL_NAMES,
    SHEETS_CHECKER_QUESTIONS_BY_TOOL,
    SHEETS_CHECKER_READ_TOOL_NAMES,
    SHEETS_CHECKER_WRITE_TOOL_NAMES,
)
from tools.builtins.google.sheets_tools import GOOGLE_SHEETS_TOOLS
from tools.checker.registry import get_checker_questions
from tools.verification import EVIDENCE_LIVE_FETCH


class SheetsCheckerPackTests(unittest.TestCase):
    def test_all_43_sheets_tools_have_handcrafted_questions(self) -> None:
        tools_by_name = {tool.name: tool for tool in GOOGLE_SHEETS_TOOLS}
        self.assertEqual(len(SHEETS_CHECKER_ALL_TOOL_NAMES), 43)
        self.assertEqual(len(GOOGLE_SHEETS_TOOLS), 43)
        for name in SHEETS_CHECKER_ALL_TOOL_NAMES:
            self.assertIn(name, tools_by_name, msg=name)
            questions = get_checker_questions(tools_by_name[name])
            self.assertGreaterEqual(len(questions), 1, msg=name)
            self.assertEqual(questions, SHEETS_CHECKER_QUESTIONS_BY_TOOL[name], msg=name)

    def test_read_write_partitions(self) -> None:
        self.assertEqual(
            set(SHEETS_CHECKER_READ_TOOL_NAMES) | set(SHEETS_CHECKER_WRITE_TOOL_NAMES),
            set(SHEETS_CHECKER_ALL_TOOL_NAMES),
        )
        self.assertEqual(len(SHEETS_CHECKER_READ_TOOL_NAMES), 4)
        self.assertEqual(len(SHEETS_CHECKER_WRITE_TOOL_NAMES), 39)

    def test_update_values_has_live_range_fetch(self) -> None:
        fetches = {
            ref.fetch
            for q in GOOGLE_SHEETS_UPDATE_VALUES_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertIn("sheets_range_values", fetches)

    def test_delete_dimension_requires_confirm(self) -> None:
        self.assertIn("confirm_explicit", {q.id for q in GOOGLE_SHEETS_DELETE_DIMENSION_QUESTIONS})

    def test_find_replace_scope_question(self) -> None:
        self.assertIn("scope_not_too_broad", {q.id for q in GOOGLE_SHEETS_FIND_REPLACE_QUESTIONS})

    def test_clear_vs_delete_sheet_questions(self) -> None:
        clear = SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.clear_values"]
        delete_sheet = SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.delete_sheet"]
        self.assertIn("clear_not_delete_structure", {q.id for q in clear})
        self.assertIn("confirm_explicit", {q.id for q in delete_sheet})

    def test_allowlist_glob_matches_sheets(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="google.sheets.*",
        )
        tool = next(t for t in GOOGLE_SHEETS_TOOLS if t.name == "google.sheets.update_values")
        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="google.sheets.update_values",
            arguments_raw={},
            arguments_normalized={
                "spreadsheet_id": "s1",
                "range": "Sheet1!A1",
                "values": [[1]],
            },
            result_ok=True,
            result_json=json.dumps({"updated_cells": 1}),
        )
        self.assertTrue(should_run_tool_checker(spec=tool, step=step, settings=settings))


if __name__ == "__main__":
    unittest.main()
