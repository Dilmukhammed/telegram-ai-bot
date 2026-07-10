from __future__ import annotations

from tools.builtins.google.sheets_advanced import (
    add_chart_handler,
    add_conditional_format_rule_handler,
    add_protected_range_handler,
    clear_basic_filter_handler,
    clear_data_validation_handler,
    delete_chart_handler,
    delete_conditional_format_rule_handler,
    delete_protected_range_handler,
    set_basic_filter_handler,
    set_data_validation_handler,
    update_chart_handler,
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
_GRID_RANGE = {
    "sheet_id": _SHEET_ID,
    "start_row_index": {"type": "integer", "default": 0, "description": "0-based start row (inclusive)."},
    "end_row_index": {"type": "integer", "description": "0-based end row (exclusive)."},
    "start_column_index": {"type": "integer", "default": 0, "description": "0-based start column (inclusive)."},
    "end_column_index": {"type": "integer", "description": "0-based end column (exclusive)."},
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
_VALIDATION_CONDITION = {
    "type": "string",
    "enum": [
        "ONE_OF_LIST",
        "NUMBER_BETWEEN",
        "NUMBER_GREATER",
        "NUMBER_GREATER_THAN_EQ",
        "NUMBER_LESS",
        "NUMBER_LESS_THAN_EQ",
        "TEXT_CONTAINS",
        "DATE_IS_VALID",
        "BOOLEAN",
    ],
    "default": "ONE_OF_LIST",
}

GOOGLE_SHEETS_SET_DATA_VALIDATION = ToolSpec(
    name="google.sheets.set_data_validation",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Add data validation: dropdown list, number range, text rules. "
        "NOT for conditional colors — add_conditional_format_rule. NOT for clearing — clear_data_validation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            **_GRID_RANGE,
            "condition_type": _VALIDATION_CONDITION,
            "values": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Dropdown options for ONE_OF_LIST.",
            },
            "min_value": {"type": "number"},
            "max_value": {"type": "number"},
            "condition_value": {"type": "string", "description": "Threshold or text for single-value rules."},
            "show_dropdown": {"type": "boolean", "default": True},
            "strict": {"type": "boolean", "default": True},
            "input_message": {"type": "string", "description": "Help text when invalid value entered."},
        },
        "required": ["spreadsheet_id", "sheet_id", "end_row_index", "end_column_index"],
    },
    handler=set_data_validation_handler,
    tags=("google", "sheets", "write", "validation"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("add dropdown to column", "validate numbers 1-100", "dropdown Active Inactive"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.set_data_validation"],
)

GOOGLE_SHEETS_CLEAR_DATA_VALIDATION = ToolSpec(
    name="google.sheets.clear_data_validation",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Remove data validation rules from a cell range. NOT for clearing values — clear_values."
    ),
    parameters={
        "type": "object",
        "properties": {"spreadsheet_id": _SPREADSHEET_ID, **_GRID_RANGE},
        "required": ["spreadsheet_id", "sheet_id", "end_row_index", "end_column_index"],
    },
    handler=clear_data_validation_handler,
    tags=("google", "sheets", "write", "validation"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("remove dropdown validation", "clear validation rules"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.clear_data_validation"],
)

GOOGLE_SHEETS_ADD_CONDITIONAL_FORMAT_RULE = ToolSpec(
    name="google.sheets.add_conditional_format_rule",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Highlight cells by rule (value > X, text contains, custom formula). "
        "NOT for dropdown validation — set_data_validation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            **_GRID_RANGE,
            "rule_index": {"type": "integer", "default": 0, "description": "Priority (0 = highest)."},
            "condition_type": {
                "type": "string",
                "enum": [
                    "NUMBER_GREATER",
                    "NUMBER_GREATER_THAN_EQ",
                    "NUMBER_LESS",
                    "NUMBER_LESS_THAN_EQ",
                    "NUMBER_EQ",
                    "TEXT_CONTAINS",
                    "TEXT_STARTS_WITH",
                    "TEXT_ENDS_WITH",
                    "CUSTOM_FORMULA",
                ],
                "default": "NUMBER_GREATER",
            },
            "condition_value": {"type": "string"},
            "formula": {"type": "string", "description": "For CUSTOM_FORMULA, e.g. =AND(A1>0,B1<100)."},
            "background_color": _RGB_COLOR,
            "text_color": _RGB_COLOR,
            "bold": {"type": "boolean"},
        },
        "required": ["spreadsheet_id", "sheet_id", "end_row_index", "end_column_index"],
    },
    handler=add_conditional_format_rule_handler,
    tags=("google", "sheets", "write", "format"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("highlight negative numbers red", "conditional formatting", "color cells when value greater than 100"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.add_conditional_format_rule"],
)

GOOGLE_SHEETS_DELETE_CONDITIONAL_FORMAT_RULE = ToolSpec(
    name="google.sheets.delete_conditional_format_rule",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Remove a conditional formatting rule by index on a sheet. "
        "NOT for clearing validation — clear_data_validation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "sheet_id": _SHEET_ID,
            "rule_index": {"type": "integer", "default": 0},
        },
        "required": ["spreadsheet_id", "sheet_id"],
    },
    handler=delete_conditional_format_rule_handler,
    tags=("google", "sheets", "write", "format"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("delete conditional format rule", "remove highlight rule"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.delete_conditional_format_rule"],
)

GOOGLE_SHEETS_SET_BASIC_FILTER = ToolSpec(
    name="google.sheets.set_basic_filter",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Enable auto-filter (header dropdown filters) on a table range. "
        "NOT for sorting — sort_range. NOT for clearing — clear_basic_filter."
    ),
    parameters={
        "type": "object",
        "properties": {"spreadsheet_id": _SPREADSHEET_ID, **_GRID_RANGE},
        "required": ["spreadsheet_id", "sheet_id", "end_row_index", "end_column_index"],
    },
    handler=set_basic_filter_handler,
    tags=("google", "sheets", "write", "filters"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("enable filter on table", "add autofilter to header", "turn on filter view"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.set_basic_filter"],
)

GOOGLE_SHEETS_CLEAR_BASIC_FILTER = ToolSpec(
    name="google.sheets.clear_basic_filter",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Remove auto-filter from a worksheet tab. NOT for clearing cell values — clear_values."
    ),
    parameters={
        "type": "object",
        "properties": {"spreadsheet_id": _SPREADSHEET_ID, "sheet_id": _SHEET_ID},
        "required": ["spreadsheet_id", "sheet_id"],
    },
    handler=clear_basic_filter_handler,
    tags=("google", "sheets", "write", "filters"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("remove autofilter", "clear filter from sheet"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.clear_basic_filter"],
)

GOOGLE_SHEETS_ADD_CHART = ToolSpec(
    name="google.sheets.add_chart",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Insert chart from table data (BAR, LINE, COLUMN, AREA, PIE). "
        "First column (domain_column_index) = categories; other columns = series. "
        "NOT for updating — update_chart. NOT for deleting — delete_chart."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            **_GRID_RANGE,
            "chart_type": {
                "type": "string",
                "enum": ["BAR", "LINE", "COLUMN", "AREA", "PIE"],
                "default": "COLUMN",
            },
            "title": {"type": "string"},
            "domain_column_index": {
                "type": "integer",
                "description": "Column index for category labels (default first column in range).",
            },
            "has_header_row": {"type": "boolean", "default": True},
            "anchor_row_index": {"type": "integer", "description": "Where to place chart (row)."},
            "anchor_column_index": {"type": "integer", "description": "Where to place chart (column)."},
        },
        "required": ["spreadsheet_id", "sheet_id", "end_row_index", "end_column_index"],
    },
    handler=add_chart_handler,
    tags=("google", "sheets", "write", "charts"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("create chart from data", "add pie chart", "insert bar chart from table"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.add_chart"],
)

GOOGLE_SHEETS_UPDATE_CHART = ToolSpec(
    name="google.sheets.update_chart",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Update chart title or rebuild chart from new data range. "
        "Provide chart_id from add_chart. For title-only pass chart_id + title. "
        "For type/data change pass chart_type + grid range like add_chart."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "chart_id": {"type": "integer"},
            "title": {"type": "string"},
            "chart_type": {"type": "string", "enum": ["BAR", "LINE", "COLUMN", "AREA", "PIE"]},
            **_GRID_RANGE,
            "domain_column_index": {"type": "integer"},
            "has_header_row": {"type": "boolean", "default": True},
        },
        "required": ["spreadsheet_id", "chart_id"],
    },
    handler=update_chart_handler,
    tags=("google", "sheets", "write", "charts"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("rename chart", "change chart type to line", "update chart data range"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.update_chart"],
)

GOOGLE_SHEETS_DELETE_CHART = ToolSpec(
    name="google.sheets.delete_chart",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Remove embedded chart by chart_id. NOT for deleting sheet — delete_sheet."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "chart_id": {"type": "integer"},
        },
        "required": ["spreadsheet_id", "chart_id"],
    },
    handler=delete_chart_handler,
    tags=("google", "sheets", "write", "charts"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("delete chart", "remove embedded chart"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.delete_chart"],
)

GOOGLE_SHEETS_ADD_PROTECTED_RANGE = ToolSpec(
    name="google.sheets.add_protected_range",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Lock cell range from editing (protect formulas/headers). "
        "warning_only=true shows warning but allows edit. NOT for share permissions — drive.share_file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            **_GRID_RANGE,
            "description": {"type": "string"},
            "warning_only": {"type": "boolean", "default": False},
        },
        "required": ["spreadsheet_id", "sheet_id", "end_row_index", "end_column_index"],
    },
    handler=add_protected_range_handler,
    tags=("google", "sheets", "write", "protection"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("protect header row", "lock formula cells", "protect range from editing"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.add_protected_range"],
)

GOOGLE_SHEETS_DELETE_PROTECTED_RANGE = ToolSpec(
    name="google.sheets.delete_protected_range",
    description=(
        GOOGLE_SHEETS_OAUTH_HINT
        + "Remove range protection by protected_range_id from add_protected_range."
    ),
    parameters={
        "type": "object",
        "properties": {
            "spreadsheet_id": _SPREADSHEET_ID,
            "protected_range_id": {"type": "integer"},
        },
        "required": ["spreadsheet_id", "protected_range_id"],
    },
    handler=delete_protected_range_handler,
    tags=("google", "sheets", "write", "protection"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("remove range protection", "unlock protected cells"),
    verification_questions=SHEETS_CHECKER_QUESTIONS_BY_TOOL["google.sheets.delete_protected_range"],
)

SHEETS_WAVE4_TOOL_NAMES: tuple[str, ...] = tuple(
    tool.name
    for tool in (
        GOOGLE_SHEETS_SET_DATA_VALIDATION,
        GOOGLE_SHEETS_CLEAR_DATA_VALIDATION,
        GOOGLE_SHEETS_ADD_CONDITIONAL_FORMAT_RULE,
        GOOGLE_SHEETS_DELETE_CONDITIONAL_FORMAT_RULE,
        GOOGLE_SHEETS_SET_BASIC_FILTER,
        GOOGLE_SHEETS_CLEAR_BASIC_FILTER,
        GOOGLE_SHEETS_ADD_CHART,
        GOOGLE_SHEETS_UPDATE_CHART,
        GOOGLE_SHEETS_DELETE_CHART,
        GOOGLE_SHEETS_ADD_PROTECTED_RANGE,
        GOOGLE_SHEETS_DELETE_PROTECTED_RANGE,
    )
)

GOOGLE_SHEETS_WAVE4_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_SHEETS_SET_DATA_VALIDATION,
    GOOGLE_SHEETS_CLEAR_DATA_VALIDATION,
    GOOGLE_SHEETS_ADD_CONDITIONAL_FORMAT_RULE,
    GOOGLE_SHEETS_DELETE_CONDITIONAL_FORMAT_RULE,
    GOOGLE_SHEETS_SET_BASIC_FILTER,
    GOOGLE_SHEETS_CLEAR_BASIC_FILTER,
    GOOGLE_SHEETS_ADD_CHART,
    GOOGLE_SHEETS_UPDATE_CHART,
    GOOGLE_SHEETS_DELETE_CHART,
    GOOGLE_SHEETS_ADD_PROTECTED_RANGE,
    GOOGLE_SHEETS_DELETE_PROTECTED_RANGE,
)
