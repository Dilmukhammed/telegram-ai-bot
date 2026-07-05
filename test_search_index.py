import unittest

from tools.schema import ToolSpec
from tools.search_index import enriched_index_text, keyword_action_bonus


class SearchIndexTests(unittest.TestCase):
    def test_enriched_index_includes_aliases(self) -> None:
        tool = ToolSpec(
            name="yandex.music.search",
            description="Yandex Music API search.",
            parameters={"type": "object", "properties": {}},
            handler=lambda _: None,  # type: ignore[arg-type]
            tags=("yandex", "music"),
        )
        text = enriched_index_text(
            name=tool.name,
            description=tool.description,
            tags=tool.tags,
        )
        self.assertIn("lookup", text)
        self.assertIn("catalog", text)

    def test_keyword_action_bonus_prefers_search_tool(self) -> None:
        bonus = keyword_action_bonus({"search", "tracks"}, "yandex.music.search")
        tracks_bonus = keyword_action_bonus({"search", "tracks"}, "yandex.music.tracks")
        self.assertGreater(bonus, tracks_bonus)

    def test_keyword_action_bonus_prefers_auth_status(self) -> None:
        status = keyword_action_bonus({"connection", "status"}, "google.auth.status")
        connect = keyword_action_bonus({"connection", "status"}, "google.auth.connect_url")
        self.assertGreater(status, connect)


if __name__ == "__main__":
    unittest.main()
