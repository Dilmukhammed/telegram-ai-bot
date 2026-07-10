from __future__ import annotations

from tools.builtins.google.sheets_structure import (
    add_sheet_handler,
    copy_sheet_to_spreadsheet_handler,
    delete_dimension_handler,
    delete_sheet_handler,
    duplicate_sheet_handler,
    insert_dimension_handler,
    move_dimension_handler,
    update_dimension_properties_handler,
    update_sheet_properties_handler,
)
from tools.builtins.google.tool_hints import GOOGLE_SHEETS_OAUTH_HINT
from tools.builtins.google.sheets_checker import SHEETS_CHECKER_QUESTIONS_BY_TOOL
from tools.schema import ToolSpec

_WRITE_RATE_LIMIT = (60, 60)

_SPREADSHEET_ID = {
    "type": "string",
    "description": "Spreadsheet id from drive.search_files or URL (.../spreadsheets/d/{id}/edit).",
}
_SHEET_ID = {
    "type": "integer",
    "description": "Numeric tab id from get_spreadsheet (sheets[].sheet_id).",
}
_CONFIRM_PARAM = {
    "type": "boolean",
    "description": "Must be true — irreversible destructive operation.",
}
_DIMENSION = {
    "type": "string",
    "enum": ["ROWS", "COLUMNS"],
    "default": "ROWS",
    "description": "ROWS for row operations, COLUMNS for column operations.",
}

