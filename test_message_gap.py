import unittest
from datetime import datetime, timedelta, timezone

from bot.message_gap import build_gap_prefix, format_elapsed, prefix_message_if_gap


class MessageGapTests(unittest.TestCase):
    def test_no_prefix_under_20_minutes(self) -> None:
        previous = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
        current = previous + timedelta(minutes=15)
        self.assertIsNone(build_gap_prefix(previous, current))

    def test_prefix_after_20_minutes(self) -> None:
        previous = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
        current = previous + timedelta(minutes=25)
        prefix = build_gap_prefix(previous, current)
        self.assertEqual(prefix, "[gap: 25 minutes since your last message]")

    def test_prefix_days_and_hours(self) -> None:
        previous = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        current = datetime(2026, 7, 3, 1, 0, tzinfo=timezone.utc)
        prefix = build_gap_prefix(previous, current)
        self.assertEqual(prefix, "[gap: 1 day 15 hours since your last message]")

    def test_format_two_days(self) -> None:
        elapsed = format_elapsed(timedelta(days=2, hours=3))
        self.assertEqual(elapsed, "2 days 3 hours")

    def test_prefixes_message_body(self) -> None:
        previous = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
        current = previous + timedelta(hours=2)
        result = prefix_message_if_gap("hello", previous, current)
        self.assertTrue(result.startswith("[gap: 2 hours since your last message]"))
        self.assertIn("hello", result)


if __name__ == "__main__":
    unittest.main()
