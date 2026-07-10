from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import Message, User

from bot.access_service import AccessService, format_user_brief, parse_email
from bot.access_store import AccessStore, reset_access_store


class AccessServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        with patch("bot.access_store.get_settings") as settings:
            settings.return_value.access_db_path = ":memory:"
            self.store = AccessStore()
        reset_access_store(self.store)
        self.service = AccessService(self.store)

    def tearDown(self) -> None:
        reset_access_store(None)

    def test_parse_email(self) -> None:
        self.assertEqual(parse_email("User@Gmail.com"), "user@gmail.com")
        self.assertIsNone(parse_email("not-an-email"))

    def test_format_user_brief(self) -> None:
        user = User(id=1, is_bot=False, first_name="Ann", username="ann")
        self.assertIn("@ann", format_user_brief(user))

    def test_approval_required_blocks_unknown_user(self) -> None:
        with patch("bot.access_service.access_approval_enabled", return_value=True), patch(
            "bot.access_service.admin_user_ids",
            return_value=frozenset({99}),
        ), patch("bot.access_service.allowed_user_ids", return_value=frozenset()):
            self.assertFalse(self.service.is_allowed(42))
            self.assertTrue(self.service.is_allowed(99))

    def test_env_allowlist_grants_access(self) -> None:
        with patch("bot.access_service.access_approval_enabled", return_value=True), patch(
            "bot.access_service.admin_user_ids",
            return_value=frozenset(),
        ), patch("bot.access_service.allowed_user_ids", return_value=frozenset({42})):
            self.assertTrue(self.service.is_allowed(42))

    def test_approve_persists_user(self) -> None:
        self.store.upsert_pending(42, username="u", display_name="User")
        self.store.set_status(42, "approved", approved_by=99)
        with patch("bot.access_service.access_approval_enabled", return_value=True), patch(
            "bot.access_service.admin_user_ids",
            return_value=frozenset(),
        ), patch("bot.access_service.allowed_user_ids", return_value=frozenset()):
            self.assertTrue(self.service.is_allowed(42))


class AccessCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_approve_notifies_user(self) -> None:
        with patch("bot.access_store.get_settings") as settings:
            settings.return_value.access_db_path = ":memory:"
            store = AccessStore()
        reset_access_store(store)
        service = AccessService(store)
        store.upsert_pending(42, username="u", display_name="User")

        bot = AsyncMock()
        note = await service.approve_user(bot, 42, admin_id=99)
        self.assertIn("одобрен", note)
        bot.send_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
