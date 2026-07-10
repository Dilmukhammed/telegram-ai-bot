from __future__ import annotations

from tools.builtins.google.sheets_structure import (
    create_spreadsheet_handler,
    get_spreadsheet_handler,
    update_spreadsheet_properties_handler,
)
from tools.builtins.google.sheets_values import (
    append_values_handler,
    batch_clear_values_handler,
    batch_get_values_handler,
    batch_update_values_handler,
    clear_values_handler,
    get_values_handler,
    read_sheet_handler,
    update_values_handler,
)
from tools.builtins.google.sheets_checker import SHEETS_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.google.sheets_tools_wave2 import GOOGLE_SHEETS_WAVE2_TOOLS, SHEETS_WAVE2_TOOL_NAMES
from tools.builtins.google.sheets_tools_wave3 import GOOGLE_SHEETS_WAVE3_TOOLS, SHEETS_WAVE3_TOOL_NAMES
from tools.builtins.google.sheets_tools_wave4 import GOOGLE_SHEETS_WAVE4_TOOLS, SHEETS_WAVE4_TOOL_NAMES
from tools.builtins.google.tool_hints import GOOGLE_SHEETS_OAUTH_HINT
from tools.schema import ToolSpec

_READ_RATE_LIMIT = (120, 60)
_WRITE_RATE_LIMIT = (60, 60)

_SPREADSHEET_ID = {
    "type": "string",
    "description": "Spreadsheet id from drive.search_files or URL (.../spreadsheets/d/{id}/edit).",
}
_RANGE = {
    "type": "string",
    "description": "A1 notation, e.g. Sheet1!A1:D10 or Budget!B:B.",
}
_VALUE_INPUT_OPTION = {
    "type": "string",
    "enum": ["RAW", "USER_ENTERED"],
    "default": "USER_ENTERED",
    "description": "USER_ENTERED parses formulas/dates; RAW stores literals.",
}
_VALUE_RENDER_OPTION = {
    "type": "string",
    "enum": ["FORMATTED_VALUE", "UNFORMATTED_VALUE", "FORMULA"],
    "default": "FORMATTED_VALUE",
}

GOOGLE_SHEETS_GET_SPREADSHEET = ToolSpec(
    name="google.sheets.get_spreadsheet",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Get spreadsheet metadata: file title, tab names, numeric sheet_id, grid sizes. "
        "Use FIRST after drive.search_files when you have spreadsheet_id. "
        "NOT for cell values — use get_values or read_sheet. NOT for finding files — use drive.search_files."
    ),
    parameters={
        "type": "object",
        "properties": {"spreadsheet_id": _SPREADSHEET_ID},
        "required": ["spreadsheet_id"],
    },
    handler=get_spreadsheet_handler,
    tags=("google", "sheets", "read", "structure"),
    cache_ttl_seconds=30,
    rate_limit=_READ_RATE_LIMIT,
    examples=("list sheet tabs", "sheet ids for workbook", "spreadsheet metadata"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.get_spreadsheet"],
)

GOOGLE_SHEETS_CREATE_SPREADSHEET = ToolSpec(
    name="google.sheets.create_spreadsheet",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Create a NEW Google Spreadsheet file. "
        "NOT for adding a tab to existing file — that is add_sheet (Sheets-2). "
        "NOT for copying a file — use drive.copy_file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Spreadsheet title."},
            "sheet_titles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional initial tab names.",
            },
        },
    },
    handler=create_spreadsheet_handler,
    tags=("google", "sheets", "write", "structure"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("create new spreadsheet", "new google sheet budget 2026"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.create_spreadsheet"],
)

GOOGLE_SHEETS_UPDATE_SPREADSHEET_PROPERTIES = ToolSpec(
    name="google.sheets.update_spreadsheet_properties",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Rename the spreadsheet FILE, or set workbook locale/timezone. "
        "NOT for renaming a tab — use update_sheet_properties (Sheets-2)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "title": {"type": "string"},
            "locale": {"type": "string", "description": "e.g. ru_RU, en_US"},
            "time_zone": {"type": "string", "description": "e.g. Asia/Tashkent"},
        },
        "required": ["spreadsheet_id"],
    },
    handler=update_spreadsheet_properties_handler,
    tags=("google", "sheets", "write", "structure"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("rename spreadsheet file", "set spreadsheet timezone"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.update_spreadsheet_properties"],
)

GOOGLE_SHEETS_GET_VALUES = ToolSpec(
    name="google.sheets.get_values",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Read ONE A1 range (Sheet1!A1:D10). Main read tool for specific cells. "
        "For multiple ranges use batch_get_values. For whole tab use read_sheet. "
        "NOT for finding the file — drive.search_files. NOT whole-file CSV — drive.export_file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "range": _RANGE,
            "value_render_option": _VALUE_RENDER_OPTION,
            "major_dimension": {"type": "string", "enum": ["ROWS", "COLUMNS"], "default": "ROWS"},
        },
        "required": ["spreadsheet_id", "range"],
    },
    handler=get_values_handler,
    tags=("google", "sheets", "read", "values"),
    cache_ttl_seconds=15,
    rate_limit=_READ_RATE_LIMIT,
    examples=("read cells A1 to D10", "get values from sheet range", "read spreadsheet column B"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.get_values"],
)

