import unittest

from tools.keyword_index import expand_query_terms, tokenize
from tools.ranking import keyword_action_bonus


class ListIntentRankingTests(unittest.TestCase):
    def test_skips_bare_list_in_multiword_query(self) -> None:
        terms = expand_query_terms("list files")
        self.assertIn("list files", terms)
        self.assertNotIn("list", terms)

    def test_list_files_beats_tasks_crud(self) -> None:
        tokens = tokenize("list files")
        drive = keyword_action_bonus(tokens, "google.drive.list_files")
        tasks = keyword_action_bonus(tokens, "google.tasks.create_tasklist")
        self.assertGreater(drive, tasks)

    def test_list_events_beats_tasks(self) -> None:
        tokens = tokenize("list events")
        events = keyword_action_bonus(tokens, "google.calendar.list_events")
        tasks = keyword_action_bonus(tokens, "google.tasks.create_tasklist")
        self.assertGreater(events, tasks)

    def test_list_user_playlists_beats_generic_playlists(self) -> None:
        tokens = tokenize("list user playlists")
        user_list = keyword_action_bonus(tokens, "yandex.music.users_playlists_list")
        generic = keyword_action_bonus(tokens, "yandex.music.playlists_list")
        self.assertGreater(user_list, generic)

    def test_bare_list_penalizes_tasklist_crud(self) -> None:
        tokens = tokenize("list")
        skills = keyword_action_bonus(tokens, "skills.list")
        create = keyword_action_bonus(tokens, "google.tasks.create_tasklist")
        self.assertGreater(skills, create)


if __name__ == "__main__":
    unittest.main()
