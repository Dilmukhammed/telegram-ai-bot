import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tools.builtins.google.auth import SHEETS_SCOPE, user_has_sheets_scope
from tools.builtins.google.sheets_a1 import quote_sheet_title, sheet_data_range
from tools.builtins.google.sheets_serialize import (
    compact_spreadsheet,
    compact_value_range,
    count_cells,
    truncate_values,
)
from tools.builtins.google.sheets_tools import (
    GOOGLE_SHEETS_TOOLS,
    SHEETS_WAVE1_TOOL_NAMES,
)
from tools.builtins.google.sheets_tools_wave2 import SHEETS_WAVE2_TOOL_NAMES
from tools.builtins.google.sheets_tools_wave3 import SHEETS_WAVE3_TOOL_NAMES
from tools.builtins.google.sheets_tools_wave4 import SHEETS_WAVE4_TOOL_NAMES
from tools.builtins.google.token_store import StoredGoogleToken
from tools.context import RunContext, reset_run_context, set_run_context


class SheetsSerializeTests(unittest.TestCase):
    def test_truncate_values(self) -> None:
        values = [["a", "b", "c"], ["d", "e", "f"]]
        trimmed, truncated = truncate_values(values, 4)
        self.assertTrue(truncated)
        self.assertEqual(count_cells(trimmed), 4)

    def test_compact_value_range_truncates(self) -> None:
        payload = compact_value_range(
            {"range": "Sheet1!A1:C2", "majorDimension": "ROWS", "values": [["1", "2"], ["3", "4"]]},
            max_cells=2,
        )
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["cell_count"], 2)

    def test_compact_spreadsheet(self) -> None:
        payload = compact_spreadsheet(
            {
                "spreadsheetId": "abc123",
                "properties": {"title": "Budget", "locale": "ru_RU", "timeZone": "Asia/Tashkent"},
                "sheets": [
                    {
                        "properties": {
                            "sheetId": 0,
                            "title": "Sheet1",
                            "index": 0,
                            "gridProperties": {"rowCount": 1000, "columnCount": 26},
                        }
                    }
                ],
            }
        )
        self.assertEqual(payload["spreadsheet_id"], "abc123")
        self.assertEqual(payload["sheet_count"], 1)


class SheetsA1Tests(unittest.TestCase):
    def test_quote_sheet_title_with_space(self) -> None:
        self.assertEqual(quote_sheet_title("My Sheet"), "'My Sheet'")

    def test_sheet_data_range(self) -> None:
        self.assertEqual(sheet_data_range("Data", max_rows=500), "Data!A1:ZZ500")
        self.assertEqual(sheet_data_range("My Sheet", max_rows=100), "'My Sheet'!A1:ZZ100")


class SheetsAuthTests(unittest.TestCase):
    def test_user_has_sheets_scope(self) -> None:
        token = StoredGoogleToken(
            telegram_user_id=1,
            email="a@b.com",
            refresh_token="r",
            access_token="a",
            token_expiry=None,
            scopes=(SHEETS_SCOPE,),
        )
        self.assertTrue(user_has_sheets_scope(token))


class SheetsRegistryTests(unittest.TestCase):
    def test_wave1_tool_count(self) -> None:
        self.assertEqual(len(SHEETS_WAVE1_TOOL_NAMES), 11)

    def test_wave2_tool_count(self) -> None:
        self.assertEqual(len(SHEETS_WAVE2_TOOL_NAMES), 9)

    def test_wave3_tool_count(self) -> None:
        self.assertEqual(len(SHEETS_WAVE3_TOOL_NAMES), 12)

    def test_wave4_tool_count(self) -> None:
        self.assertEqual(len(SHEETS_WAVE4_TOOL_NAMES), 11)

    def test_total_sheets_tool_count(self) -> None:
        self.assertEqual(len(GOOGLE_SHEETS_TOOLS), 43)

    def test_all_tools_have_sheets_tags(self) -> None:
        for tool in GOOGLE_SHEETS_TOOLS:
            self.assertIn("google", tool.tags)
            self.assertIn("sheets", tool.tags)
            self.assertTrue({"read", "write"} & set(tool.tags))
            self.assertTrue(
                {"values", "structure", "format", "data", "validation", "charts", "filters", "protection"}
                & set(tool.tags)
                or "sugar" in tool.tags
            )


class SheetsHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_values_requires_range(self) -> None:
        from tools.builtins.google.sheets_values import get_values_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await get_values_handler({"spreadsheet_id": "abc"})
        finally:
            reset_run_context(token)

    async def test_update_values_requires_values(self) -> None:
        from tools.builtins.google.sheets_values import update_values_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await update_values_handler(
                    {"spreadsheet_id": "abc", "range": "Sheet1!A1", "values": []}
                )
        finally:
            reset_run_context(token)

    async def test_read_sheet_by_title(self) -> None:
        from tools.builtins.google.sheets_values import read_sheet_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with patch(
                "tools.builtins.google.sheets_values.get_values_handler",
                new=AsyncMock(
                    return_value={
                        "spreadsheet_id": "abc",
                        "range": "Sheet1!A1:ZZ100",
                        "values": [["a"]],
                        "row_count": 1,
                        "cell_count": 1,
                    }
                ),
            ) as get_values:
                result = await read_sheet_handler(
                    {"spreadsheet_id": "abc", "sheet_title": "Sheet1", "max_rows": 100}
                )
        finally:
            reset_run_context(token)

        self.assertEqual(result["sheet_title"], "Sheet1")
        get_values.assert_awaited_once()
        call_range = get_values.await_args.args[0]["range"]
        self.assertIn("Sheet1", call_range)

    async def test_read_sheet_resolves_sheet_id(self) -> None:
        from tools.builtins.google.sheets_values import read_sheet_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with patch(
                "tools.builtins.google.sheets_values.run_sheets_call",
                new=AsyncMock(
                    return_value={
                        "sheets": [{"properties": {"sheetId": 42, "title": "Budget"}}],
                    }
                ),
            ):
                with patch(
                    "tools.builtins.google.sheets_values.get_values_handler",
                    new=AsyncMock(return_value={"values": [], "row_count": 0, "cell_count": 0}),
                ) as get_values:
                    result = await read_sheet_handler({"spreadsheet_id": "abc", "sheet_id": 42})
        finally:
            reset_run_context(token)

        self.assertEqual(result["sheet_title"], "Budget")
        get_values.assert_awaited_once()

    async def test_get_spreadsheet_handler(self) -> None:
        from tools.builtins.google.sheets_structure import get_spreadsheet_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with patch(
                "tools.builtins.google.sheets_structure.run_sheets_call",
                new=AsyncMock(
                    return_value={
                        "spreadsheetId": "sid",
                        "properties": {"title": "Test"},
                        "sheets": [],
                    }
                ),
            ):
                result = await get_spreadsheet_handler({"spreadsheet_id": "sid"})
        finally:
            reset_run_context(token)

        self.assertEqual(result["spreadsheet"]["spreadsheet_id"], "sid")
        self.assertEqual(result["spreadsheet"]["title"], "Test")

    async def test_add_sheet_handler(self) -> None:
        from tools.builtins.google.sheets_structure import add_sheet_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with patch(
                "tools.builtins.google.sheets_structure.batch_update",
                new=AsyncMock(
                    return_value={
                        "replies": [{"addSheet": {"properties": {"sheetId": 99, "title": "March"}}}],
                    }
                ),
            ):
                result = await add_sheet_handler({"spreadsheet_id": "abc", "title": "March"})
        finally:
            reset_run_context(token)

        self.assertEqual(result["sheet_id"], 99)
        self.assertEqual(result["title"], "March")

    async def test_delete_sheet_requires_confirm(self) -> None:
        from tools.builtins.google.sheets_structure import delete_sheet_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await delete_sheet_handler({"spreadsheet_id": "abc", "sheet_id": 0})
        finally:
            reset_run_context(token)

    async def test_copy_sheet_to_spreadsheet_handler(self) -> None:
        from tools.builtins.google.sheets_structure import copy_sheet_to_spreadsheet_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with patch(
                "tools.builtins.google.sheets_structure.run_sheets_call",
                new=AsyncMock(return_value={"properties": {"sheetId": 7, "title": "Copy of Budget"}}),
            ):
                result = await copy_sheet_to_spreadsheet_handler(
                    {
                        "source_spreadsheet_id": "src",
                        "sheet_id": 1,
                        "destination_spreadsheet_id": "dst",
                    }
                )
        finally:
            reset_run_context(token)

        self.assertEqual(result["destination_sheet_id"], 7)
        self.assertEqual(result["destination_sheet_title"], "Copy of Budget")

    async def test_move_dimension_requires_destination(self) -> None:
        from tools.builtins.google.sheets_structure import move_dimension_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await move_dimension_handler({"spreadsheet_id": "abc", "sheet_id": 0})
        finally:
            reset_run_context(token)

    async def test_set_borders_requires_side(self) -> None:
        from tools.builtins.google.sheets_structure import set_borders_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await set_borders_handler(
                    {
                        "spreadsheet_id": "abc",
                        "sheet_id": 0,
                        "end_row_index": 1,
                        "end_column_index": 1,
                        "outer_borders": False,
                        "inner_borders": False,
                    }
                )
        finally:
            reset_run_context(token)

    async def test_add_named_range_handler(self) -> None:
        from tools.builtins.google.sheets_structure import add_named_range_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with patch(
                "tools.builtins.google.sheets_structure.batch_update",
                new=AsyncMock(
                    return_value={
                        "replies": [
                            {"addNamedRange": {"namedRange": {"namedRangeId": "nr123", "name": "Totals"}}}
                        ],
                    }
                ),
            ):
                result = await add_named_range_handler(
                    {
                        "spreadsheet_id": "abc",
                        "name": "Totals",
                        "sheet_id": 0,
                        "end_row_index": 10,
                        "end_column_index": 3,
                    }
                )
        finally:
            reset_run_context(token)

        self.assertEqual(result["named_range_id"], "nr123")
        self.assertEqual(result["name"], "Totals")

    async def test_find_replace_requires_find(self) -> None:
        from tools.builtins.google.sheets_structure import find_replace_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await find_replace_handler({"spreadsheet_id": "abc", "find": ""})
        finally:
            reset_run_context(token)

    async def test_set_data_validation_requires_list_values(self) -> None:
        from tools.builtins.google.sheets_advanced import set_data_validation_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await set_data_validation_handler(
                    {
                        "spreadsheet_id": "abc",
                        "sheet_id": 0,
                        "end_row_index": 10,
                        "end_column_index": 1,
                        "condition_type": "ONE_OF_LIST",
                    }
                )
        finally:
            reset_run_context(token)

    async def test_add_protected_range_handler(self) -> None:
        from tools.builtins.google.sheets_advanced import add_protected_range_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with patch(
                "tools.builtins.google.sheets_advanced.batch_update",
                new=AsyncMock(
                    return_value={
                        "replies": [
                            {"addProtectedRange": {"protectedRange": {"protectedRangeId": 55}}}
                        ],
                    }
                ),
            ):
                result = await add_protected_range_handler(
                    {
                        "spreadsheet_id": "abc",
                        "sheet_id": 0,
                        "end_row_index": 1,
                        "end_column_index": 5,
                        "description": "Header",
                    }
                )
        finally:
            reset_run_context(token)

        self.assertEqual(result["protected_range_id"], 55)

    async def test_add_chart_handler(self) -> None:
        from tools.builtins.google.sheets_advanced import add_chart_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with patch(
                "tools.builtins.google.sheets_advanced.batch_update",
                new=AsyncMock(
                    return_value={"replies": [{"addChart": {"chart": {"chartId": 999}}}]},
                ),
            ):
                result = await add_chart_handler(
                    {
                        "spreadsheet_id": "abc",
                        "sheet_id": 0,
                        "start_row_index": 0,
                        "end_row_index": 5,
                        "start_column_index": 0,
                        "end_column_index": 3,
                        "chart_type": "COLUMN",
                    }
                )
        finally:
            reset_run_context(token)

        self.assertEqual(result["chart_id"], 999)


if __name__ == "__main__":
    unittest.main()
