from __future__ import annotations

from tools.builtins.google.sheets_structure import (
    add_named_range_handler,
    auto_resize_columns_handler,
    auto_resize_rows_handler,
    copy_paste_range_handler,
    cut_paste_range_handler,
    delete_named_range_handler,
    find_replace_handler,
    format_cells_handler,
    merge_cells_handler,
    set_borders_handler,
    sort_range_handler,
    unmerge_cells_handler,
)
from tools.builtins.google.tool_hints import GOOGLE_SHEETS_OAUTH_HINT
from tools.schema import ToolSpec

_WRITE_RATE_LIMIT = (30, 60)

_SPREADSHEET_ID = {
    "type": "string",
    "description": "Spreadsheet id from drive.search_files or URL (.../spreadsheets/d/{id}/edit).",
}
_SHEET_ID = {
    "type": "integer",
    "description": "Numeric tab id from get_spreadsheet (sheets[].sheet_id).",
}
_GRID_RANGE = {
    "sheet_id": _SHEET_ID,
    "start_row_index": {"type": "integer", "default": 0, "description": "0-based start row (inclusive)."},
    "end_row_index": {"type": "integer", "description": "0-based end row (exclusive)."},
    "start_column_index": {"type": "integer", "default": 0, "description": "0-based start column (inclusive)."},
    "end_column_index": {"type": "integer", "description": "0-based end column (exclusive)."},
}
_MERGE_TYPE = {
    "type": "string",
    "enum": ["MERGE_ALL", "MERGE_COLUMNS", "MERGE_ROWS"],
    "default": "MERGE_ALL",
}
_PASTE_TYPE = {
    "type": "string",
    "enum": ["PASTE_NORMAL", "PASTE_VALUES", "PASTE_FORMAT", "PASTE_FORMULA"],
    "default": "PASTE_NORMAL",
}
_RGB_COLOR = {
    "type": "object",
    "properties": {
        "red": {"type": "number", "minimum": 0, "maximum": 1},
        "green": {"type": "number", "minimum": 0, "maximum": 1},
        "blue": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "description": "RGB color components 0..1.",
}

GOOGLE_SHEETS_MERGE_CELLS = ToolSpec(
    name="google.sheets.merge_cells",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Merge a rectangular cell range (e.g. header row A1:D1). "
        "NOT for unmerge — unmerge_cells. NOT for copy/move — copy_paste_range / cut_paste_range."
    ),
    parameters={
        "type": "object",
        "properties": {"spreadsheet_id": _SPREADSHEET_ID, "merge_type": _MERGE_TYPE, **_GRID_RANGE},
        "required": ["spreadsheet_id", "sheet_id", "end_row_index", "end_column_index"],
    },
    handler=merge_cells_handler,
    tags=("google", "sheets", "write", "format"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("merge header cells", "merge cells A1:D1"),
)

GOOGLE_SHEETS_UNMERGE_CELLS = ToolSpec(
    name="google.sheets.unmerge_cells",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Split previously merged cells back into individual cells. "
        "NOT for merge — merge_cells."
    ),
    parameters={
        "type": "object",
        "properties": {"spreadsheet_id": _SPREADSHEET_ID, **_GRID_RANGE},
        "required": ["spreadsheet_id", "sheet_id", "end_row_index", "end_column_index"],
    },
    handler=unmerge_cells_handler,
    tags=("google", "sheets", "write", "format"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("unmerge cells", "split merged header"),
)

GOOGLE_SHEETS_FORMAT_CELLS = ToolSpec(
    name="google.sheets.format_cells",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Apply cell formatting: bold, italic, font size, number format (currency/percent/date), background color. "
        "NOT for borders only — set_borders. NOT for column width — update_dimension_properties."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            **_GRID_RANGE,
            "bold": {"type": "boolean"},
            "italic": {"type": "boolean"},
            "font_size": {"type": "integer"},
            "number_format_type": {
                "type": "string",
                "description": "e.g. NUMBER, CURRENCY, PERCENT, DATE, TEXT.",
            },
            "number_format_pattern": {"type": "string", "description": "Custom pattern e.g. #,##0.00."},
            "background_color": _RGB_COLOR,
        },
        "required": ["spreadsheet_id", "sheet_id", "end_row_index", "end_column_index"],
    },
    handler=format_cells_handler,
    tags=("google", "sheets", "write", "format"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("bold header row", "format as currency", "highlight cells yellow"),
)

