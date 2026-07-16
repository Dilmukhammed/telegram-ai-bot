from __future__ import annotations

import os
import unittest

import pytest


@pytest.mark.steel_live
class BrowserSteelLiveSmoke(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        if not os.getenv("STEEL_API_KEY"):
            self.skipTest("STEEL_API_KEY not set")
        if os.getenv("BROWSER_SMOKE_SKIP", "").strip() in {"1", "true", "yes"}:
            self.skipTest("BROWSER_SMOKE_SKIP set")

    async def test_navigate_and_screenshot(self) -> None:
        from tools.builtins.browser.playwright_bridge import (
            connect_session,
            disconnect_session,
            navigate,
            screenshot,
        )
        from tools.builtins.browser.steel_client import get_steel_client, reset_steel_client_for_tests

        reset_steel_client_for_tests()
        client = get_steel_client()
        await client.acquire_session_slot()
        session = None
        pw = None
        try:
            session = await client.create_session(api_timeout=120_000, persist_profile=False)
            session_id = getattr(session, "id", None)
            ws = getattr(session, "websocket_url", None) or getattr(session, "websocketUrl", None)
            self.assertTrue(session_id and ws)
            pw = await connect_session(websocket_url=str(ws), api_key=os.environ["STEEL_API_KEY"])
            nav = await navigate(pw, "https://example.com")
            self.assertIn("example", nav["url"])
            png = await screenshot(pw, full_page=False)
            self.assertGreater(len(png), 100)
        finally:
            if pw is not None:
                await disconnect_session(pw)
            if session is not None:
                try:
                    await client.release_session(str(getattr(session, "id")))
                except Exception:
                    pass
            await client.release_session_slot()
            reset_steel_client_for_tests()


if __name__ == "__main__":
    unittest.main()
