from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tools.builtins.browser.errors import BrowserError
from tools.builtins.browser.playwright_bridge import (
    PlaywrightSession,
    emulate_media,
    perf_metrics,
    route_install,
    route_remove,
)


def _session() -> PlaywrightSession:
    page = SimpleNamespace(
        url="https://example.com/",
        route=AsyncMock(),
        unroute=AsyncMock(),
        unroute_all=AsyncMock(),
        emulate_media=AsyncMock(),
        evaluate=AsyncMock(
            return_value={
                "duration": 120.5,
                "domContentLoadedEventEnd": 80,
                "loadEventEnd": 120,
                "transferSize": 1024,
                "noise": "drop",
            }
        ),
    )
    context = SimpleNamespace(
        pages=[page],
        on=lambda *a, **k: None,
        grant_permissions=AsyncMock(),
    )
    return PlaywrightSession(
        playwright=SimpleNamespace(),
        browser=SimpleNamespace(),
        context=context,
        page=page,
    )


class BrowserBridgeP3Tests(unittest.IsolatedAsyncioTestCase):
    async def test_route_abort_and_unroute(self) -> None:
        session = _session()
        installed = await route_install(
            session, action="abort", glob="**/tracking.js"
        )
        self.assertTrue(installed["ok"])
        self.assertEqual(installed["action"], "abort")
        session.page.route.assert_awaited()
        removed = await route_remove(session, glob="**/tracking.js")
        self.assertEqual(removed["removed"], 1)
        self.assertEqual(removed["active_routes"], 0)

    async def test_route_rejects_continue(self) -> None:
        session = _session()
        with self.assertRaises(BrowserError):
            await route_install(session, action="continue", url="https://x/")

    async def test_emulate_media_and_perf(self) -> None:
        session = _session()
        media = await emulate_media(session, color_scheme="dark", media="print")
        self.assertTrue(media["ok"])
        session.page.emulate_media.assert_awaited()
        perf = await perf_metrics(session)
        self.assertTrue(perf["ok"])
        self.assertEqual(perf["metrics"]["duration"], 120.5)
        self.assertNotIn("noise", perf["metrics"])


if __name__ == "__main__":
    unittest.main()
