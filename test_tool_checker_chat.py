import unittest

from tools.builtins.chat_checker import CHAT_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.chat_tools import CHAT_TOOLS
from tools.checker.registry import get_checker_questions


class ChatCheckerTests(unittest.TestCase):
    def test_all_chat_tools_have_checker_questions(self) -> None:
        for spec in CHAT_TOOLS:
            questions = get_checker_questions(spec)
            self.assertTrue(questions, msg=spec.name)
            self.assertEqual(
                questions,
                CHAT_CHECKER_QUESTIONS_BY_TOOL[spec.name],
            )


if __name__ == "__main__":
    unittest.main()
