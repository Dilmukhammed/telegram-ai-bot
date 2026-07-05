import unittest

from tools.tool_results.stats import format_archive_stats_section, load_global_archive_stats
from tools.tool_results.store import ToolResultStore, reset_tool_result_store


class ToolResultStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_tool_result_store(ToolResultStore(":memory:"))

    def test_format_archive_stats_section(self) -> None:
        store = ToolResultStore(":memory:")
        reset_tool_result_store(store)
        ref = store.insert(
            user_id=42,
            run_id="r1",
            tool_name="exa.web_search",
            turn=1,
            args_json="{}",
            payload_json='{"ok": true, "data": "' + ("x" * 200) + '"}',
            ok=True,
            cached=False,
        )
        store.update_summary(ref, summary="hits", summarize_status="ok", summarize_attempts=1)
        store.insert(
            user_id=99,
            run_id="r2",
            tool_name="yandex.music.tracks",
            turn=0,
            args_json="{}",
            payload_json='{"ok": true}',
            ok=True,
            cached=False,
        )

        report = format_archive_stats_section(user_id=42)
        self.assertIn("Your stored refs: **1**", report)
        self.assertIn("exa.web_search", report)
        self.assertIn("Archive (all users)", report)
        self.assertIn("Total refs: **2**", report)
        self.assertIn("Users with data: **2**", report)

    def test_global_archive_stats(self) -> None:
        store = ToolResultStore(":memory:")
        store.insert(
            user_id=1,
            run_id="r",
            tool_name="echo.test",
            turn=0,
            args_json="{}",
            payload_json='{"ok": true}',
            ok=True,
            cached=False,
        )
        reset_tool_result_store(store)
        stats = load_global_archive_stats()
        self.assertEqual(stats.row_count, 1)
        self.assertEqual(stats.user_count, 1)


if __name__ == "__main__":
    unittest.main()
