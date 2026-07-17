from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tools.builtins.browser import BROWSER_TOOLS
from tools.builtins.browser.profile_store import BrowserProfileStore, reset_browser_profile_store_for_tests
from tools.builtins.browser.session_manager import (
    BrowserSessionManager,
    set_browser_session_manager,
)
from tools.builtins.browser.steel_client import SteelClientFacade, set_steel_client_for_tests
from tools.context import RunContext, reset_run_context, set_run_context
from tools.checker.common import is_checker_excluded
from tools.checker.registry import get_checker_questions
from agent.tool_search_hints import tags_for_tool_name
from skills.skill_map import skill_id_for_tool_name


class BrowserToolsMockedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        reset_browser_profile_store_for_tests()
        self.store = BrowserProfileStore(db_path=":memory:")
        import tools.builtins.browser.profile_store as ps

        ps._default_store = self.store

        sdk = SimpleNamespace(
            sessions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(
                        id="sess1",
                        websocket_url="wss://example/ws",
                        debug_url="https://steel.example/debug/1",
                        profile_id="prof1",
                    )
                ),
                release=AsyncMock(),
            ),
            profiles=SimpleNamespace(
                retrieve=AsyncMock(return_value=SimpleNamespace(status="READY")),
                delete=AsyncMock(),
            ),
        )
        set_steel_client_for_tests(SteelClientFacade(sdk, max_concurrent=5, rpm=60))
        self.mgr = BrowserSessionManager(run_id="r1", user_id=99)
        self.token = set_browser_session_manager(self.mgr)
        self.ctx_token = set_run_context(RunContext(user_id=99, turn=1, meta_tool="use_tool"))

        self.fake_pw = SimpleNamespace(
            playwright=SimpleNamespace(stop=AsyncMock()),
            browser=SimpleNamespace(close=AsyncMock()),
            page=SimpleNamespace(
                url="https://example.com",
                title=AsyncMock(return_value="Example"),
                goto=AsyncMock(return_value=SimpleNamespace(status=200)),
                accessibility=SimpleNamespace(
                    snapshot=AsyncMock(
                        return_value={
                            "role": "WebArea",
                            "name": "Example",
                            "children": [
                                {"role": "link", "name": "More information"},
                            ],
                        }
                    )
                ),
                inner_text=AsyncMock(return_value="Hello"),
                content=AsyncMock(return_value="<html>hi</html>"),
                screenshot=AsyncMock(return_value=b"\x89PNG\r\n\x1a\n"),
                pdf=AsyncMock(return_value=b"%PDF"),
                keyboard=SimpleNamespace(press=AsyncMock()),
                mouse=SimpleNamespace(wheel=AsyncMock()),
                evaluate=AsyncMock(return_value=0),
                wait_for_timeout=AsyncMock(),
                query_selector_all=AsyncMock(return_value=[]),
            ),
            refs={},
            next_ref=1,
        )

    async def asyncTearDown(self) -> None:
        reset_run_context(self.ctx_token)
        from tools.builtins.browser.session_manager import reset_browser_session_manager

        reset_browser_session_manager(self.token)
        set_steel_client_for_tests(None)
        reset_browser_profile_store_for_tests()

    async def test_tool_count_and_discovery(self) -> None:
        self.assertEqual(len(BROWSER_TOOLS), 71)
        names = {t.name for t in BROWSER_TOOLS}
        self.assertIn("browser.session_open", names)
        self.assertIn("browser.screenshot", names)
        self.assertIn("browser.tabs.list", names)
        self.assertIn("browser.download", names)
        self.assertIn("browser.evaluate", names)
        self.assertIn("browser.cookies.get", names)
        self.assertIn("browser.drag", names)
        self.assertIn("browser.storage.get", names)
        self.assertIn("browser.network.last", names)
        self.assertIn("browser.console", names)
        self.assertIn("browser.route", names)
        self.assertIn("browser.clipboard_read", names)
        self.assertIn("browser.emulate_media", names)
        self.assertIn("browser.perf", names)
        self.assertIn("browser.captcha.detect", names)
        self.assertIn("browser.captcha.solve", names)
        self.assertEqual(tags_for_tool_name("browser.navigate"), ("browser", "web"))
        self.assertEqual(skill_id_for_tool_name("browser.navigate"), "browser")
        self.assertEqual(tags_for_tool_name("browser.tabs.list"), ("browser", "web"))
        self.assertEqual(skill_id_for_tool_name("browser.evaluate"), "browser")
        self.assertEqual(tags_for_tool_name("browser.captcha.detect"), ("browser", "auth"))
        self.assertEqual(skill_id_for_tool_name("browser.captcha.solve"), "browser")

        by_name = {t.name: t for t in BROWSER_TOOLS}
        self.assertTrue(is_checker_excluded(by_name["browser.session_open"]))
        self.assertFalse(is_checker_excluded(by_name["browser.navigate"]))
        questions = get_checker_questions(by_name["browser.navigate"])
        self.assertTrue(questions)

    async def test_session_open_result_has_no_debug_url(self) -> None:
        open_tool = next(t for t in BROWSER_TOOLS if t.name == "browser.session_open")
        with patch(
            "tools.builtins.browser.session_manager.browser_tools_enabled",
            return_value=True,
        ), patch(
            "tools.builtins.browser.session_manager.connect_session",
            AsyncMock(return_value=self.fake_pw),
        ), patch(
            "tools.builtins.browser.session_manager.disconnect_session",
            AsyncMock(),
        ), patch(
            "tools.builtins.browser.session_manager.get_settings",
            return_value=SimpleNamespace(
                browser_session_max_seconds=900,
                browser_viewport_width=1280,
                browser_viewport_height=800,
                steel_api_key="k",
                browser_profile_ready_timeout_seconds=1,
                browser_profile_ready_poll_interval_seconds=0.01,
                browser_session_idle_close_seconds=300,
            ),
        ), patch(
            "tools.builtins.browser.playwright_bridge.navigate",
            AsyncMock(return_value={"url": "https://example.com", "title": "Example", "status": 200}),
        ):
            result = await open_tool.handler({"purpose": "automation"})
        self.assertNotIn("debug_url", result)
        self.assertNotIn("_debug_url_internal", result)
        self.assertIn("session_handle", result)

        nav = next(t for t in BROWSER_TOOLS if t.name == "browser.navigate")
        with patch(
            "tools.builtins.browser.page_tools.pw.navigate",
            AsyncMock(return_value={"url": "https://example.com", "title": "Example", "status": 200}),
        ):
            # use real get_playwright via manager
            pass
        nav_result = await nav.handler({"url": "https://example.com"})
        self.assertEqual(nav_result["url"], "https://example.com")

        snap = next(t for t in BROWSER_TOOLS if t.name == "browser.snapshot")
        snap_result = await snap.handler({})
        self.assertTrue(snap_result["refs"])

        close = next(t for t in BROWSER_TOOLS if t.name == "browser.session_close")
        with patch(
            "tools.builtins.browser.session_manager.poll_profile_ready",
            AsyncMock(
                return_value=SimpleNamespace(
                    ready=True,
                    status="ready",
                    attempts=1,
                    poll_elapsed_ms=10,
                    error=None,
                )
            ),
        ):
            closed = await close.handler({})
        self.assertTrue(closed["released"])


if __name__ == "__main__":
    unittest.main()
