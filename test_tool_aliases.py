import unittest

from tools.search_index import TOOL_ALIASES

# Wave 4 priority tools — each alias tied to a benchmark or prod collision case.
WAVE4_ALIAS_TOOLS: tuple[str, ...] = (
    "google.drive.search_files",
    "google.drive.download_file",
    "google.drive.export_file",
    "google.tasks.search_tasks",
    "google.tasks.list_tasks",
    "google.tasks.list_default_tasks",
    "google.calendar.list_today",
    "google.calendar.list_upcoming",
    "google.calendar.freebusy",
    "google.calendar.find_free_slots",
    "google.calendar.search_events",
    "google.sheets.append_values",
    "workspace.find",
    "telegram.send_file",
)


class ToolAliasTests(unittest.TestCase):
    def test_wave4_aliases_present(self) -> None:
        missing = [name for name in WAVE4_ALIAS_TOOLS if name not in TOOL_ALIASES]
        self.assertEqual(missing, [], f"missing aliases: {missing}")

    def test_alias_count_within_budget(self) -> None:
        self.assertLessEqual(len(TOOL_ALIASES), 45)

    def test_aliases_have_negative_phrases(self) -> None:
        for name in WAVE4_ALIAS_TOOLS:
            phrases = TOOL_ALIASES[name]
            self.assertGreaterEqual(len(phrases), 2, f"{name} needs intent + negative phrase")
            self.assertTrue(any("not " in phrase for phrase in phrases), f"{name} missing negative phrase")


if __name__ == "__main__":
    unittest.main()
