import unittest

from agent.history_persist import extract_worker_history_for_persist
from skills.collapse import SKILL_COLLAPSED_PREFIX, parse_expanded_skill_id
from skills.pending import reset_skill_run_state
from skills.registry import get_skill
from skills.session import (
    SkillRunSnapshot,
    SkillSessionStore,
    apply_skill_run_snapshot,
    inject_session_skill_for_run,
)


def _loaded_skill_message(skill_id: str) -> dict:
    spec = get_skill(skill_id)
    assert spec is not None
    return {
        "role": "user",
        "content": f"[Skill loaded: {skill_id}]\n\n{spec.content}",
    }


class SkillSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_skill_run_state()
        SkillSessionStore.reset(42)

    def test_persist_collapses_expanded_skills(self) -> None:
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            _loaded_skill_message("google.gmail"),
            {
                "role": "assistant",
                "content": "done",
            },
        ]
        worker = extract_worker_history_for_persist(
            messages,
            worker_start_index=2,
            display_reply="Ответ.",
        )
        skill_msgs = [
            message["content"]
            for message in worker
            if isinstance(message.get("content"), str) and "google.gmail" in message["content"]
        ]
        self.assertTrue(skill_msgs)
        self.assertTrue(all(SKILL_COLLAPSED_PREFIX in text for text in skill_msgs))
        self.assertIsNone(parse_expanded_skill_id(skill_msgs[0]))

    def test_session_reinject_after_run(self) -> None:
        apply_skill_run_snapshot(
            42,
            SkillRunSnapshot(
                expanded_skill_id="google.calendar",
                skills_with_tools=frozenset({"google.calendar"}),
            ),
        )
        injected = inject_session_skill_for_run(42)
        self.assertEqual(injected, "google.calendar")

    def test_session_idle_clears_after_seven_runs(self) -> None:
        apply_skill_run_snapshot(
            42,
            SkillRunSnapshot(
                expanded_skill_id="google.gmail",
                skills_with_tools=frozenset({"google.gmail"}),
            ),
        )
        for _ in range(6):
            apply_skill_run_snapshot(
                42,
                SkillRunSnapshot(
                    expanded_skill_id="google.gmail",
                    skills_with_tools=frozenset(),
                ),
            )
        self.assertEqual(SkillSessionStore.get(42).expanded_skill_id, "google.gmail")
        apply_skill_run_snapshot(
            42,
            SkillRunSnapshot(
                expanded_skill_id="google.gmail",
                skills_with_tools=frozenset(),
            ),
        )
        self.assertIsNone(SkillSessionStore.get(42).expanded_skill_id)

    def test_reset_clears_session(self) -> None:
        apply_skill_run_snapshot(
            42,
            SkillRunSnapshot(
                expanded_skill_id="google.maps",
                skills_with_tools=frozenset({"google.maps"}),
            ),
        )
        SkillSessionStore.reset(42)
        self.assertIsNone(inject_session_skill_for_run(42))


if __name__ == "__main__":
    unittest.main()
