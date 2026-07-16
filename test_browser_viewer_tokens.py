from __future__ import annotations

import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from oauth_server import create_oauth_app
from tools.builtins.browser.errors import BrowserViewerTokenError
from tools.builtins.browser.profile_store import BrowserProfileStore, reset_browser_profile_store_for_tests
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.viewer_tokens import mint_viewer_token, resolve_viewer_redirect


class BrowserViewerRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        reset_browser_profile_store_for_tests()
        self.store = BrowserProfileStore(db_path=":memory:")
        import tools.builtins.browser.profile_store as ps

        ps._default_store = self.store

    async def asyncTearDown(self) -> None:
        reset_browser_profile_store_for_tests()

    async def test_viewer_route_302_and_gone_on_replay(self) -> None:
        with patch(
            "tools.builtins.browser.viewer_tokens.browser_viewer_configured",
            return_value=True,
        ), patch(
            "tools.builtins.browser.viewer_tokens.get_settings",
            return_value=type(
                "S",
                (),
                {
                    "browser_viewer_public_base": "https://bot.example",
                    "browser_viewer_token_ttl_seconds": 900,
                    "browser_session_max_seconds": 900,
                },
            )(),
        ):
            token, _url, _exp = mint_viewer_token(
                telegram_user_id=1,
                steel_session_id="s1",
                debug_url="https://api.steel.dev/debug/xyz",
            )

        app = create_oauth_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"/browser/viewer/{token}", allow_redirects=False)
            self.assertEqual(resp.status, 302)
            location = resp.headers.get("Location", "")
            self.assertIn("api.steel.dev/debug/xyz", location)
            self.assertIn("interactive=true", location)

            resp2 = await client.get(f"/browser/viewer/{token}", allow_redirects=False)
            self.assertIn(resp2.status, {403, 410})

    def test_redact_debug_url_from_payload(self) -> None:
        payload = {
            "ok": True,
            "debug_url": "https://api.steel.dev/v1/sessions/x/debug",
            "note": "see https://api.steel.dev/debug/abc",
        }
        redacted = redact_browser_payload(payload)
        self.assertEqual(redacted["debug_url"], "[redacted]")
        self.assertNotIn("api.steel.dev/debug", redacted["note"])


if __name__ == "__main__":
    unittest.main()
