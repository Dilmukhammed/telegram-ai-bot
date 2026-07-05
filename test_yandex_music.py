import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from tools.builtins.yandex import YANDEX_TOOLS
from tools.builtins.yandex.music_client import (
    _download_track_id,
    _pick_download_info,
    download_track_to_file_ref,
)
from tools.builtins.yandex.music_tool_registry import MUSIC_TOOL_COUNT
from tools.builtins.yandex.music_tools import YANDEX_AUTH_TOOLS, YANDEX_MUSIC_TRACK_DOWNLOAD
from tools.run_files import RunFileStore, set_run_file_store


class YandexMusicToolsTests(unittest.TestCase):
    def test_tool_count(self) -> None:
        self.assertEqual(MUSIC_TOOL_COUNT, 141)
        self.assertEqual(len(YANDEX_AUTH_TOOLS), 4)
        self.assertIn(YANDEX_MUSIC_TRACK_DOWNLOAD, YANDEX_TOOLS)
        self.assertEqual(len(YANDEX_TOOLS), MUSIC_TOOL_COUNT + 1 + len(YANDEX_AUTH_TOOLS))

    def test_unique_tool_names(self) -> None:
        names = [tool.name for tool in YANDEX_TOOLS]
        self.assertEqual(len(names), len(set(names)))

    def test_search_tool_registered(self) -> None:
        names = {tool.name for tool in YANDEX_TOOLS}
        self.assertIn("yandex.music.search", names)
        self.assertIn("yandex.music.track_download", names)
        self.assertIn("yandex.auth.status", names)

    def test_auth_oauth_not_in_music_registry(self) -> None:
        from tools.builtins.yandex.music_tool_registry import MUSIC_TOOL_REGISTRY

        methods = {entry["method"] for entry in MUSIC_TOOL_REGISTRY}
        self.assertNotIn("request_device_code", methods)
        self.assertNotIn("poll_device_token", methods)

    def test_download_track_id_adds_album(self) -> None:
        track = SimpleNamespace(id=141264728, albums=[SimpleNamespace(id=999)])
        self.assertEqual(_download_track_id(track, "141264728"), "141264728:999")
        self.assertEqual(_download_track_id(track, "141264728:888"), "141264728:888")

    def test_pick_download_info_prefers_codec(self) -> None:
        infos = [
            SimpleNamespace(codec="aac", bitrate_in_kbps=128),
            SimpleNamespace(codec="mp3", bitrate_in_kbps=192),
        ]
        picked = _pick_download_info(infos, "mp3")
        self.assertEqual(picked.codec, "mp3")


class YandexTrackDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_uses_track_without_fetch(self) -> None:
        track = MagicMock()
        track.title = "Test Song"
        track.id = 123
        track.albums = [SimpleNamespace(id=456)]
        track.to_dict.return_value = {"id": 123, "title": "Test Song"}
        track.get_download_info_async = AsyncMock(
            return_value=[SimpleNamespace(codec="mp3", bitrate_in_kbps=192)]
        )
        track.download_bytes_async = AsyncMock(return_value=b"audio-bytes")

        client = MagicMock()
        client.tracks = AsyncMock(return_value=[track])

        store = RunFileStore(run_id="testrun", user_id=1)
        set_run_file_store(store)

        with patch(
            "tools.builtins.yandex.music_client.get_music_client",
            new=AsyncMock(return_value=client),
        ):
            result = await download_track_to_file_ref(
                telegram_user_id=1,
                track_id="123",
                codec="mp3",
            )

        self.assertIn("file_ref", result)
        self.assertEqual(result["title"], "Test Song")
        track.download_bytes_async.assert_awaited_once_with("mp3", 192)
        self.assertFalse(hasattr(track, "fetch_track_async") and track.fetch_track_async.called)


class YandexMusicSerializeTests(unittest.TestCase):
    def test_tracks_response_uses_compact_track_fields(self) -> None:
        from tools.builtins.yandex.music_serialize import build_method_response

        fat_track = {
            "id": "141264728",
            "title": "Test Song",
            "duration_ms": 200000,
            "available": True,
            "lyrics_available": False,
            "cover_uri": "avatars.yandex.net/get-music-content/123/orig",
            "derived_colors": {"average": "#000000", "waveText": "#ffffff"},
            "download_info": {"count": 2, "items": [{"codec": "mp3"}, {"codec": "aac"}]},
            "artists": {
                "count": 1,
                "items": [{"id": 1, "name": "Artist", "cover": {"uri": "x" * 500}}],
            },
            "albums": {
                "count": 1,
                "items": [{"id": 999, "title": "Album", "track_count": 10, "labels": []}],
            },
        }
        payload = build_method_response([fat_track], method="tracks")
        item = payload["items"][0]
        self.assertEqual(set(item.keys()), {
            "track_id",
            "album_id",
            "title",
            "artists",
            "duration_ms",
            "available",
            "lyrics_available",
            "cover_uri",
            "url",
        })
        self.assertNotIn("download_info", item)
        self.assertNotIn("derived_colors", item)

    def test_like_wrapper_is_not_compact_as_track(self) -> None:
        from tools.builtins.yandex.music_serialize import serialize_value

        like = {
            "id": "1",
            "timestamp": "2026-01-01T00:00:00",
            "track": {
                "id": "141264728",
                "title": "Nested",
                "duration_ms": 1000,
                "artists": {"count": 1, "items": [{"name": "A"}]},
                "albums": {"count": 1, "items": [{"id": 2}]},
            },
        }
        out = serialize_value(like)
        self.assertIn("timestamp", out)
        self.assertEqual(out["track"]["title"], "Nested")
        self.assertEqual(out["track"]["track_id"], "141264728")


if __name__ == "__main__":
    unittest.main()
