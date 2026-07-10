import unittest
from datetime import datetime, timezone

from bot.chat_commands import format_session_detail, format_sessions_list
from bot.chat_store.models import ChatSession


def _session(**overrides) -> ChatSession:
    base = dict(
        session_id="abc123def456",
        user_id=1,
        status="archived",
        summary="User discussed cafes.",
        summary_status="done",
        title="Tashkent cafes",
        message_count=4,
        created_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
        started_at=datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc),
        last_message_at=datetime(2026, 7, 9, 10, 5, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
        archived_at=datetime(2026, 7, 9, 10, 6, tzinfo=timezone.utc),
        summary_started_at=None,
        summary_completed_at=None,
        metadata={},
    )
    base.update(overrides)
    return ChatSession(**base)


class ChatCommandsFormatTests(unittest.TestCase):
    def test_format_sessions_list(self) -> None:
        text = format_sessions_list([_session()])
        self.assertIn("Tashkent cafes", text)
        self.assertIn("abc123de", text)
        self.assertIn("/session", text)

    def test_format_session_detail(self) -> None:
        text = format_session_detail(_session(), trace_count=2)
        self.assertIn("abc123def456", text)
        self.assertIn("Tashkent cafes", text)
        self.assertIn("traces: 2", text)


if __name__ == "__main__":
    unittest.main()