GOOGLE_SHEETS_SET_BORDERS = ToolSpec(
    name="google.sheets.set_borders",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Add grid borders around/outside/inside a cell range. "
        "NOT for font/color formatting — format_cells."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            **_GRID_RANGE,
            "border_style": {
                "type": "string",
                "enum": ["SOLID", "DASHED", "DOTTED", "DOUBLE", "NONE"],
                "default": "SOLID",
            },
            "border_width": {"type": "integer", "default": 1},
            "border_color": _RGB_COLOR,
            "outer_borders": {"type": "boolean", "default": True},
            "inner_borders": {"type": "boolean", "default": False},
        },
        "required": ["spreadsheet_id", "sheet_id", "end_row_index", "end_column_index"],
    },
    handler=set_borders_handler,
    tags=("google", "sheets", "write", "format"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("add borders to table", "grid lines around range"),
)

GOOGLE_SHEETS_AUTO_RESIZE_COLUMNS = ToolSpec(
    name="google.sheets.auto_resize_columns",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Auto-fit column width to cell content. "
        "NOT for manual pixel width — update_dimension_properties. NOT for rows — auto_resize_rows."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "sheet_id": _SHEET_ID,
            "start_column_index": {"type": "integer", "default": 0},
            "end_column_index": {"type": "integer"},
        },
        "required": ["spreadsheet_id", "sheet_id"],
    },
    handler=auto_resize_columns_handler,
    tags=("google", "sheets", "write", "format"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("auto fit columns", "resize columns to content"),
)

GOOGLE_SHEETS_AUTO_RESIZE_ROWS = ToolSpec(
    name="google.sheets.auto_resize_rows",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Auto-fit row height to cell content. NOT for columns — auto_resize_columns."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "sheet_id": _SHEET_ID,
            "start_row_index": {"type": "integer", "default": 0},
            "end_row_index": {"type": "integer"},
        },
        "required": ["spreadsheet_id", "sheet_id"],
    },
    handler=auto_resize_rows_handler,
    tags=("google", "sheets", "write", "format"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("auto fit row height", "resize rows to content"),
)

_COPY_PASTE_GRID = {
    "sheet_id": _SHEET_ID,
    "source_start_row_index": {"type": "integer", "default": 0},
    "source_end_row_index": {"type": "integer"},
    "source_start_column_index": {"type": "integer", "default": 0},
    "source_end_column_index": {"type": "integer"},
    "dest_start_row_index": {"type": "integer", "default": 0},
    "dest_end_row_index": {"type": "integer"},
    "dest_start_column_index": {"type": "integer", "default": 0},
    "dest_end_column_index": {"type": "integer"},
}

GOOGLE_SHEETS_COPY_PASTE_RANGE = ToolSpec(
    name="google.sheets.copy_paste_range",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Copy a cell block and paste elsewhere (values, format, formulas, or all). "
        "NOT for move — cut_paste_range. NOT for single-cell write — update_values."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "paste_type": _PASTE_TYPE,
            **_COPY_PASTE_GRID,
        },
        "required": [
            "spreadsheet_id",
            "sheet_id",
            "source_end_row_index",
            "source_end_column_index",
            "dest_end_row_index",
            "dest_end_column_index",
        ],
    },
    handler=copy_paste_range_handler,
    tags=("google", "sheets", "write", "format", "data"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("copy range to another place", "duplicate table block", "copy format only"),
)

GOOGLE_SHEETS_CUT_PASTE_RANGE = ToolSpec(
    name="google.sheets.cut_paste_range",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Cut (move) a cell block to a new location. "
        "NOT for copy while keeping source — copy_paste_range."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "paste_type": _PASTE_TYPE,
            **_COPY_PASTE_GRID,
        },
        "required": [
            "spreadsheet_id",
            "sheet_id",
            "source_end_row_index",
            "source_end_column_index",
            "dest_end_row_index",
            "dest_end_column_index",
        ],
    },
    handler=cut_paste_range_handler,
    tags=("google", "sheets", "write", "data"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("move cell block", "cut and paste range", "relocate table section"),
)

