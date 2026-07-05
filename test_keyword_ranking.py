import unittest

from tools.keyword_index import tokenize
from tools.ranking import keyword_action_bonus


class KeywordRankingTests(unittest.TestCase):
    def test_gmail_search_beats_exa_penalty(self) -> None:
        tokens = tokenize("search gmail messages")
        gmail = keyword_action_bonus(tokens, "google.gmail.search_messages")
        exa = keyword_action_bonus(tokens, "exa.web_search")
        self.assertGreater(gmail, exa)

    def test_likes_beats_dislikes(self) -> None:
        tokens = tokenize("liked tracks favorites")
        likes = keyword_action_bonus(tokens, "yandex.music.users_likes_tracks")
        dislikes = keyword_action_bonus(tokens, "yandex.music.users_dislikes_tracks")
        self.assertGreater(likes, dislikes)

    def test_calendar_today_not_auth(self) -> None:
        tokens = tokenize("Google Calendar events today")
        today = keyword_action_bonus(tokens, "google.calendar.list_today")
        auth = keyword_action_bonus(tokens, "google.auth.status")
        self.assertGreater(today, auth)

    def test_yandex_auth_beats_google_on_yandex_query(self) -> None:
        tokens = tokenize("status yandex oauth")
        yandex = keyword_action_bonus(tokens, "yandex.auth.status")
        google = keyword_action_bonus(tokens, "google.auth.status")
        self.assertGreater(yandex, google)


    def test_search_tasks_beats_exa(self) -> None:
        tokens = tokenize("search tasks")
        tasks = keyword_action_bonus(tokens, "google.tasks.search_tasks")
        exa = keyword_action_bonus(tokens, "exa.web_search")
        self.assertGreater(tasks, exa)

    def test_generic_search_boosts_exa_over_siblings(self) -> None:
        tokens = tokenize("search")
        exa = keyword_action_bonus(tokens, "exa.web_search")
        gmail = keyword_action_bonus(tokens, "google.gmail.search_messages")
        self.assertGreater(exa, gmail)


    def test_reverse_geocode_beats_geocode(self) -> None:
        tokens = tokenize("reverse geocode coordinates to address")
        reverse_tool = keyword_action_bonus(tokens, "google.maps.reverse_geocode")
        geocode = keyword_action_bonus(tokens, "google.maps.geocode")
        self.assertGreater(reverse_tool, geocode)

    def test_track_download_beats_download_info(self) -> None:
        tokens = tokenize("download yandex music track mp3")
        download = keyword_action_bonus(tokens, "yandex.music.track_download")
        info = keyword_action_bonus(tokens, "yandex.music.tracks_download_info")
        self.assertGreater(download, info)

    def test_liked_albums_boost(self) -> None:
        tokens = tokenize("liked albums favorites")
        albums = keyword_action_bonus(tokens, "yandex.music.users_likes_albums")
        tracks = keyword_action_bonus(tokens, "yandex.music.users_likes_tracks")
        self.assertGreater(albums, tracks)


if __name__ == "__main__":
    unittest.main()
