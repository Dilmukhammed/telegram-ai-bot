from __future__ import annotations

import unittest

from skills.auto_load import (
    maybe_auto_load_after_tool,
    prepare_skills_for_run,
    should_auto_load_skill,
)
from skills.collapse import SKILL_LOADED_PREFIX, parse_expanded_skill_id
from skills.pending import is_skill_loaded, reset_skill_run_state
from skills.registry import get_skill
from skills.usage_tracker import record_tool_use, reset_skill_usage_tracker


def _loaded_skill_message(skill_id: str) -> dict:
    spec = get_skill(skill_id)
    assert spec is not None
    return {
        "role": "user",
        "content": f"[Skill loaded: {skill_id}]\n\n{spec.content}",
    }


class SkillsAutoLoadTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_skill_run_state()
        reset_skill_usage_tracker()

    def test_prepare_skills_marks_expanded_history(self) -> None:
        history = [_loaded_skill_message("google.drive")]
        prepare_skills_for_run(history)
        self.assertTrue(is_skill_loaded("google.drive"))

    def test_should_auto_load_counts_current_run_only(self) -> None:
        record_tool_use("google.calendar.create_event")
        record_tool_use("google.calendar.list_today")
        self.assertFalse(should_auto_load_skill("google.calendar"))
        record_tool_use("google.calendar.list_events")
        self.assertTrue(should_auto_load_skill("google.calendar"))

    def test_maybe_auto_load_skips_when_already_in_history(self) -> None:
        prepare_skills_for_run([_loaded_skill_message("google.drive")])
        record_tool_use("google.drive.search_files")
        record_tool_use("google.drive.export_file")
        record_tool_use("google.drive.list_recent")
        self.assertIsNone(maybe_auto_load_after_tool("google.drive.list_recent"))

    def test_maybe_auto_load_after_tool_requires_run_threshold(self) -> None:
        record_tool_use("google.drive.search_files")
        self.assertIsNone(maybe_auto_load_after_tool("google.drive.search_files"))
        record_tool_use("google.drive.export_file")
        record_tool_use("google.drive.list_recent")
        loaded = maybe_auto_load_after_tool("google.drive.list_recent")
        self.assertEqual(loaded, "google.drive")

    def test_yandex_auth_tools_count_toward_music_skill(self) -> None:
        record_tool_use("yandex.auth.status")
        record_tool_use("yandex.auth.connect_start")
        self.assertFalse(should_auto_load_skill("yandex.music"))
        record_tool_use("yandex.music.search")
        loaded = maybe_auto_load_after_tool("yandex.music.search")
        self.assertEqual(loaded, "yandex.music")


class SkillsPersistTests(unittest.TestCase):
    def test_expanded_skill_parsed_from_history(self) -> None:
        message = _loaded_skill_message("google.gmail")
        content = message["content"]
        assert isinstance(content, str)
        self.assertTrue(content.startswith(SKILL_LOADED_PREFIX))
        self.assertEqual(parse_expanded_skill_id(content), "google.gmail")


if __name__ == "__main__":
    unittest.main()
