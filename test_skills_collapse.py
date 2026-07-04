import unittest

from config import get_settings
from skills.auto_load import append_pending_skills_to_messages, mark_skills_loaded_from_history
from skills.collapse import (
    SKILL_COLLAPSED_PREFIX,
    SkillContextCollapser,
    build_collapsed_skill_content,
    collapse_skill_in_messages,
    expanded_skill_ids_in_messages,
    parse_collapsed_skill_id,
    parse_expanded_skill_id,
)
from skills.pending import is_skill_loaded, mark_skill_loaded, reset_skill_run_state, take_pending_skills
from skills.registry import get_skill
from skills.pending import push_pending_skill


def _loaded_message(skill_id: str) -> dict:
    content = get_skill(skill_id)
    assert content is not None
    return {
        "role": "user",
        "content": f"[Skill loaded: {skill_id}]\n\n{content.content}",
    }


class SkillCollapseTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_skill_run_state()

    def test_parse_expanded_and_collapsed(self) -> None:
        spec = get_skill("google.maps")
        assert spec is not None
        expanded = f"[Skill loaded: google.maps]\n\n{spec.content}"
        collapsed = build_collapsed_skill_content(
            "google.maps",
            reason="test reason",
        )
        self.assertEqual(parse_expanded_skill_id(expanded), "google.maps")
        self.assertIsNone(parse_expanded_skill_id(collapsed))
        self.assertEqual(parse_collapsed_skill_id(collapsed), "google.maps")

    def test_collapse_replaces_full_playbook_and_unmarks_loaded(self) -> None:
        messages = [_loaded_message("google.gmail")]
        mark_skill_loaded("google.gmail")
        self.assertTrue(
            collapse_skill_in_messages(
                messages,
                "google.gmail",
                reason="idle test",
            )
        )
        self.assertFalse(is_skill_loaded("google.gmail"))
        self.assertIn(SKILL_COLLAPSED_PREFIX, messages[0]["content"])
        self.assertIn("skills.load", messages[0]["content"])
        self.assertIn("idle test", messages[0]["content"])
        self.assertEqual(expanded_skill_ids_in_messages(messages), set())

    def test_new_skill_load_collapses_previous(self) -> None:
        messages = [_loaded_message("google.gmail")]
        collapser = SkillContextCollapser()
        collapser.sync_from_messages(messages, turn_index=0)

        reset_skill_run_state()
        mark_skill_loaded("google.calendar")
        push_pending_skill("google.calendar", get_skill("google.calendar").content)

        append_pending_skills_to_messages(messages, collapser, turn_index=1)

        self.assertEqual(expanded_skill_ids_in_messages(messages), {"google.calendar"})
        gmail_msgs = [
            m["content"]
            for m in messages
            if isinstance(m.get("content"), str) and "google.gmail" in m["content"]
        ]
        self.assertTrue(any(SKILL_COLLAPSED_PREFIX in text for text in gmail_msgs))
        self.assertTrue(any("replaced by google.calendar" in text for text in gmail_msgs))

    def test_idle_collapse_after_seven_turns(self) -> None:
        messages = [_loaded_message("google.tasks")]
        collapser = SkillContextCollapser()
        collapser.sync_from_messages(messages, turn_index=0)
        mark_skill_loaded("google.tasks")

        for turn in range(1, 7):
            self.assertEqual(collapser.collapse_idle_if_needed(messages, turn), [])

        collapsed = collapser.collapse_idle_if_needed(messages, 7)
        self.assertEqual(collapsed, ["google.tasks"])
        self.assertEqual(expanded_skill_ids_in_messages(messages), set())
        self.assertIn("7+ agent turns", messages[0]["content"])

    def test_tool_use_resets_idle_timer(self) -> None:
        messages = [_loaded_message("google.drive")]
        collapser = SkillContextCollapser()
        collapser.sync_from_messages(messages, turn_index=0)

        for turn in range(1, 6):
            collapser.collapse_idle_if_needed(messages, turn)

        collapser.on_tool_use("google.drive", 6)
        self.assertEqual(collapser.collapse_idle_if_needed(messages, 12), [])

    def test_collapsed_history_not_marked_loaded(self) -> None:
        collapsed = build_collapsed_skill_content("google.maps", reason="was idle")
        history = [{"role": "user", "content": collapsed}]
        mark_skills_loaded_from_history(history)
        self.assertFalse(is_skill_loaded("google.maps"))

    def test_threshold_from_config(self) -> None:
        self.assertEqual(get_settings().skills_collapse_idle_turns, 7)


if __name__ == "__main__":
    unittest.main()
