from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tools.builtins.browser.profile_store import BrowserProfileStore, reset_browser_profile_store_for_tests
from tools.builtins.browser.session_manager import BrowserSessionManager
from tools.builtins.browser.steel_client import SteelClientFacade, set_steel_client_for_tests


class _FakeSdk:
    def __init__(self) -> None:
        self.sessions = SimpleNamespace(
            create=AsyncMock(),
            release=AsyncMock(),
            list=AsyncMock(return_value=[]),
        )
        self.profiles = SimpleNamespace(
            retrieve=AsyncMock(return_value=SimpleNamespace(status="READY")),
            delete=AsyncMock(),
        )


class BrowserSessionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        reset_browser_profile_store_for_tests()
        self.store = BrowserProfileStore(db_path=":memory:")
        import tools.builtins.browser.profile_store as ps

        ps._default_store = self.store

        self.sdk = _FakeSdk()
        self.sdk.sessions.create.return_value = SimpleNamespace(
            id="sess_abc",
            websocket_url="wss://example/ws",
            debug_url="https://steel.example/debug/abc",
            profile_id="prof_abc",
        )
        self.client = SteelClientFacade(self.sdk, max_concurrent=2, rpm=60)
        set_steel_client_for_tests(self.client)

        self.fake_pw = SimpleNamespace(
            playwright=SimpleNamespace(stop=AsyncMock()),
            browser=SimpleNamespace(close=AsyncMock()),
            context=None,
            page=SimpleNamespace(url="https://example.com", title=AsyncMock(return_value="Example")),
            refs={},
            next_ref=1,
        )

    async def asyncTearDown(self) -> None:
        set_steel_client_for_tests(None)
        reset_browser_profile_store_for_tests()

    async def test_open_reuse_close_releases(self) -> None:
        mgr = BrowserSessionManager(run_id="run1", user_id=1)
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
                steel_api_key="test-key",
                browser_profile_ready_timeout_seconds=1,
                browser_profile_ready_poll_interval_seconds=0.01,
                browser_session_idle_close_seconds=300,
            ),
        ), patch(
            "tools.builtins.browser.playwright_bridge.navigate",
            AsyncMock(return_value={"url": "https://example.com", "title": "Example", "status": 200}),
        ):
            first = await mgr.open(purpose="automation", persist=True, start_url="https://example.com")
            self.assertFalse(first["reused"])
            second = await mgr.open(purpose="automation")
            self.assertTrue(second["reused"])
            self.assertEqual(first["session_handle"], second["session_handle"])

            closed = await mgr.close(reason="explicit")
            self.assertTrue(closed["released"])
            self.sdk.sessions.release.assert_awaited()
            self.assertEqual(self.client.active_slots, 0)

    async def test_login_run_end_parks_instead_of_revoke(self) -> None:
        from tools.builtins.browser import session_manager as sm

        sm._HELD_LOGIN_LEASES.clear()
        mgr = BrowserSessionManager(run_id="run_login", user_id=3)
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
                steel_api_key="test-key",
                browser_profile_ready_timeout_seconds=1,
                browser_profile_ready_poll_interval_seconds=0.01,
                browser_session_idle_close_seconds=300,
            ),
        ), patch(
            "tools.builtins.browser.playwright_bridge.navigate",
            AsyncMock(return_value={"url": "https://accounts.google.com/", "title": "Google", "status": 200}),
        ):
            opened = await mgr.open(purpose="login", persist=True)
            self.assertFalse(opened["reused"])
            await mgr.close_all(reason="run_end")
            self.sdk.sessions.release.assert_not_awaited()
            self.assertIn(3, sm._HELD_LOGIN_LEASES)
            held = sm._HELD_LOGIN_LEASES[3]
            self.assertFalse(held.closed)

            mgr2 = BrowserSessionManager(run_id="run_login2", user_id=3)
            adopted = await mgr2.adopt_held_login_lease()
            self.assertTrue(adopted)
            self.assertNotIn(3, sm._HELD_LOGIN_LEASES)
            closed = await mgr2.close(reason="explicit")
            self.assertTrue(closed["released"])
            self.sdk.sessions.release.assert_awaited()

    async def test_close_all_on_error_still_releases(self) -> None:
        mgr = BrowserSessionManager(run_id="run2", user_id=2)
        with patch(
            "tools.builtins.browser.session_manager.browser_tools_enabled",
            return_value=True,
        ), patch(
            "tools.builtins.browser.session_manager.connect_session",
            AsyncMock(return_value=self.fake_pw),
        ), patch(
            "tools.builtins.browser.session_manager.disconnect_session",
            AsyncMock(side_effect=RuntimeError("pw boom")),
        ), patch(
            "tools.builtins.browser.session_manager.get_settings",
            return_value=SimpleNamespace(
                browser_session_max_seconds=900,
                browser_viewport_width=1280,
                browser_viewport_height=800,
                steel_api_key="test-key",
                browser_profile_ready_timeout_seconds=1,
                browser_profile_ready_poll_interval_seconds=0.01,
                browser_session_idle_close_seconds=300,
            ),
        ):
            await mgr.open(purpose="automation", persist=False)
            await mgr.close_all(reason="run_end")
            self.sdk.sessions.release.assert_awaited()
            self.assertEqual(self.client.active_slots, 0)


if __name__ == "__main__":
    unittest.main()
