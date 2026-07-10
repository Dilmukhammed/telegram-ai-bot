import json
import unittest
from dataclasses import replace

from agent.run_trace import ToolStep
from agent.tool_checker import should_run_tool_checker
from config import get_settings
from tools.builtins.google.tasks_checker import (
    GOOGLE_TASKS_CREATE_TASK_QUESTIONS,
    GOOGLE_TASKS_DELETE_TASKLIST_QUESTIONS,
    GOOGLE_TASKS_DELETE_TASK_QUESTIONS,
    GOOGLE_TASKS_PATCH_TASK_QUESTIONS,
    GOOGLE_TASKS_UPDATE_TASK_QUESTIONS,
    TASKS_CHECKER_ALL_TOOL_NAMES,
    TASKS_CHECKER_QUESTIONS_BY_TOOL,
    TASKS_CHECKER_READ_TOOL_NAMES,
    TASKS_CHECKER_WRITE_TOOL_NAMES,
)
from tools.builtins.google.tasks_tools import GOOGLE_TASKS_TOOLS
from tools.checker.registry import get_checker_questions
from tools.verification import EVIDENCE_LIVE_FETCH


class TasksCheckerPackTests(unittest.TestCase):
    def test_all_24_tasks_tools_have_handcrafted_questions(self) -> None:
        tools_by_name = {tool.name: tool for tool in GOOGLE_TASKS_TOOLS}
        self.assertEqual(len(TASKS_CHECKER_ALL_TOOL_NAMES), 24)
        self.assertEqual(len(GOOGLE_TASKS_TOOLS), 24)
        for name in TASKS_CHECKER_ALL_TOOL_NAMES:
            self.assertIn(name, tools_by_name, msg=name)
            questions = get_checker_questions(tools_by_name[name])
            self.assertGreaterEqual(len(questions), 1, msg=name)
            self.assertEqual(questions, TASKS_CHECKER_QUESTIONS_BY_TOOL[name], msg=name)

    def test_read_write_partitions(self) -> None:
        self.assertEqual(
            set(TASKS_CHECKER_READ_TOOL_NAMES) | set(TASKS_CHECKER_WRITE_TOOL_NAMES),
            set(TASKS_CHECKER_ALL_TOOL_NAMES),
        )
        self.assertEqual(len(TASKS_CHECKER_READ_TOOL_NAMES), 11)
        self.assertEqual(len(TASKS_CHECKER_WRITE_TOOL_NAMES), 13)

    def test_create_task_has_live_fetch(self) -> None:
        fetches = {
            ref.fetch
            for q in GOOGLE_TASKS_CREATE_TASK_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertIn("tasks_get_task", fetches)

    def test_patch_task_has_live_fetch(self) -> None:
        fetches = {
            ref.fetch
            for q in GOOGLE_TASKS_PATCH_TASK_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertIn("tasks_get_task", fetches)

    def test_delete_tasklist_requires_confirm(self) -> None:
        self.assertIn("confirm_explicit", {q.id for q in GOOGLE_TASKS_DELETE_TASKLIST_QUESTIONS})

    def test_delete_task_no_live_fetch(self) -> None:
        fetches = {
            ref.fetch
            for q in GOOGLE_TASKS_DELETE_TASK_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertEqual(fetches, set())

    def test_update_vs_patch_questions(self) -> None:
        self.assertIn("full_replace_intended", {q.id for q in GOOGLE_TASKS_UPDATE_TASK_QUESTIONS})
        self.assertIn("partial_fields_match", {q.id for q in GOOGLE_TASKS_PATCH_TASK_QUESTIONS})

    def test_allowlist_glob_matches_tasks(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="google.tasks.*",
        )
        tool = next(t for t in GOOGLE_TASKS_TOOLS if t.name == "google.tasks.create_task")
        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="google.tasks.create_task",
            arguments_raw={},
            arguments_normalized={"title": "buy milk"},
            result_ok=True,
            result_json=json.dumps(
                {"tasklist_id": "tl1", "task": {"id": "t1", "title": "buy milk"}}
            ),
        )
        self.assertTrue(should_run_tool_checker(spec=tool, step=step, settings=settings))


if __name__ == "__main__":
    unittest.main()
