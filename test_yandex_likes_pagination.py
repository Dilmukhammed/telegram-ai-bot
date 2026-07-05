import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tools.builtins.yandex.music_pagination import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    pop_list_pagination,
    slice_tracks_list_result,
)
from tools.builtins.yandex.music_tools import _make_handler


class YandexLikesPaginationTests(unittest.TestCase):
    def test_pop_list_pagination_defaults(self) -> None:
        prepared, offset, limit = pop_list_pagination({"user_id": "1"})
        self.assertEqual(prepared, {"user_id": "1"})
        self.assertEqual(offset, 0)
        self.assertEqual(limit, DEFAULT_PAGE_LIMIT)

    def test_pop_list_pagination_custom_page(self) -> None:
        prepared, offset, limit = pop_list_pagination({"offset": 50, "limit": 25})
        self.assertEqual(prepared, {})
        self.assertEqual(offset, 50)
        self.assertEqual(limit, 25)

    def test_pop_list_pagination_rejects_bad_limit(self) -> None:
        with self.assertRaises(ValueError):
            pop_list_pagination({"limit": MAX_PAGE_LIMIT + 1})

    def test_slice_tracks_list_result(self) -> None:
        tracks = [SimpleNamespace(id=i) for i in range(117)]
        value = SimpleNamespace(uid=1, revision=0, tracks=tracks)
        sliced, meta = slice_tracks_list_result(value, offset=50, limit=50)
        self.assertEqual(len(sliced.tracks), 50)
        self.assertEqual(sliced.tracks[0].id, 50)
        self.assertEqual(meta["total_count"], 117)
        self.assertEqual(meta["offset"], 50)
        self.assertEqual(meta["returned_count"], 50)
        self.assertTrue(meta["has_more"])
        self.assertEqual(len(tracks), 117)


class YandexLikesHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_users_likes_tracks_passes_pagination_to_response(self) -> None:
        tracks = [SimpleNamespace(id=i, to_dict=lambda i=i: {"id": str(i), "title": f"t{i}", "albums": []}) for i in range(5)]
        api_result = SimpleNamespace(uid=1, revision=0, tracks=tracks)
        client = object()
        handler = _make_handler("users_likes_tracks", auth=True)

        with patch(
            "tools.builtins.yandex.music_tools.get_music_client",
            new=AsyncMock(return_value=client),
        ), patch(
            "tools.builtins.yandex.music_tools.call_music_method",
            new=AsyncMock(return_value=api_result),
        ) as call_mock, patch(
            "tools.builtins.yandex.music_tools._require_user_id",
            return_value=1,
        ):
            result = await handler({"offset": 1, "limit": 2})

        call_mock.assert_awaited_once_with(client, "users_likes_tracks", {})
        self.assertEqual(result["total_count"], 5)
        self.assertEqual(result["offset"], 1)
        self.assertEqual(result["limit"], 2)
        self.assertEqual(result["returned_count"], 2)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["method"], "users_likes_tracks")


if __name__ == "__main__":
    unittest.main()
