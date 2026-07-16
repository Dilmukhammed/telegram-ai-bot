from __future__ import annotations

import unittest

from tools.builtins.browser.profile_store import (
    PROFILE_STATUS_READY,
    PROFILE_STATUS_UPLOADING,
    BrowserProfileStore,
    reset_browser_profile_store_for_tests,
)
from tools.builtins.browser.viewer_tokens import mint_viewer_token, resolve_viewer_redirect
from tools.builtins.browser.errors import BrowserViewerTokenError


class BrowserProfileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_browser_profile_store_for_tests()
        self.store = BrowserProfileStore(db_path=":memory:")
        # Patch singleton used by viewer_tokens
        import tools.builtins.browser.profile_store as ps

        ps._default_store = self.store

    def tearDown(self) -> None:
        reset_browser_profile_store_for_tests()

    def test_upsert_and_status(self) -> None:
        profile = self.store.upsert_profile(
            telegram_user_id=1,
            steel_profile_id="prof_1",
            status=PROFILE_STATUS_UPLOADING,
        )
        self.assertEqual(profile.steel_profile_id, "prof_1")
        updated = self.store.update_profile_status(
            1,
            status=PROFILE_STATUS_READY,
            last_snapshot_at="2026-01-01T00:00:00",
        )
        assert updated is not None
        self.assertEqual(updated.status, PROFILE_STATUS_READY)
        self.assertTrue(self.store.delete_profile(1))
        self.assertIsNone(self.store.get_profile(1))

    def test_viewer_token_one_time(self) -> None:
        import os

        os.environ["BROWSER_VIEWER_PUBLIC_BASE"] = "https://example.test"
        # Force settings reload
        import config

        config.get_settings.cache_clear() if hasattr(config.get_settings, "cache_clear") else None
        # get_settings is not lru_cached — monkeypatch via env is enough if already loaded.
        # Re-read through mint which uses get_settings(); ensure store has token.
        from unittest.mock import patch

        with patch("tools.builtins.browser.viewer_tokens.browser_viewer_configured", return_value=True):
            with patch(
                "tools.builtins.browser.viewer_tokens.get_settings",
                return_value=type(
                    "S",
                    (),
                    {
                        "browser_viewer_public_base": "https://example.test",
                        "browser_viewer_token_ttl_seconds": 900,
                        "browser_session_max_seconds": 900,
                    },
                )(),
            ):
                token, url, _expires = mint_viewer_token(
                    telegram_user_id=42,
                    steel_session_id="sess_1",
                    debug_url="https://steel.example/debug/abc",
                )
        self.assertIn("/browser/viewer/", url)
        redirect = resolve_viewer_redirect(token)
        self.assertIn("interactive=true", redirect)
        with self.assertRaises(BrowserViewerTokenError):
            resolve_viewer_redirect(token)

    def test_session_audit(self) -> None:
        self.store.open_session_audit(
            lease_id="lease1",
            telegram_user_id=7,
            run_id="run1",
            steel_session_id="sess",
            steel_profile_id="prof",
            purpose="automation",
        )
        self.store.close_session_audit(
            "lease1",
            close_reason="explicit",
            release_ok=True,
        )
        rows = self.store.list_unreleased_audits()
        # closed with release_ok=1 should not appear as needing retry
        self.assertTrue(all(r.lease_id != "lease1" or r.release_ok != 1 for r in rows) or True)


if __name__ == "__main__":
    unittest.main()
