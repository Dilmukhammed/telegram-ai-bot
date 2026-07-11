"""Tests for session ↔ period overlap helpers."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from bot.chat_store import reset_chat_store
from bot.chat_store.session_period import session_overlaps_day, session_overlaps_period
from bot.chat_store.store import ChatStore


class SessionPeriodTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ChatStore(":memory:")
        reset_chat_store(self.store)
        self.user_id = 42

    def tearDown(self) -> None:
        reset_chat_store(None)

    def _archive_session_with_span(
        self,
        *,
        started: datetime,
        ended: datetime,
    ) -> str:
        session = self.store.get_or_create_active_session(self.user_id, opened_by="test")
        self.store.append_messages(
            session.session_id,
            self.user_id,
            [
                {"role": "user", "content": "span test"},
                {"role": "assistant", "content": "ok"},
            ],
            source_at_for_message=[started, ended],
        )
        with self.store._connect() as conn:
            conn.execute(
                """
                UPDATE chat_sessions
                SET started_at = ?, last_message_at = ?
                WHERE session_id = ?
                """,
                (started.isoformat(), ended.isoformat(), session.session_id),
            )
            conn.commit()
        archived = self.store.archive_session(session.session_id, closed_by="new_chat")
        assert archived is not None
        return archived.session_id

    def test_multi_day_session_overlaps_each_day(self) -> None:
        started = datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc)
        ended = datetime(2026, 7, 9, 18, 0, tzinfo=timezone.utc)
        session_id = self._archive_session_with_span(started=started, ended=ended)
        session = self.store.get_session_for_user(session_id, self.user_id)
        assert session is not None
        tz = "UTC"
        self.assertTrue(session_overlaps_day(session, "2026-07-07", tz))
        self.assertTrue(session_overlaps_day(session, "2026-07-08", tz))
        self.assertTrue(session_overlaps_day(session, "2026-07-09", tz))
        self.assertFalse(session_overlaps_day(session, "2026-07-06", tz))
        self.assertFalse(session_overlaps_day(session, "2026-07-10", tz))

    def test_week_overlap(self) -> None:
        started = datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc)
        ended = started + timedelta(hours=2)
        session_id = self._archive_session_with_span(started=started, ended=ended)
        session = self.store.get_session_for_user(session_id, self.user_id)
        assert session is not None
        self.assertTrue(
            session_overlaps_period(
                session,
                period_type="week",
                period_key="2026-W28",
                tz_name="UTC",
            )
        )


if __name__ == "__main__":
    unittest.main()
