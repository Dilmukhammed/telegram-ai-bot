import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tools.builtins.google.auth import (
    auth_status_payload,
    extract_oauth_code_from_text,
    extract_oauth_state_from_text,
    looks_like_manual_oauth_callback,
)
from tools.builtins.google.datetime_utils import (
    build_create_calendar_body,
    build_create_event_body,
    build_event_time,
    build_patch_event_body,
    compact_color_palette,
    compact_event,
    find_free_slots,
    merge_calendar_for_update,
    today_bounds,
)
from tools.builtins.google.token_store import GoogleTokenStore, StoredGoogleToken


class GoogleTokenStoreTests(unittest.TestCase):
    def test_save_and_load(self) -> None:
        store = GoogleTokenStore(db_path=":memory:")
        store.save(
            telegram_user_id=42,
            email="user@example.com",
            refresh_token="refresh",
            access_token="access",
            token_expiry=datetime(2026, 1, 1, tzinfo=timezone.utc),
            scopes=("https://www.googleapis.com/auth/calendar",),
        )
        stored = store.get(42)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.email, "user@example.com")
        self.assertEqual(stored.refresh_token, "refresh")


class GoogleCalendarHelpersTests(unittest.TestCase):
    def test_compact_event(self) -> None:
        event = compact_event(
            {
                "id": "evt1",
                "summary": "Meeting",
                "start": {"dateTime": "2026-07-02T10:00:00+05:00"},
                "end": {"dateTime": "2026-07-02T11:00:00+05:00"},
            }
        )
        self.assertEqual(event["id"], "evt1")
        self.assertEqual(event["summary"], "Meeting")

    def test_today_bounds(self) -> None:
        start, end, tz_name = today_bounds("UTC")
        self.assertLess(start, end)
        self.assertEqual(tz_name, "UTC")

    def test_build_timed_event_body(self) -> None:
        body = build_create_event_body(
            {
                "summary": "Sync",
                "start": {"datetime": "2026-07-03T15:00:00", "time_zone": "Asia/Tashkent"},
                "end": {"datetime": "2026-07-03T16:00:00", "time_zone": "Asia/Tashkent"},
                "location": "Zoom",
            }
        )
        self.assertEqual(body["summary"], "Sync")
        self.assertIn("dateTime", body["start"])
        self.assertEqual(body["start"]["timeZone"], "Asia/Tashkent")
        self.assertEqual(body["location"], "Zoom")

    def test_build_all_day_event_body(self) -> None:
        body = build_create_event_body(
            {
                "summary": "Offsite",
                "start": {"date": "2026-07-10"},
                "end": {"date": "2026-07-11"},
            }
        )
        self.assertEqual(body["start"], {"date": "2026-07-10"})
        self.assertEqual(body["end"], {"date": "2026-07-11"})

    def test_build_patch_event_body_partial(self) -> None:
        body = build_patch_event_body(
            {
                "summary": "Renamed",
                "start": {"datetime": "2026-07-03T16:00:00+05:00"},
            }
        )
        self.assertEqual(body["summary"], "Renamed")
        self.assertIn("dateTime", body["start"])
        self.assertNotIn("end", body)

    def test_build_event_time_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            build_event_time({})

    def test_build_create_calendar_body(self) -> None:
        body = build_create_calendar_body(
            {"summary": "Work", "description": "Projects", "time_zone": "Asia/Tashkent"}
        )
        self.assertEqual(body["summary"], "Work")
        self.assertEqual(body["timeZone"], "Asia/Tashkent")

    def test_merge_calendar_for_update(self) -> None:
        updated = merge_calendar_for_update(
            {"id": "cal1", "summary": "Old", "timeZone": "UTC"},
            {"summary": "New"},
        )
        self.assertEqual(updated["summary"], "New")
        self.assertEqual(updated["timeZone"], "UTC")

    def test_find_free_slots_respects_working_hours(self) -> None:
        tz = ZoneInfo("UTC")
        time_min = datetime(2026, 7, 3, 0, 0, tzinfo=tz)
        time_max = datetime(2026, 7, 3, 23, 59, tzinfo=tz)
        busy_blocks = [
            {"start": "2026-07-03T10:00:00+00:00", "end": "2026-07-03T11:00:00+00:00"},
        ]
        slots = find_free_slots(
            time_min=time_min,
            time_max=time_max,
            busy_blocks=busy_blocks,
            duration_minutes=60,
            working_hours_start="09:00",
            working_hours_end="18:00",
            time_zone="UTC",
            max_slots=5,
        )
        self.assertGreater(len(slots), 0)
        first_start = datetime.fromisoformat(slots[0]["start"])
        self.assertGreaterEqual(first_start.hour, 9)
        self.assertLess(first_start.hour, 18)

    def test_compact_color_palette(self) -> None:
        palette = compact_color_palette(
            {
                "updated": "2026-07-02T10:00:00Z",
                "calendar": {
                    "1": {"background": "#ac725e", "foreground": "#1d1d1d"},
                    "2": {"background": "#d06b64", "foreground": "#1d1d1d"},
                },
                "event": {
                    "10": {"background": "#5484ed", "foreground": "#1d1d1d"},
                },
            }
        )
        self.assertEqual(len(palette["calendar_colors"]), 2)
        self.assertEqual(palette["calendar_colors"][0]["color_id"], "1")
        self.assertEqual(palette["event_colors"][0]["background"], "#5484ed")

    def test_create_event_with_color_id(self) -> None:
        body = build_create_event_body(
            {
                "summary": "Colored",
                "start": {"date": "2026-07-10"},
                "end": {"date": "2026-07-11"},
                "color_id": "4",
            }
        )
        self.assertEqual(body["colorId"], "4")

    def test_compact_event_includes_color_id(self) -> None:
        event = compact_event(
            {
                "id": "evt1",
                "summary": "Meeting",
                "colorId": "5",
                "start": {"dateTime": "2026-07-02T10:00:00+05:00"},
                "end": {"dateTime": "2026-07-02T11:00:00+05:00"},
            }
        )
        self.assertEqual(event["color_id"], "5")


class GoogleToolsRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_google_calendar_tools_registered(self) -> None:
        from tools.bootstrap import create_tool_runtime

        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            runtime = await create_tool_runtime()

        result = await runtime.search_tools("", tags=["google", "calendar"], mode="catalog")
        names = {tool["name"] for tool in result["tools"]}
        self.assertIn("google.calendar.list_today", names)
        self.assertIn("google.calendar.freebusy", names)
        self.assertIn("google.calendar.create_event", names)
        self.assertIn("google.calendar.patch_event", names)
        self.assertIn("google.calendar.list_calendars", names)
        self.assertIn("google.calendar.import_event", names)
        self.assertIn("google.calendar.find_free_slots", names)
        self.assertIn("google.calendar.list_instances", names)
        self.assertIn("google.calendar.list_colors", names)
        self.assertIn("google.calendar.set_calendar_color", names)
        self.assertNotIn("google.auth.status", names)

    async def test_auth_tools_have_google_auth_tags(self) -> None:
        from tools.bootstrap import create_tool_runtime

        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            runtime = await create_tool_runtime()

        result = await runtime.search_tools("", tags=["google", "auth"], mode="catalog")
        names = {tool["name"] for tool in result["tools"]}
        self.assertIn("google.auth.status", names)


class GoogleOAuthCallbackParseTests(unittest.TestCase):
    def test_extract_code_from_localhost_url(self) -> None:
        url = "http://localhost:1/?code=4/0Aabc&scope=calendar"
        self.assertEqual(extract_oauth_code_from_text(url), "4/0Aabc")
        self.assertTrue(looks_like_manual_oauth_callback(url))

    def test_extract_code_from_query_only(self) -> None:
        self.assertEqual(
            extract_oauth_code_from_text("code=abc123&scope=email"),
            "abc123",
        )

    def test_oauth_error_raises(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "access_denied"):
            extract_oauth_code_from_text("http://localhost:1/?error=access_denied")

    def test_extract_code_from_chrome_error_text(self) -> None:
        text = (
            "Веб-страница по адресу http://localhost:1/?state=8464921092"
            "&code=4/0Aabc&scope=https://www.googleapis.com/auth/calendar, "
            "возможно, временно недоступна"
        )
        self.assertEqual(extract_oauth_code_from_text(text), "4/0Aabc")
        self.assertEqual(extract_oauth_state_from_text(text), 8464921092)

    def test_pkce_verifier_roundtrip(self) -> None:
        from tools.builtins.google.oauth_pending_store import OAuthPendingStore

        store = OAuthPendingStore(db_path=":memory:")
        store.save_verifier(42, "verifier-secret")
        self.assertEqual(store.pop_verifier(42), "verifier-secret")
        self.assertIsNone(store.pop_verifier(42))


class GoogleAuthStatusTests(unittest.TestCase):
    def test_credentials_expiry_check_with_aware_stored_expiry(self) -> None:
        from google.oauth2.credentials import Credentials

        from tools.builtins.google.auth import credentials_from_stored

        aware_expiry = datetime(2099, 1, 1, tzinfo=timezone.utc)
        stored = StoredGoogleToken(
            telegram_user_id=1,
            email="user@example.com",
            refresh_token="refresh",
            access_token="access",
            token_expiry=aware_expiry,
            scopes=("https://www.googleapis.com/auth/calendar",),
        )
        with patch("tools.builtins.google.auth.get_settings") as mock_settings:
            mock_settings.return_value.google_client_id = "client-id"
            mock_settings.return_value.google_client_secret = "client-secret"
            credentials = credentials_from_stored(stored)
        self.assertIsInstance(credentials, Credentials)
        self.assertIsNone(credentials.expiry.tzinfo)
        self.assertFalse(credentials.expired)

    def test_not_connected_by_default(self) -> None:
        store = GoogleTokenStore(db_path=":memory:")
        with patch("tools.builtins.google.auth.get_token_store", return_value=store):
            with patch("tools.builtins.google.auth.google_oauth_configured", return_value=True):
                status = auth_status_payload(99)
        self.assertTrue(status["configured"])
        self.assertFalse(status["connected"])


if __name__ == "__main__":
    unittest.main()