GOOGLE_SHEETS_SORT_RANGE = ToolSpec(
    name="google.sheets.sort_range",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Sort a table range by one or more columns ASC/DESC. "
        "NOT for find/replace text — find_replace."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            **_GRID_RANGE,
            "sort_specs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "dimension_index": {
                            "type": "integer",
                            "description": "0-based column index within range.",
                        },
                        "sort_order": {"type": "string", "enum": ["ASCENDING", "DESCENDING"]},
                    },
                    "required": ["dimension_index", "sort_order"],
                },
            },
        },
        "required": ["spreadsheet_id", "sheet_id", "end_row_index", "end_column_index", "sort_specs"],
    },
    handler=sort_range_handler,
    tags=("google", "sheets", "write", "data"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("sort by column B descending", "sort table alphabetically"),
)

GOOGLE_SHEETS_FIND_REPLACE = ToolSpec(
    name="google.sheets.find_replace",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Bulk find/replace text across a sheet or entire workbook. "
        "NOT for sorting — sort_range. NOT for single cell — update_values."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "find": {"type": "string"},
            "replace": {"type": "string", "default": ""},
            "sheet_id": {"type": "integer", "description": "Limit to one tab; omit for all sheets."},
            "match_case": {"type": "boolean", "default": False},
            "match_entire_cell": {"type": "boolean", "default": False},
            "search_by_regex": {"type": "boolean", "default": False},
        },
        "required": ["spreadsheet_id", "find"],
    },
    handler=find_replace_handler,
    tags=("google", "sheets", "write", "data"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("replace all USD with UZS", "find and replace in sheet"),
)

GOOGLE_SHEETS_ADD_NAMED_RANGE = ToolSpec(
    name="google.sheets.add_named_range",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Create a named range for formulas (e.g. =SUM(Budget_Q1)). "
        "NOT for deleting — delete_named_range."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "name": {"type": "string", "description": "Range name (no spaces recommended)."},
            **_GRID_RANGE,
        },
        "required": ["spreadsheet_id", "name", "sheet_id", "end_row_index", "end_column_index"],
    },
    handler=add_named_range_handler,
    tags=("google", "sheets", "write", "data"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("create named range", "define range name Totals"),
)

GOOGLE_SHEETS_DELETE_NAMED_RANGE = ToolSpec(
    name="google.sheets.delete_named_range",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Remove a named range by id. NOT for clearing cell values — clear_values."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "named_range_id": {
                "type": "string",
                "description": "Id from add_named_range or get_spreadsheet namedRanges.",
            },
        },
        "required": ["spreadsheet_id", "named_range_id"],
    },
    handler=delete_named_range_handler,
    tags=("google", "sheets", "write", "data"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("delete named range", "remove range name Totals"),
)

SHEETS_WAVE3_TOOL_NAMES: tuple[str, ...] = tuple(
    tool.name
    for tool in (
        GOOGLE_SHEETS_MERGE_CELLS,
        GOOGLE_SHEETS_UNMERGE_CELLS,
        GOOGLE_SHEETS_FORMAT_CELLS,
        GOOGLE_SHEETS_SET_BORDERS,
        GOOGLE_SHEETS_AUTO_RESIZE_COLUMNS,
        GOOGLE_SHEETS_AUTO_RESIZE_ROWS,
        GOOGLE_SHEETS_COPY_PASTE_RANGE,
        GOOGLE_SHEETS_CUT_PASTE_RANGE,
        GOOGLE_SHEETS_SORT_RANGE,
        GOOGLE_SHEETS_FIND_REPLACE,
        GOOGLE_SHEETS_ADD_NAMED_RANGE,
        GOOGLE_SHEETS_DELETE_NAMED_RANGE,
    )
)

GOOGLE_SHEETS_WAVE3_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_SHEETS_MERGE_CELLS,
    GOOGLE_SHEETS_UNMERGE_CELLS,
    GOOGLE_SHEETS_FORMAT_CELLS,
    GOOGLE_SHEETS_SET_BORDERS,
    GOOGLE_SHEETS_AUTO_RESIZE_COLUMNS,
    GOOGLE_SHEETS_AUTO_RESIZE_ROWS,
    GOOGLE_SHEETS_COPY_PASTE_RANGE,
    GOOGLE_SHEETS_CUT_PASTE_RANGE,
    GOOGLE_SHEETS_SORT_RANGE,
    GOOGLE_SHEETS_FIND_REPLACE,
    GOOGLE_SHEETS_ADD_NAMED_RANGE,
    GOOGLE_SHEETS_DELETE_NAMED_RANGE,
)
