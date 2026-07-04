import re
import unittest
from unittest.mock import patch

from agent.runtime_context import build_runtime_context_prompt


class RuntimeContextTests(unittest.TestCase):
    def test_includes_date_only_not_time(self) -> None:
        with patch.dict("os.environ", {"BOT_TIMEZONE": "Asia/Tashkent"}, clear=False):
            prompt = build_runtime_context_prompt()
        self.assertIn("Today's date", prompt)
        self.assertIn("Asia/Tashkent", prompt)
        self.assertIn("Мавлоно Риёзи", prompt)
        self.assertIn("41.313964", prompt)
        self.assertNotIn("Current date and time", prompt)
        self.assertIsNone(re.search(r"\d{2}:\d{2}", prompt))


if __name__ == "__main__":
    unittest.main()
