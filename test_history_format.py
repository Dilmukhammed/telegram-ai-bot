import unittest

from bot.history_format import strip_rich_appendices


class HistoryFormatTests(unittest.TestCase):
    def test_strip_rich_appendices(self) -> None:
        text = "Маршрут готов.\n\n<details>\n<summary>Google Maps</summary>\n\n• link\n</details>"
        self.assertEqual(strip_rich_appendices(text), "Маршрут готов.")


if __name__ == "__main__":
    unittest.main()
