import json
import unittest

from tools.builtins.yandex.music_serialize import build_method_response, serialize_value


def _fat_track(track_id: int = 1, album_id: int = 10) -> dict:
    return {
        "id": track_id,
        "title": "Test Track",
        "duration_ms": 180000,
        "available": True,
        "lyrics_available": True,
        "cover_uri": "avatars.yandex.net/get-music-content/123/456/xxx/orig",
        "artists": [{"id": 1, "name": "Artist", "various": False, "composer": False}],
        "albums": [{"id": album_id, "title": "Album", "year": 2024, "genre": "pop"}],
        "major": {"id": 1, "name": "UNIVERSAL"},
        "storage_dir": "dir",
        "file_size": 12345,
        "bitrate": 320,
    }


def _fat_playlist_entry(track_id: int = 1, album_id: int = 10) -> dict:
    return {
        "id": track_id,
        "timestamp": "2024-01-01T00:00:00+00:00",
        "album_id": album_id,
        "play_count": 3,
        "recent": True,
        "chart": {"position": 1, "progress": "up", "listeners": 10},
        "original_index": 0,
        "track": _fat_track(track_id, album_id),
    }


class YandexMusicSerializeTests(unittest.TestCase):
    def test_compact_playlist_response(self) -> None:
        playlist = {
            "uid": 123,
            "kind": 3,
            "title": "Liked",
            "track_count": 2,
            "owner": {"uid": 123, "login": "user", "name": "Dima", "display_name": "Dima T"},
            "cover": {"type": "pic", "dir": "cover", "version": "123", "uri": "avatars/xxx"},
            "made_for": {"uid": 1, "login": "x", "name": "X", "display_name": "X"},
            "play_counter": {"updated": "2024-01-01", "plays": 99},
            "tracks": [_fat_playlist_entry(1), _fat_playlist_entry(2, 20)],
        }
        raw = json.dumps(playlist, ensure_ascii=False)
        compact = json.dumps(build_method_response(playlist, method="playlist"), ensure_ascii=False)

        self.assertLess(len(compact), len(raw))
        self.assertLess(len(compact), 2000)
        self.assertIn('"track_id": 1', compact)
        self.assertNotIn("play_counter", compact)
        self.assertNotIn("chart", compact)
        self.assertIn('"owner": "Dima"', compact)

    def test_playlist_track_entry_compacts_nested_track(self) -> None:
        entry = serialize_value(_fat_playlist_entry())
        self.assertIsInstance(entry, dict)
        self.assertIn("track", entry)
        self.assertNotIn("timestamp", entry)
        self.assertEqual(entry["track"]["track_id"], 1)
        self.assertEqual(entry["track"]["artists"], ["Artist"])


if __name__ == "__main__":
    unittest.main()
