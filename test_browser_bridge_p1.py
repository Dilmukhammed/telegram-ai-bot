from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tools.builtins.browser.playwright_bridge import (
    PlaywrightSession,
    _serialize_eval_result,
    evaluate,
    frame_switch,
    tabs_list,
    tabs_new,
    tabs_switch,
)


def _session_with_pages(*pages) -> PlaywrightSession:
    context = SimpleNamespace(pages=list(pages), new_page=AsyncMock())
    return PlaywrightSession(
        playwright=SimpleNamespace(),
        browser=SimpleNamespace(),
        context=context,
        page=pages[0] if pages else SimpleNamespace(url="about:blank"),
        frame=None,
        refs={},
        next_ref=1,
    )


class BrowserBridgeP1Tests(unittest.IsolatedAsyncioTestCase):
    async def test_tabs_list_and_switch(self) -> None:
        p1 = SimpleNamespace(
            url="https://a.example/",
            title=AsyncMock(return_value="A"),
            bring_to_front=AsyncMock(),
        )
        p2 = SimpleNamespace(
            url="https://b.example/",
            title=AsyncMock(return_value="B"),
            bring_to_front=AsyncMock(),
        )
        session = _session_with_pages(p1, p2)
        listed = await tabs_list(session)
        self.assertEqual(listed["count"], 2)
        self.assertTrue(listed["tabs"][0]["active"])

        switched = await tabs_switch(session, index=1)
        self.assertEqual(session.page, p2)
        self.assertEqual(switched["url"], "https://b.example/")
        p2.bring_to_front.assert_awaited()

    async def test_tabs_new(self) -> None:
        existing = SimpleNamespace(url="https://a.example/", title=AsyncMock(return_value="A"))
        new_page = SimpleNamespace(
            url="about:blank",
            title=AsyncMock(return_value=""),
            goto=AsyncMock(),
        )
        session = _session_with_pages(existing)
        session.context.new_page = AsyncMock(return_value=new_page)
        session.context.pages = [existing, new_page]
        result = await tabs_new(session, "https://c.example/")
        new_page.goto.assert_awaited()
        self.assertEqual(session.page, new_page)
        self.assertIn("index", result)

    async def test_frame_switch_main(self) -> None:
        page = SimpleNamespace(url="https://example.com/", frames=[])
        session = _session_with_pages(page)
        session.frame = SimpleNamespace(url="https://iframe/")
        result = await frame_switch(session, main=True)
        self.assertIsNone(session.frame)
        self.assertEqual(result["frame"], "main")

    async def test_evaluate_wraps_expression(self) -> None:
        page = SimpleNamespace(
            url="https://example.com/",
            evaluate=AsyncMock(return_value={"ok": 1}),
        )
        session = _session_with_pages(page)
        result = await evaluate(session, "1+1")
        page.evaluate.assert_awaited()
        expr = page.evaluate.await_args.args[0]
        self.assertIn("=>", expr)
        self.assertEqual(result["result"], {"ok": 1})

    def test_serialize_eval_truncates(self) -> None:
        huge = "x" * 20_000
        out = _serialize_eval_result(huge)
        self.assertIsInstance(out, dict)
        self.assertTrue(out.get("truncated"))


if __name__ == "__main__":
    unittest.main()
