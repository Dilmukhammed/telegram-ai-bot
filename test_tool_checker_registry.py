import unittest

from tools.builtins import BUILTIN_TOOLS
from tools.builtins.google import GOOGLE_TOOLS
from tools.builtins.yandex import YANDEX_TOOLS
from tools.checker.common import is_checker_excluded
from tools.checker.registry import checker_has_questions, get_checker_questions

ALL_TOOLS = BUILTIN_TOOLS + GOOGLE_TOOLS + YANDEX_TOOLS


class CheckerRegistryCoverageTests(unittest.TestCase):
    def test_all_registered_tools_have_questions_or_are_excluded(self) -> None:
        missing: list[str] = []
        covered = 0
        excluded = 0
        for spec in ALL_TOOLS:
            if is_checker_excluded(spec):
                excluded += 1
                continue
            questions = get_checker_questions(spec)
            if not questions:
                missing.append(spec.name)
                continue
            covered += 1
        self.assertEqual(
            missing,
            [],
            msg=f"Tools without checker questions: {missing[:20]}{'...' if len(missing) > 20 else ''}",
        )
        self.assertGreater(covered, 400)
        self.assertGreater(excluded, 0)

    def test_templates_include_live_fetch_for_targeted_writes(self) -> None:
        from tools.builtins.google.calendar_tools import GOOGLE_CALENDAR_DELETE_EVENT
        from tools.checker.registry import get_checker_questions

        question_ids = {item.id for item in get_checker_questions(GOOGLE_CALENDAR_DELETE_EVENT)}
        self.assertIn("correct_event_targeted", question_ids)

        from tools.builtins.google.drive_tools import GOOGLE_DRIVE_UPDATE_FILE_METADATA

        patch_questions = get_checker_questions(GOOGLE_DRIVE_UPDATE_FILE_METADATA)
        self.assertTrue(patch_questions)
        live_kinds = {
            ref.fetch for q in patch_questions for ref in q.evidence if ref.fetch
        }
        self.assertIn("drive_file", live_kinds)

    def test_excluded_tools_have_no_questions(self) -> None:
        from tools.builtins.echo import ECHO_TOOL
        from tools.builtins.coach_reply import COACH_REPLY_TOOL

        self.assertFalse(checker_has_questions(ECHO_TOOL))
        self.assertFalse(checker_has_questions(COACH_REPLY_TOOL))


if __name__ == "__main__":
    unittest.main()
