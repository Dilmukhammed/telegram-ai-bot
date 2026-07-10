import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from bot.chat_service import ChatService
from bot.chat_store import ChatStore
from config import get_settings


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class ChatServiceStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ChatStore(db_path=":memory:")
        agent = MagicMock()
        self.service = ChatService(agent, chat_store=self.store)
        self.user_id = 501
        self.t1 = _utc(2026, 7, 9, 10, 0)
        self.t2 = _utc(2026, 7, 9, 10, 5)

    def test_get_history_starts_empty(self) -> None:
        self.assertEqual(self.service.get_history(self.user_id), [])

    def test_append_and_reload_prompt_history(self) -> None:
        self.service.append_turn_messages(
            self.user_id,
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
            user_message_at=self.t1,
        )
        self.assertEqual(len(self.service.get_history(self.user_id)), 2)

        reloaded = ChatService(MagicMock(), chat_store=self.store)
        history = reloaded.get_history(self.user_id)
        self.assertEqual(history[0]["content"], "hello")
        self.assertEqual(history[1]["content"], "hi")
        self.assertEqual(reloaded._last_message_at[self.user_id], self.t1)

    def test_prompt_trim_keeps_full_session_in_db(self) -> None:
        settings = get_settings()
        trimmed_settings = settings.__class__(
            **{**settings.__dict__, "chat_max_history": 1}
        )
        with patch("bot.chat_service.get_settings", return_value=trimmed_settings), patch(
            "bot.chat_store.store.get_settings",
            return_value=trimmed_settings,
        ):
            for turn in range(3):
                self.service.append_turn_messages(
                    self.user_id,
                    [
                        {"role": "user", "content": f"user-{turn}"},
                        {"role": "assistant", "content": f"assistant-{turn}"},
                    ],
                    user_message_at=self.t1,
                )

            prompt_history = self.service.get_history(self.user_id)
            self.assertEqual(prompt_history[0]["content"], "user-2")
            self.assertEqual(len(prompt_history), 2)

        active = self.store.get_active_session(self.user_id)
        assert active is not None
        db_messages = self.store.read_message_dicts(active.session_id)
        self.assertEqual(len(db_messages), 6)

    def test_reset_archives_session_with_messages(self) -> None:
        self.service.append_turn_messages(
            self.user_id,
            [
                {"role": "user", "content": "keep me archived"},
                {"role": "assistant", "content": "ok"},
            ],
            user_message_at=self.t1,
            user_message_metadata={"telegram_message_id": 42},
        )
        active_before = self.store.get_active_session(self.user_id)
        assert active_before is not None

        self.service.reset_history(self.user_id, closed_by="reset")

        self.assertEqual(self.service.get_history(self.user_id), [])
        archived = self.store.list_sessions(self.user_id, status="archived")
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].session_id, active_before.session_id)
        self.assertEqual(archived[0].metadata.get("closed_by"), "reset")
        self.assertEqual(archived[0].summary_status, "pending")

        new_active = self.store.get_active_session(self.user_id)
        assert new_active is not None
        self.assertNotEqual(new_active.session_id, active_before.session_id)
        self.assertEqual(new_active.message_count, 0)

        archived_messages = self.store.read_message_dicts(archived[0].session_id)
        self.assertEqual(archived_messages[0]["content"], "keep me archived")
        row = self.store.get_message_by_id(1)
        assert row is not None
        self.assertEqual(row.metadata.get("telegram_message_id"), 42)

    def test_reset_without_messages_does_not_archive_empty_session(self) -> None:
        self.service.get_history(self.user_id)
        self.service.reset_history(self.user_id, closed_by="start")
        archived = self.store.list_sessions(self.user_id, status="archived")
        self.assertEqual(archived, [])

    def test_prepare_user_message_uses_last_user_source_at(self) -> None:
        self.service.append_turn_messages(
            self.user_id,
            [{"role": "user", "content": "first"}],
            user_message_at=self.t1,
        )
        self.service._histories.pop(self.user_id, None)

        reloaded = ChatService(MagicMock(), chat_store=self.store)
        prepared = reloaded.prepare_user_message(self.user_id, "second", self.t2)
        self.assertIn("second", prepared)


if __name__ == "__main__":
    unittest.main()
