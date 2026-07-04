import unittest

from bot.transcription_format import (
    format_transcription_agent,
    format_transcription_chat,
)


class TranscriptionFormatTests(unittest.TestCase):
    def test_chat_voice_collapsed_details(self) -> None:
        text = format_transcription_chat("привет мир", "voice")
        self.assertIn("<details>", text)
        self.assertIn("<summary>Транскрипция</summary>", text)
        self.assertIn("<blockquote>привет мир</blockquote>", text)
        self.assertNotIn("open", text)

    def test_chat_audio_collapsed_details(self) -> None:
        text = format_transcription_chat("hello", "audio")
        self.assertIn("<summary>Транскрипция · аудио</summary>", text)
        self.assertIn("<blockquote>hello</blockquote>", text)

    def test_chat_empty(self) -> None:
        text = format_transcription_chat("   ", "voice")
        self.assertIn("—", text)

    def test_agent_voice_tag(self) -> None:
        text = format_transcription_agent("привет", "voice")
        self.assertEqual(text, "[transcription:voice]\nпривет")


if __name__ == "__main__":
    unittest.main()
