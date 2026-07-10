import json
import unittest
from unittest.mock import MagicMock, patch

from config import get_settings
from llm import LLMClient
from tools.tool_results.archive import is_archived_tool_call_arguments
from tools.tool_results.collapser import ToolResultCollapser
from tools.tool_results.store import ToolResultStore
from tools.tool_results.summarize import SUMMARIZE_STATUS_OK
from tools.tool_results.summarize_queue import reset_summarize_queue


class ToolCallArgumentsArchiveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_summarize_queue()

    def _collapser(self, store: ToolResultStore) -> ToolResultCollapser:
        settings = get_settings()
        return ToolResultCollapser(
            settings=settings,
            llm=MagicMock(spec=LLMClient),
            user_id=42,
            run_id="run1",
            store=store,
        )

    @patch.dict(
        "os.environ",
        {
            "TOOL_RESULT_ARCHIVE_ENABLED": "1",
            "TOOL_RESULT_ARCHIVE_MIN_CHARS": "150",
            "TOOL_RESULT_COLLAPSE_STALE_STEPS": "10",
            "TOOL_RESULT_DB_PATH": ":memory:",
        },
        clear=False,
    )
    async def test_registers_and_collapses_large_use_tool_arguments(self) -> None:
        store = ToolResultStore(db_path=":memory:")
        collapser = self._collapser(store)

        big_values = [["x" * 40] * 5 for _ in range(8)]
        args = {
            "tool_name": "google.sheets.update_values",
            "arguments": {
                "spreadsheet_id": "sheet123",
                "range": "R01!A1:E8",
                "values": big_values,
            },
        }
        args_str = json.dumps(args, ensure_ascii=False)
        self.assertGreater(len(args_str), 150)

        assistant = {
            "role": "assistant",
            "content": "planning",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "use_tool",
                        "arguments": args_str,
                    },
                }
            ],
        }
        messages = [assistant]

        collapser.register_assistant_tool_calls(assistant, turn=0)
        self.assertEqual(len(collapser.entries), 1)
        self.assertEqual(collapser.entries[0].kind, "arguments")

        record = store.get(1, user_id=42)
        assert record is not None
        store.update_summary(
            record.ref,
            summary="Wrote 8 rows to R01!A1:E8 in sheet sheet123.",
            summarize_status=SUMMARIZE_STATUS_OK,
            summarize_attempts=1,
        )

        collapsed = await collapser.collapse_all(messages)
        self.assertEqual(collapsed, 1)
        collapsed_args = json.loads(
            messages[0]["tool_calls"][0]["function"]["arguments"]
        )
        self.assertTrue(is_archived_tool_call_arguments(json.dumps(collapsed_args)))
        self.assertEqual(collapsed_args["ref"], 1)
        self.assertIn("summary", collapsed_args)

    @patch.dict(
        "os.environ",
        {
            "TOOL_RESULT_ARCHIVE_ENABLED": "1",
            "TOOL_RESULT_ARCHIVE_MIN_CHARS": "150",
            "TOOL_RESULT_DB_PATH": ":memory:",
        },
        clear=False,
    )
    async def test_skips_small_arguments(self) -> None:
        store = ToolResultStore(db_path=":memory:")
        collapser = self._collapser(store)
        args_str = json.dumps(
            {"tool_name": "echo.test", "arguments": {"message": "hi"}},
            ensure_ascii=False,
        )
        assistant = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {"name": "use_tool", "arguments": args_str},
                }
            ],
        }
        collapser.register_assistant_tool_calls(assistant, turn=0)
        self.assertEqual(collapser.entries, [])

    @patch.dict(
        "os.environ",
        {
            "TOOL_RESULT_ARCHIVE_ENABLED": "1",
            "TOOL_RESULT_ARCHIVE_MIN_CHARS": "150",
            "TOOL_RESULT_COLLAPSE_STALE_STEPS": "10",
            "TOOL_RESULT_DB_PATH": ":memory:",
        },
        clear=False,
    )
    async def test_stale_collapse_after_threshold(self) -> None:
        store = ToolResultStore(db_path=":memory:")
        collapser = self._collapser(store)
        args_str = json.dumps(
            {
                "tool_name": "google.sheets.update_values",
                "arguments": {"spreadsheet_id": "s", "values": [["a" * 200]]},
            },
            ensure_ascii=False,
        )
        assistant = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {"name": "use_tool", "arguments": args_str},
                }
            ],
        }
        messages = [assistant]
        collapser.register_assistant_tool_calls(assistant, turn=0)
        record = store.get(1, user_id=42)
        assert record is not None
        store.update_summary(
            record.ref,
            summary="Updated sheet s with one large row.",
            summarize_status=SUMMARIZE_STATUS_OK,
            summarize_attempts=1,
        )

        self.assertEqual(await collapser.collapse_stale(messages, current_turn=5), 0)
        self.assertEqual(await collapser.collapse_stale(messages, current_turn=10), 1)


if __name__ == "__main__":
    unittest.main()