GOOGLE_SHEETS_ADD_SHEET = ToolSpec(
    name="google.sheets.add_sheet",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Add a NEW worksheet tab to an existing spreadsheet. "
        "NOT for creating a new file — create_spreadsheet. NOT for copying a tab — duplicate_sheet."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "title": {"type": "string", "description": "Tab name (default Sheet)."},
            "row_count": {"type": "integer", "default": 1000},
            "column_count": {"type": "integer", "default": 26},
            "index": {"type": "integer", "description": "Zero-based tab position."},
        },
        "required": ["spreadsheet_id"],
    },
    handler=add_sheet_handler,
    tags=("google", "sheets", "write", "structure"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("add worksheet tab", "new sheet March", "create tab in spreadsheet"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.add_sheet"],
)

GOOGLE_SHEETS_DELETE_SHEET = ToolSpec(
    name="google.sheets.delete_sheet",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Permanently DELETE a worksheet tab. Requires confirm=true. "
        "NOT for clearing cell values — clear_values. NOT for deleting the whole file — drive.trash_file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "sheet_id": _SHEET_ID,
            "confirm": _CONFIRM_PARAM,
        },
        "required": ["spreadsheet_id", "sheet_id", "confirm"],
    },
    handler=delete_sheet_handler,
    tags=("google", "sheets", "write", "structure"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("delete worksheet tab", "remove sheet from spreadsheet"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.delete_sheet"],
)

GOOGLE_SHEETS_DUPLICATE_SHEET = ToolSpec(
    name="google.sheets.duplicate_sheet",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Duplicate a tab WITHIN the same spreadsheet (copy worksheet template). "
        "NOT for copying to another file — copy_sheet_to_spreadsheet. NOT for copying whole file — drive.copy_file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "sheet_id": _SHEET_ID,
            "new_sheet_name": {"type": "string", "description": "Name for the copy."},
            "insert_sheet_index": {"type": "integer", "description": "Where to place the new tab."},
        },
        "required": ["spreadsheet_id", "sheet_id"],
    },
    handler=duplicate_sheet_handler,
    tags=("google", "sheets", "write", "structure"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("duplicate sheet tab", "copy worksheet template", "clone tab in same file"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.duplicate_sheet"],
)

GOOGLE_SHEETS_COPY_SHEET_TO_SPREADSHEET = ToolSpec(
    name="google.sheets.copy_sheet_to_spreadsheet",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Copy a worksheet tab to a DIFFERENT spreadsheet file. "
        "NOT for duplicate within same file — duplicate_sheet. NOT for copying whole file — drive.copy_file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "source_spreadsheet_id": {
                "type": "string",
                "description": "Spreadsheet id containing the source tab.",
            },
            "sheet_id": _SHEET_ID,
            "destination_spreadsheet_id": {
                "type": "string",
                "description": "Target spreadsheet id (can be same or different file).",
            },
        },
        "required": ["source_spreadsheet_id", "sheet_id", "destination_spreadsheet_id"],
    },
    handler=copy_sheet_to_spreadsheet_handler,
    tags=("google", "sheets", "write", "structure"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("copy sheet to another spreadsheet", "move tab to different file"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.copy_sheet_to_spreadsheet"],
)

GOOGLE_SHEETS_UPDATE_SHEET_PROPERTIES = ToolSpec(
    name="google.sheets.update_sheet_properties",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Rename tab, hide/show worksheet, reorder tabs, freeze header rows/columns. "
        "NOT for renaming the spreadsheet file — update_spreadsheet_properties."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "sheet_id": _SHEET_ID,
            "title": {"type": "string", "description": "New tab name."},
            "hidden": {"type": "boolean", "description": "Hide tab from UI."},
            "index": {"type": "integer", "description": "Zero-based tab order."},
            "frozen_row_count": {"type": "integer", "description": "Freeze top N rows."},
            "frozen_column_count": {"type": "integer", "description": "Freeze left N columns."},
        },
        "required": ["spreadsheet_id", "sheet_id"],
    },
    handler=update_sheet_properties_handler,
    tags=("google", "sheets", "write", "structure"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("rename sheet tab", "hide worksheet", "freeze first row", "reorder tabs"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.update_sheet_properties"],
)

GOOGLE_SHEETS_INSERT_DIMENSION = ToolSpec(
    name="google.sheets.insert_dimension",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Insert BLANK rows or columns (shifts existing content). "
        "NOT for appending data rows — append_values."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "sheet_id": _SHEET_ID,
            "dimension": _DIMENSION,
            "start_index": {"type": "integer", "default": 0, "description": "First row/col to insert (0-based)."},
            "end_index": {
                "type": "integer",
                "description": "Exclusive end index (insert count = end - start).",
            },
            "inherit_from_before": {
                "type": "boolean",
                "default": True,
                "description": "Copy format from cell before insertion point.",
            },
        },
        "required": ["spreadsheet_id", "sheet_id"],
    },
    handler=insert_dimension_handler,
    tags=("google", "sheets", "write", "structure"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("insert rows", "add blank columns", "insert 5 rows at row 3"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.insert_dimension"],
)

GOOGLE_SHEETS_DELETE_DIMENSION = ToolSpec(
    name="google.sheets.delete_dimension",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Delete rows or columns (shifts remaining content). Requires confirm=true. "
        "NOT for clearing cell values — clear_values."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "sheet_id": _SHEET_ID,
            "dimension": _DIMENSION,
            "start_index": {"type": "integer", "default": 0},
            "end_index": {"type": "integer", "description": "Exclusive end index."},
            "confirm": _CONFIRM_PARAM,
        },
        "required": ["spreadsheet_id", "sheet_id", "confirm"],
    },
    handler=delete_dimension_handler,
    tags=("google", "sheets", "write", "structure"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("delete rows 5-10", "remove column C", "delete columns D-F"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.delete_dimension"],
)

GOOGLE_SHEETS_MOVE_DIMENSION = ToolSpec(
    name="google.sheets.move_dimension",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Move a block of rows or columns to a new position. "
        "Use for reordering columns or moving row blocks."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "sheet_id": _SHEET_ID,
            "dimension": _DIMENSION,
            "source_start": {"type": "integer", "default": 0},
            "source_end": {"type": "integer", "description": "Exclusive end of block to move."},
            "destination_index": {
                "type": "integer",
                "description": "Target index where the block will be inserted.",
            },
        },
        "required": ["spreadsheet_id", "sheet_id", "destination_index"],
    },
    handler=move_dimension_handler,
    tags=("google", "sheets", "write", "structure"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("move rows", "reorder columns", "move column block"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.move_dimension"],
)

GOOGLE_SHEETS_UPDATE_DIMENSION_PROPERTIES = ToolSpec(
    name="google.sheets.update_dimension_properties",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Set row height or column width (pixels), or hide rows/columns. "
        "NOT for cell formatting — format_cells (Sheets-3). NOT auto-fit — auto_resize_columns (Sheets-3)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "sheet_id": _SHEET_ID,
            "dimension": _DIMENSION,
            "start_index": {"type": "integer", "default": 0},
            "end_index": {"type": "integer"},
            "pixel_size": {"type": "integer", "description": "Height/width in pixels."},
            "hidden": {"type": "boolean", "description": "Hide rows or columns."},
        },
        "required": ["spreadsheet_id", "sheet_id"],
    },
    handler=update_dimension_properties_handler,
    tags=("google", "sheets", "write", "structure", "format"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("set column width", "hide columns D-F", "set row height"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.update_dimension_properties"],
)

SHEETS_WAVE2_TOOL_NAMES: tuple[str, ...] = tuple(
    tool.name
    for tool in (
        GOOGLE_SHEETS_ADD_SHEET,
        GOOGLE_SHEETS_DELETE_SHEET,
        GOOGLE_SHEETS_DUPLICATE_SHEET,
        GOOGLE_SHEETS_COPY_SHEET_TO_SPREADSHEET,
        GOOGLE_SHEETS_UPDATE_SHEET_PROPERTIES,
        GOOGLE_SHEETS_INSERT_DIMENSION,
        GOOGLE_SHEETS_DELETE_DIMENSION,
        GOOGLE_SHEETS_MOVE_DIMENSION,
        GOOGLE_SHEETS_UPDATE_DIMENSION_PROPERTIES,
    )
)

GOOGLE_SHEETS_WAVE2_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_SHEETS_ADD_SHEET,
    GOOGLE_SHEETS_DELETE_SHEET,
    GOOGLE_SHEETS_DUPLICATE_SHEET,
    GOOGLE_SHEETS_COPY_SHEET_TO_SPREADSHEET,
    GOOGLE_SHEETS_UPDATE_SHEET_PROPERTIES,
    GOOGLE_SHEETS_INSERT_DIMENSION,
    GOOGLE_SHEETS_DELETE_DIMENSION,
    GOOGLE_SHEETS_MOVE_DIMENSION,
    GOOGLE_SHEETS_UPDATE_DIMENSION_PROPERTIES,
)
