import json
import unittest

from config import get_settings
from skills.auto_load import (
    auto_load_skills_for_run,
    decide_auto_load_skill_ids,
    distinct_tools_by_skill_from_history,
    extract_tool_names_from_history,
    mark_skills_loaded_from_history,
    maybe_auto_load_after_tool,
    queue_skill_load,
    should_auto_load_skill,
)
from skills.pending import is_skill_loaded, reset_skill_run_state, take_pending_skills
from skills.usage_tracker import record_tool_use, reset_skill_usage_tracker


def _use_tool_history(*tool_names: str) -> list[dict]:
    messages: list[dict] = []
    for index, tool_name in enumerate(tool_names, start=1):
        call_id = f"u{index}"
        messages.extend(
            [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "use_tool",
                                "arguments": json.dumps(
                                    {"tool_name": tool_name, "arguments": {}},
                                ),
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps({"ok": True, "tool_name": tool_name, "result": {}}),
                },
            ]
        )
    return messages


class SkillsAutoLoadTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_skill_run_state()
        reset_skill_usage_tracker()

    def test_single_keyword_does_not_load(self) -> None:
        ids = decide_auto_load_skill_ids("Покажи непрочитанные в почте", None)
        self.assertEqual(ids, [])

    def test_two_distinct_history_tools_does_not_load_when_threshold_is_three(self) -> None:
        history = _use_tool_history(
            "google.gmail.list_inbox",
            "google.gmail.get_message",
        )
        ids = decide_auto_load_skill_ids(
            "Покажи полный список непрочитанных писем за неделю",
            history,
        )
        self.assertEqual(ids, [])

    def test_three_distinct_history_tools_load_gmail(self) -> None:
        history = _use_tool_history(
            "google.gmail.list_inbox",
            "google.gmail.get_message",
            "google.gmail.reply_to_message",
        )
        ids = decide_auto_load_skill_ids("ещё одно", history)
        self.assertIn("google.gmail", ids)

    def test_one_history_tool_plus_follow_up_loads(self) -> None:
        history = _use_tool_history("google.calendar.list_today")
        ids = decide_auto_load_skill_ids("а завтра?", history)
        self.assertIn("google.calendar", ids)

    def test_one_history_tool_without_follow_up_does_not_load(self) -> None:
        history = _use_tool_history("google.calendar.list_today")
        ids = decide_auto_load_skill_ids("Покажи полный календарь на неделю вперёд", history)
        self.assertEqual(ids, [])

    def test_third_distinct_tool_in_run_triggers_auto_load(self) -> None:
        record_tool_use("google.drive.search_files")
        record_tool_use("google.drive.get_file")
        self.assertIsNone(
            maybe_auto_load_after_tool("google.drive.get_file", history=None)
        )
        record_tool_use("google.drive.download_file")
        loaded = maybe_auto_load_after_tool("google.drive.download_file", history=None)
        self.assertEqual(loaded, "google.drive")
        self.assertTrue(is_skill_loaded("google.drive"))

    def test_same_tool_twice_does_not_auto_load(self) -> None:
        record_tool_use("google.tasks.list_today")
        record_tool_use("google.tasks.list_today")
        self.assertFalse(
            should_auto_load_skill("google.tasks", history=None, user_message="")
        )

    def test_history_skill_marker_prevents_reload(self) -> None:
        history = [
            {
                "role": "user",
                "content": "[Skill loaded: google.maps]\n\n# maps skill body",
            }
        ]
        mark_skills_loaded_from_history(history)
        loaded = auto_load_skills_for_run("маршрут до офиса", history)
        self.assertEqual(loaded, [])
        self.assertEqual(take_pending_skills(), [])

    def test_distinct_tools_by_skill(self) -> None:
        history = _use_tool_history(
            "google.sheets.get_values",
            "google.sheets.update_values",
        )
        by_skill = distinct_tools_by_skill_from_history(history)
        self.assertEqual(len(by_skill["google.sheets"]), 2)

    def test_threshold_from_config(self) -> None:
        self.assertEqual(get_settings().skills_auto_load_distinct_tools, 3)

    def test_queue_skill_load_idempotent(self) -> None:
        self.assertTrue(queue_skill_load("google.tasks"))
        self.assertFalse(queue_skill_load("google.tasks"))


if __name__ == "__main__":
    unittest.main()
