import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from agent.run_trace import RunTrace, RunTraceCollector
from bot.chat_store import ChatStore
from bot.chat_store.summary import format_session_traces_for_summary, summarize_archived_session
from bot.chat_store.traces import append_session_trace, list_session_traces
from config import get_settings


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _sample_trace(user_message: str = "find cafes") -> RunTrace:
    collector = RunTraceCollector(
        user_id=1,
        user_message=user_message,
        worker_turns_budget=30,
    )
    collector.finish("completed")
    return collector.build()


class ChatSessionTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ChatStore(db_path=":memory:")
        self.session = self.store.get_or_create_active_session(10)
        self.user_id = 10

    def test_append_and_list_traces(self) -> None:
        trace = _sample_trace("hello")
        with self.store._connect() as conn:
            append_session_trace(
                conn,
                self.session.session_id,
                self.user_id,
                trace=trace,
                assistant_reply="Hi there.",
                source_at=_utc(2026, 7, 9),
            )
            conn.commit()
            rows = list_session_traces(conn, self.session.session_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].user_message, "hello")
        self.assertEqual(rows[0].assistant_reply, "Hi there.")
        self.assertEqual(rows[0].turn_seq, 1)

    def test_format_session_traces_for_summary(self) -> None:
        trace = _sample_trace("route to airport")
        self.store.append_session_trace(
            self.session.session_id,
            self.user_id,
            trace=trace,
            assistant_reply="Here is the route.",
            source_at=_utc(2026, 7, 9),
        )
        records = self.store.list_session_traces(self.session.session_id)
        text = format_session_traces_for_summary(records, settings=get_settings())
        self.assertIn("Turn 1", text)
        self.assertIn("route to airport", text)
        self.assertIn("Here is the route.", text)


class ChatSessionSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_summarize_archived_session(self) -> None:
        store = ChatStore(db_path=":memory:")
        session = store.get_or_create_active_session(20)
        store.append_session_trace(
            session.session_id,
            20,
            trace=_sample_trace("book meeting"),
            assistant_reply="Meeting booked for tomorrow.",
            source_at=_utc(2026, 7, 9),
        )
        archived, _ = store.archive_and_create_active(20, closed_by="reset")

        assert archived is not None
        mock_llm = AsyncMock()
        mock_llm.chat_without_reasoning = AsyncMock(
            return_value=json.dumps(
                {
                    "title": "Meeting booking",
                    "summary": (
                        "User asked to book a meeting; the assistant confirmed "
                        "booking for tomorrow."
                    ),
                }
            )
        )
        with patch("bot.chat_store.summary.LLMClient", return_value=mock_llm):
            await summarize_archived_session(store, archived.session_id)

        updated = store.list_sessions(20, status="archived")[0]
        self.assertEqual(updated.summary_status, "done")
        self.assertIn("meeting", (updated.summary or "").lower())
        self.assertEqual(updated.title, "Meeting booking")
        self.assertIsNotNone(updated.summary_completed_at)
        mock_llm.chat_without_reasoning.assert_awaited_once()

    async def test_summarize_fails_without_traces(self) -> None:
        store = ChatStore(db_path=":memory:")
        store.get_or_create_active_session(21)
        store.append_messages(
            store.get_active_session(21).session_id,
            21,
            [{"role": "user", "content": "orphan message"}],
            default_source_at=_utc(2026, 7, 9),
        )
        archived, _ = store.archive_and_create_active(21, closed_by="reset")
        assert archived is not None

        await summarize_archived_session(store, archived.session_id)
        updated = store.list_sessions(21, status="archived")[0]
        self.assertEqual(updated.summary_status, "failed")


if __name__ == "__main__":
    unittest.main()
