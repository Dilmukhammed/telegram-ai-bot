import unittest

from bot.vision import build_user_message_content, history_text_for_image_turn


class VisionTests(unittest.TestCase):
    def test_text_only_message(self) -> None:
        content = build_user_message_content("hello", [])
        self.assertEqual(content, "hello")

    def test_image_with_caption(self) -> None:
        content = build_user_message_content(
            "what is this?",
            ["data:image/jpeg;base64,abc"],
        )
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1]["type"], "image_url")

    def test_image_without_text_gets_default(self) -> None:
        content = build_user_message_content("", ["data:image/jpeg;base64,abc"])
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("image", content[0]["text"].lower())

    def test_history_placeholder(self) -> None:
        self.assertEqual(history_text_for_image_turn("explain"), "[image]\nexplain")
        self.assertEqual(history_text_for_image_turn(""), "[image]")


if __name__ == "__main__":
    unittest.main()
