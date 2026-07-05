import unittest

from agent.history_persist import extract_worker_history_for_persist
from skills.collapse import parse_expanded_skill_id
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

    def test_persist_keeps_expanded_skills(self) -> None:
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
        self.assertIsNotNone(parse_expanded_skill_id(skill_msgs[0]))

    def test_session_inject_is_noop(self) -> None:
        apply_skill_run_snapshot(
            42,
            SkillRunSnapshot(
                expanded_skill_id="google.calendar",
                skills_with_tools=frozenset({"google.calendar"}),
            ),
        )
        self.assertIsNone(inject_session_skill_for_run(42))

    def test_session_tracks_expanded_skill(self) -> None:
        apply_skill_run_snapshot(
            42,
            SkillRunSnapshot(
                expanded_skill_id="google.gmail",
                skills_with_tools=frozenset({"google.gmail"}),
            ),
        )
        self.assertEqual(SkillSessionStore.get(42).expanded_skill_id, "google.gmail")

    def test_reset_clears_session(self) -> None:
        apply_skill_run_snapshot(
            42,
            SkillRunSnapshot(
                expanded_skill_id="google.maps",
                skills_with_tools=frozenset({"google.maps"}),
            ),
        )
        SkillSessionStore.reset(42)
        self.assertIsNone(SkillSessionStore.get(42).expanded_skill_id)


if __name__ == "__main__":
    unittest.main()
