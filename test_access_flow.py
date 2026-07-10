from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import CopyTextButton, User

from bot.access_service import (
    AccessService,
    build_google_email_admin_markup,
    google_test_users_console_url,
    parse_email,
    reset_access_service,
)
from bot.access_store import AccessStore, reset_access_store
from bot.google_connect_flow import try_handle_google_email
from bot.google_test_user_verify import GoogleTestUserVerifyResult


class AccessFlowHelpersTests(unittest.TestCase):
    def test_parse_email(self) -> None:
        self.assertEqual(parse_email("User@gmail.com"), "user@gmail.com")
        self.assertIsNone(parse_email("not-an-email"))

    def test_google_console_url_from_project(self) -> None:
        with patch("bot.access_service.get_settings") as settings:
            settings.return_value.google_cloud_test_users_url = ""
            settings.return_value.google_cloud_project_id = "my-hermes-bot"
            url = google_test_users_console_url()
        self.assertIn("project=my-hermes-bot", url)

    def test_google_console_url_override(self) -> None:
        with patch("bot.access_service.get_settings") as settings:
            settings.return_value.google_cloud_test_users_url = "https://example.com/console"
            settings.return_value.google_cloud_project_id = ""
            self.assertEqual(google_test_users_console_url(), "https://example.com/console")

    def test_google_email_admin_markup_has_copy_url_and_verify(self) -> None:
        markup = build_google_email_admin_markup(42, "user@gmail.com")
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 3)
        copy_btn = rows[0][0]
        url_btn = rows[1][0]
        verify_btn = rows[2][0]
        self.assertIsInstance(copy_btn.copy_text, CopyTextButton)
        self.assertEqual(copy_btn.copy_text.text, "user@gmail.com")
        self.assertTrue(url_btn.url)
        self.assertEqual(verify_btn.callback_data, "gacc:verify:42")


class GoogleEmailFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        with patch("bot.access_store.get_settings") as settings:
            settings.return_value.access_db_path = ":memory:"
            self.store = AccessStore()
        reset_access_store(self.store)
        self.service = AccessService(self.store)
        reset_access_service(self.service)

    async def asyncTearDown(self) -> None:
        reset_access_service(None)
        reset_access_store(None)

    async def test_email_flow_notifies_admin_without_oauth_link(self) -> None:
        user = User(id=42, is_bot=False, first_name="Test")
        message = MagicMock()
        message.from_user = user
        message.text = "user@gmail.com"
        message.answer = AsyncMock()

        bot = MagicMock()
        bot.send_message = AsyncMock()

        self.service.begin_google_email_collection(42)
        oauth_start_url = lambda uid: f"https://oauth.example/start?user_id={uid}"

        handled = await try_handle_google_email(message, bot, oauth_start_url=oauth_start_url)

        self.assertTrue(handled)
        self.assertEqual(self.service.get_google_email(42), "user@gmail.com")
        bot.send_message.assert_awaited()
        markup = bot.send_message.await_args.kwargs.get("reply_markup")
        self.assertIsNotNone(markup)
        message.answer.assert_awaited_once()
        answer_text = message.answer.await_args.args[0]
        self.assertIn("user@gmail.com", answer_text)
        self.assertIn("автоматически", answer_text)

    async def test_verify_google_test_user_notifies_user_and_admin(self) -> None:
        self.store.save_google_email(42, "user@gmail.com")
        bot = MagicMock()
        bot.send_message = AsyncMock()

        oauth_start_url = lambda uid: f"https://oauth.example/start?user_id={uid}"
        verify_result = GoogleTestUserVerifyResult(
            ok=True,
            found=True,
            detail="Email найден в Test users (GCP API).",
        )

        with patch(
            "bot.google_test_user_verify.verify_google_test_user_email",
            return_value=verify_result,
        ), patch(
            "bot.google_connect_flow.send_google_connect_url_to_user",
            new=AsyncMock(),
        ) as send_oauth:
            note = await self.service.verify_google_test_user(
                bot,
                42,
                admin_id=1,
                oauth_start_url=oauth_start_url,
            )

        self.assertIn("добавлен и проверен", note)
        self.assertTrue(self.service.is_google_test_user_verified(42))
        bot.send_message.assert_awaited()
        send_oauth.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