GOOGLE_SHEETS_READ_SHEET = ToolSpec(
    name="google.sheets.read_sheet",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Read an entire worksheet tab (up to max_rows). Sugar over get_values. "
        "Use when user wants all data from Sheet1. For one small range use get_values. "
        "Provide sheet_title or sheet_id from get_spreadsheet."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "sheet_title": {"type": "string", "description": "Tab name, e.g. Sheet1."},
            "sheet_id": {
                "type": "integer",
                "description": "Numeric tab id from get_spreadsheet (if title unknown).",
            },
            "max_rows": {"type": "integer", "default": 1000, "description": "Cap rows (max 10000)."},
            "value_render_option": _VALUE_RENDER_OPTION,
        },
        "required": ["spreadsheet_id"],
    },
    handler=read_sheet_handler,
    tags=("google", "sheets", "read", "values", "sugar"),
    cache_ttl_seconds=15,
    rate_limit=_READ_RATE_LIMIT,
    examples=("read entire sheet", "dump worksheet data", "show all rows in Sheet1"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.read_sheet"],
)

GOOGLE_SHEETS_BATCH_GET_VALUES = ToolSpec(
    name="google.sheets.batch_get_values",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Read MULTIPLE A1 ranges in one API call (faster than several get_values). "
        "NOT for a single range — use get_values."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "ranges": {"type": "array", "items": {"type": "string"}},
            "value_render_option": _VALUE_RENDER_OPTION,
            "major_dimension": {"type": "string", "enum": ["ROWS", "COLUMNS"], "default": "ROWS"},
        },
        "required": ["spreadsheet_id", "ranges"],
    },
    handler=batch_get_values_handler,
    tags=("google", "sheets", "read", "values"),
    cache_ttl_seconds=15,
    rate_limit=_READ_RATE_LIMIT,
    examples=("read multiple ranges", "get headers and totals from different sheets"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.batch_get_values"],
)

