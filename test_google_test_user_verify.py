from __future__ import annotations

import unittest
from unittest.mock import patch

from bot.google_test_user_verify import (
    GoogleTestUserVerifyResult,
    verify_google_test_user_email,
)


class GoogleTestUserVerifyTests(unittest.TestCase):
    def test_trust_admin_fallback_when_api_unavailable(self) -> None:
        api_result = GoogleTestUserVerifyResult(
            ok=False,
            found=None,
            detail="GCP OAuth test users API недоступен.",
        )
        with patch(
            "bot.google_test_user_verify._fetch_test_user_emails_via_api",
            return_value=api_result,
        ), patch(
            "bot.google_test_user_verify._verify_with_trust_admin",
            return_value=GoogleTestUserVerifyResult(
                ok=True,
                found=True,
                detail="Подтверждено администратором (без GCP API).",
            ),
        ) as trust_admin, patch("bot.google_test_user_verify.get_settings") as settings:
            settings.return_value.google_test_user_verify_trust_admin = True
            result = verify_google_test_user_email("user@gmail.com")

        self.assertTrue(result.ok)
        self.assertTrue(result.found)
        trust_admin.assert_called_once_with("user@gmail.com")

    def test_no_trust_admin_returns_api_error(self) -> None:
        api_result = GoogleTestUserVerifyResult(
            ok=False,
            found=None,
            detail="Нет GCP credentials для автопроверки.",
        )
        with patch(
            "bot.google_test_user_verify._fetch_test_user_emails_via_api",
            return_value=api_result,
        ), patch("bot.google_test_user_verify.get_settings") as settings:
            settings.return_value.google_test_user_verify_trust_admin = False
            result = verify_google_test_user_email("user@gmail.com")

        self.assertFalse(result.ok)
        self.assertIsNone(result.found)


if __name__ == "__main__":
    unittest.main()
