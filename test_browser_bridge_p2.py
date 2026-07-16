from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tools.builtins.browser.playwright_bridge import (
    PlaywrightSession,
    _ring_append,
    network_last,
    storage_get,
    storage_set,
)


def _session(page=None) -> PlaywrightSession:
    page = page or SimpleNamespace(
        url="https://example.com/",
        evaluate=AsyncMock(return_value='{"a":"1"}'),
        set_viewport_size=AsyncMock(),
        keyboard=SimpleNamespace(down=AsyncMock(), up=AsyncMock()),
        mouse=SimpleNamespace(
            move=AsyncMock(),
            down=AsyncMock(),
            up=AsyncMock(),
        ),
    )
    context = SimpleNamespace(
        pages=[page],
        on=lambda *a, **k: None,
        set_geolocation=AsyncMock(),
        grant_permissions=AsyncMock(),
        clear_permissions=AsyncMock(),
        new_cdp_session=AsyncMock(
            return_value=SimpleNamespace(send=AsyncMock(), detach=AsyncMock())
        ),
    )
    return PlaywrightSession(
        playwright=SimpleNamespace(),
        browser=SimpleNamespace(),
        context=context,
        page=page,
    )


class BrowserBridgeP2Tests(unittest.IsolatedAsyncioTestCase):
    def test_ring_append_caps(self) -> None:
        buf: list[dict] = []
        for i in range(5):
            _ring_append(buf, {"i": i}, 3)
        self.assertEqual([x["i"] for x in buf], [2, 3, 4])

    async def test_network_last(self) -> None:
        session = _session()
        session.network_events = [{"type": "response", "url": f"u{i}"} for i in range(5)]
        out = await network_last(session, limit=2)
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["events"][0]["url"], "u3")

    async def test_storage_set_get(self) -> None:
        page = SimpleNamespace(
            url="https://example.com/",
            evaluate=AsyncMock(side_effect=[None, '{"k":"v"}', "v"]),
        )
        session = _session(page)
        set_out = await storage_set(session, area="local", key="k", value="v")
        self.assertTrue(set_out["set"])
        all_out = await storage_get(session, area="local")
        self.assertEqual(all_out["count"], 1)
        one = await storage_get(session, area="local", key="k")
        self.assertEqual(one["value"], "v")


if __name__ == "__main__":
    unittest.main()