GOOGLE_SHEETS_UPDATE_VALUES = ToolSpec(
    name="google.sheets.update_values",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "OVERWRITE cells in one A1 range (write table, update cell, set formulas). "
        "NOT for appending rows — use append_values. NOT for multiple ranges — batch_update_values."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "range": _RANGE,
            "values": {
                "type": "array",
                "items": {"type": "array", "items": {}},
                "description": "2D array of cell values.",
            },
            "value_input_option": _VALUE_INPUT_OPTION,
        },
        "required": ["spreadsheet_id", "range", "values"],
    },
    handler=update_values_handler,
    tags=("google", "sheets", "write", "values"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("write to cells", "update spreadsheet range", "set cell B5 to 100", "put formula in C1"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.update_values"],
)

GOOGLE_SHEETS_APPEND_VALUES = ToolSpec(
    name="google.sheets.append_values",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "ADD rows at the end of a sheet (log entry, new record). "
        "NOT for overwriting existing cells — update_values. NOT for blank rows — insert_dimension (Sheets-2)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "range": {"type": "string", "default": "Sheet1", "description": "Tab name or A1 anchor."},
            "values": {
                "type": "array",
                "items": {"type": "array", "items": {}},
            },
            "value_input_option": _VALUE_INPUT_OPTION,
            "insert_data_option": {
                "type": "string",
                "enum": ["INSERT_ROWS", "OVERWRITE"],
                "default": "INSERT_ROWS",
            },
        },
        "required": ["spreadsheet_id", "values"],
    },
    handler=append_values_handler,
    tags=("google", "sheets", "write", "values"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("append row to sheet", "add new entry to spreadsheet", "log data to google sheet"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.append_values"],
)

GOOGLE_SHEETS_CLEAR_VALUES = ToolSpec(
    name="google.sheets.clear_values",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Clear cell VALUES in a range (formatting stays). "
        "NOT delete rows — delete_dimension (Sheets-2). NOT delete tab — delete_sheet (Sheets-2)."
    ),
    parameters={
        "type": "object",
        "properties": {"spreadsheet_id": _SPREADSHEET_ID, "range": _RANGE},
        "required": ["spreadsheet_id", "range"],
    },
    handler=clear_values_handler,
    tags=("google", "sheets", "write", "values"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("clear cells", "erase range A2:D100"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.clear_values"],
)

GOOGLE_SHEETS_BATCH_UPDATE_VALUES = ToolSpec(
    name="google.sheets.batch_update_values",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Write to MULTIPLE ranges atomically. NOT for one range — update_values."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "data": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "range": {"type": "string"},
                        "values": {"type": "array", "items": {"type": "array", "items": {}}},
                    },
                    "required": ["range", "values"],
                },
            },
            "value_input_option": _VALUE_INPUT_OPTION,
        },
        "required": ["spreadsheet_id", "data"],
    },
    handler=batch_update_values_handler,
    tags=("google", "sheets", "write", "values"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("batch update cells", "write headers and footer in one call"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.batch_update_values"],
)

GOOGLE_SHEETS_BATCH_CLEAR_VALUES = ToolSpec(
    name="google.sheets.batch_clear_values",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Clear values in multiple ranges at once. NOT for one range — clear_values."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "ranges": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["spreadsheet_id", "ranges"],
    },
    handler=batch_clear_values_handler,
    tags=("google", "sheets", "write", "values"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("clear multiple ranges", "reset several sections"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.batch_clear_values"],
)

SHEETS_WAVE1_TOOL_NAMES: tuple[str, ...] = tuple(
    tool.name
    for tool in (
        GOOGLE_SHEETS_GET_SPREADSHEET,
        GOOGLE_SHEETS_CREATE_SPREADSHEET,
        GOOGLE_SHEETS_UPDATE_SPREADSHEET_PROPERTIES,
        GOOGLE_SHEETS_GET_VALUES,
        GOOGLE_SHEETS_READ_SHEET,
        GOOGLE_SHEETS_BATCH_GET_VALUES,
        GOOGLE_SHEETS_UPDATE_VALUES,
        GOOGLE_SHEETS_APPEND_VALUES,
        GOOGLE_SHEETS_CLEAR_VALUES,
        GOOGLE_SHEETS_BATCH_UPDATE_VALUES,
        GOOGLE_SHEETS_BATCH_CLEAR_VALUES,
    )
)

GOOGLE_SHEETS_WAVE1_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_SHEETS_GET_SPREADSHEET,
    GOOGLE_SHEETS_CREATE_SPREADSHEET,
    GOOGLE_SHEETS_UPDATE_SPREADSHEET_PROPERTIES,
    GOOGLE_SHEETS_GET_VALUES,
    GOOGLE_SHEETS_READ_SHEET,
    GOOGLE_SHEETS_BATCH_GET_VALUES,
    GOOGLE_SHEETS_UPDATE_VALUES,
    GOOGLE_SHEETS_APPEND_VALUES,
    GOOGLE_SHEETS_CLEAR_VALUES,
    GOOGLE_SHEETS_BATCH_UPDATE_VALUES,
    GOOGLE_SHEETS_BATCH_CLEAR_VALUES,
)

# All 4 waves shipped — full Sheets catalog (43 tools).
GOOGLE_SHEETS_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_SHEETS_WAVE1_TOOLS
    + GOOGLE_SHEETS_WAVE2_TOOLS
    + GOOGLE_SHEETS_WAVE3_TOOLS
    + GOOGLE_SHEETS_WAVE4_TOOLS
)
