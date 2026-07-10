from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import Message

from bot.access_control import AccessControlMiddleware
from bot.access_service import get_access_service, reset_access_service, AccessService
from bot.access_store import AccessStore, reset_access_store
from bot.chat_service import ChatService
from bot.chat_store import ChatStore, reset_chat_store
from bot.instance_lock import BotInstanceLock, BotInstanceLockError, acquire_instance_lock
from tools.phase4_config import is_user_allowed


class AccessControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        with patch("bot.access_store.get_settings") as settings:
            settings.return_value.access_db_path = ":memory:"
            self.store = AccessStore()
        reset_access_store(self.store)
        reset_access_service(AccessService(self.store))

    def tearDown(self) -> None:
        reset_access_store(None)
        reset_access_service(None)

    def test_empty_allowlist_allows_everyone_when_approval_disabled(self) -> None:
        with patch("bot.access_service.access_approval_enabled", return_value=False), patch(
            "bot.access_service.admin_user_ids",
            return_value=frozenset(),
        ), patch("bot.access_service.allowed_user_ids", return_value=frozenset()):
            self.assertTrue(is_user_allowed(123))

    def test_approval_blocks_unknown_user(self) -> None:
        with patch("bot.access_service.access_approval_enabled", return_value=True), patch(
            "bot.access_service.admin_user_ids",
            return_value=frozenset(),
        ), patch("bot.access_service.allowed_user_ids", return_value=frozenset()):
            self.assertFalse(is_user_allowed(222))

    async def test_middleware_blocks_unauthorized_user(self) -> None:
        middleware = AccessControlMiddleware()
        message = MagicMock(spec=Message)
        message.from_user = MagicMock()
        message.from_user.id = 999
        message.text = "hello"
        message.answer = AsyncMock()
        handler = AsyncMock(return_value="ok")
        bot = AsyncMock()

        with patch.object(get_access_service(), "is_allowed", return_value=False), patch.object(
            get_access_service(),
            "handle_blocked_message",
            new=AsyncMock(),
        ) as blocked:
            result = await middleware(handler, message, {"bot": bot})

        self.assertIsNone(result)
        handler.assert_not_called()
        blocked.assert_awaited_once()

    async def test_middleware_allows_authorized_user(self) -> None:
        middleware = AccessControlMiddleware()
        message = MagicMock(spec=Message)
        message.from_user = MagicMock()
        message.from_user.id = 111
        message.text = "hello"
        handler = AsyncMock(return_value="ok")

        with patch.object(get_access_service(), "is_allowed", return_value=True):
            result = await middleware(handler, message, {})

        self.assertEqual(result, "ok")
        handler.assert_awaited_once()


class ChatServicePersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.store = ChatStore(db_path=":memory:")
        reset_chat_store(self.store)
        self.agent = MagicMock()
        self.service = ChatService(self.agent, chat_store=self.store)

    async def asyncTearDown(self) -> None:
        reset_chat_store(None)

    async def test_append_turn_persists_history(self) -> None:
        self.service.append_turn_messages(
            7,
            [
                {"role": "user", "content": "question"},
                {"role": "assistant", "content": "answer"},
            ],
        )
        reloaded = ChatService(self.agent, chat_store=self.store)
        history = reloaded.get_history(7)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["content"], "question")

    async def test_reset_history_clears_store(self) -> None:
        self.service.append_turn_messages(
            7,
            [{"role": "user", "content": "question"}],
        )
        with patch("skills.session.SkillSessionStore.reset"), patch(
            "tools.tool_results.store.get_tool_result_store"
        ) as store_factory:
            store_factory.return_value.delete_for_user.return_value = 0
            self.service.reset_history(7)
        self.assertEqual(self.service.get_history(7), [])
        archived = self.store.list_sessions(7, status="archived")
        self.assertEqual(len(archived), 1)
        active = self.store.get_active_session(7)
        assert active is not None
        self.assertEqual(active.message_count, 0)


class InstanceLockTests(unittest.TestCase):
    def test_second_lock_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = os.path.join(tmp, "bot.instance.lock")
            first = acquire_instance_lock(lock_path)
            try:
                with self.assertRaises(BotInstanceLockError):
                    acquire_instance_lock(lock_path)
            finally:
                first.release()

    def test_lock_released_and_reacquired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = os.path.join(tmp, "bot.instance.lock")
            first = BotInstanceLock(lock_path)
            first.acquire()
            first.release()
            second = BotInstanceLock(lock_path)
            second.acquire()
            second.release()


if __name__ == "__main__":
    unittest.main()
