from __future__ import annotations

from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_LIVE_FETCH,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_USER_GOAL,
    FETCH_SHEETS_RANGE_VALUES,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    EvidenceRef,
    VerificationQuestion,
)

_USER_GOAL = EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal")

_LIVE_RANGE_VALUES = EvidenceRef(
    kind=EVIDENCE_LIVE_FETCH,
    fetch=FETCH_SHEETS_RANGE_VALUES,
    label="sheets_range_live",
)

_PRIOR_SHEET_READ = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "google.sheets.get_values",
        "google.sheets.read_sheet",
        "google.sheets.batch_get_values",
    ),
    match=(("spreadsheet_id", "$call.spreadsheet_id"),),
    optional=True,
    max_age_steps=10,
    label="prior_sheet_read",
)

_PRIOR_SPREADSHEET_META = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("google.sheets.get_spreadsheet", "google.sheets.create_spreadsheet"),
    match=(("spreadsheet_id", "$call.spreadsheet_id"),),
    optional=True,
    max_age_steps=10,
    label="prior_spreadsheet_meta",
)

_PRIOR_SHEETS_CONTEXT = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_name_pattern="google.sheets.*",
    optional=True,
    max_age_steps=10,
    label="prior_sheets_context",
)


def _call(label: str, *fields: str) -> EvidenceRef:
    return EvidenceRef(kind=EVIDENCE_CALL, fields=fields, label=label)


# --- Wave 1: read (4) ---

GOOGLE_SHEETS_GET_SPREADSHEET_QUESTIONS = (
    VerificationQuestion(
        id="spreadsheet_id_correct",
        text="Does spreadsheet_id match the file the user asked about (from search/URL)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_spreadsheet_call", "spreadsheet_id"), _USER_GOAL, _PRIOR_SHEETS_CONTEXT),
    ),
    VerificationQuestion(
        id="metadata_needed",
        text="Was tab/sheet metadata needed for the next step (write, rename, pick sheet_id)?",
        severity=SEVERITY_WARN,
        evidence=(_call("get_spreadsheet_call", "spreadsheet_id"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_GET_VALUES_QUESTIONS = (
    VerificationQuestion(
        id="range_matches_intent",
        text="Does the A1 range cover the cells the user asked to read?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_values_call", "spreadsheet_id", "range"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
    VerificationQuestion(
        id="spreadsheet_correct",
        text="Is spreadsheet_id the file the user intended?",
        severity=SEVERITY_WARN,
        evidence=(_call("get_values_call", "spreadsheet_id", "range"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="read_before_write",
        text="If a write follows, does this read cover the area to be changed?",
        severity=SEVERITY_INFO,
        evidence=(_call("get_values_call", "spreadsheet_id", "range"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_READ_SHEET_QUESTIONS = (
    VerificationQuestion(
        id="tab_matches_intent",
        text="Does sheet_title or sheet_id match the worksheet the user asked to dump?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("read_sheet_call", "spreadsheet_id", "sheet_title", "sheet_id", "max_rows"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
    VerificationQuestion(
        id="max_rows_sufficient",
        text="Is max_rows high enough not to truncate data the user needs?",
        severity=SEVERITY_WARN,
        evidence=(_call("read_sheet_call", "spreadsheet_id", "max_rows"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_BATCH_GET_VALUES_QUESTIONS = (
    VerificationQuestion(
        id="ranges_match_intent",
        text="Do all ranges match the cell areas the user asked to read?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("batch_get_call", "spreadsheet_id", "ranges"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
    VerificationQuestion(
        id="batch_read_justified",
        text="Was batch read more efficient than multiple get_values for this request?",
        severity=SEVERITY_INFO,
        evidence=(_call("batch_get_call", "spreadsheet_id", "ranges"), _USER_GOAL),
    ),
)

# --- Wave 1: write values (5) ---

GOOGLE_SHEETS_UPDATE_VALUES_QUESTIONS = (
    VerificationQuestion(
        id="range_matches_intent",
        text="Does the A1 range match the cells the user asked to update?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_call", "spreadsheet_id", "range", "values"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="overwrite_intended",
        text="Did the user want to overwrite cells (not append or insert blank rows)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_call", "spreadsheet_id", "range", "values"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="values_match_intent",
        text="Do written values/formulas match what the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_call", "spreadsheet_id", "range", "values"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="values_written_verify",
        text="Do live-read cells after write match the intended values (where verifiable)?",
        severity=SEVERITY_WARN,
        evidence=(_call("update_call", "spreadsheet_id", "range"), _LIVE_RANGE_VALUES, _USER_GOAL),
    ),
)

GOOGLE_SHEETS_APPEND_VALUES_QUESTIONS = (
    VerificationQuestion(
        id="append_not_overwrite",
        text="Was appending rows correct (user did not ask to overwrite existing rows)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("append_call", "spreadsheet_id", "range", "values", "insert_data_option"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="range_or_sheet_correct",
        text="Is the anchor range/sheet correct for the new rows?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("append_call", "spreadsheet_id", "range", "values"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="values_match_intent",
        text="Do appended row values match what the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("append_call", "spreadsheet_id", "values"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_CLEAR_VALUES_QUESTIONS = (
    VerificationQuestion(
        id="range_matches_intent",
        text="Does the range to clear match what the user asked to erase?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("clear_call", "spreadsheet_id", "range"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="clear_not_delete_structure",
        text="Did the user want to clear values only (not delete rows/columns/sheets)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("clear_call", "spreadsheet_id", "range"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_BATCH_UPDATE_VALUES_QUESTIONS = (
    VerificationQuestion(
        id="ranges_match_intent",
        text="Do all batch ranges match what the user asked to update?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("batch_update_call", "spreadsheet_id", "data"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="overwrite_intended",
        text="Did the user want to overwrite (not append)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("batch_update_call", "spreadsheet_id", "data"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="values_match_intent",
        text="Do all batch values match the user's request?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("batch_update_call", "spreadsheet_id", "data"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_BATCH_CLEAR_VALUES_QUESTIONS = (
    VerificationQuestion(
        id="ranges_match_intent",
        text="Do all ranges to clear match what the user asked to erase?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("batch_clear_call", "spreadsheet_id", "ranges"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="clear_not_delete_structure",
        text="Did the user want value clear (not structural delete)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("batch_clear_call", "spreadsheet_id", "ranges"), _USER_GOAL),
    ),
)

# --- Wave 1: structure (2) ---

GOOGLE_SHEETS_CREATE_SPREADSHEET_QUESTIONS = (
    VerificationQuestion(
        id="title_matches_intent",
        text="Does the spreadsheet title match what the user asked to create?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_spreadsheet_call", "title", "sheets"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="new_file_intended",
        text="Did the user want a new file (not write to an existing spreadsheet)?",
        severity=SEVERITY_WARN,
        evidence=(_call("create_spreadsheet_call", "title"), _USER_GOAL, _PRIOR_SHEETS_CONTEXT),
    ),
)

GOOGLE_SHEETS_UPDATE_SPREADSHEET_PROPERTIES_QUESTIONS = (
    VerificationQuestion(
        id="spreadsheet_id_correct",
        text="Does spreadsheet_id match the file the user asked to rename or reconfigure?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_file_props_call", "spreadsheet_id", "title", "locale", "time_zone"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
    VerificationQuestion(
        id="fields_match_request",
        text="Are only the file-level properties the user mentioned being changed?",
        severity=SEVERITY_WARN,
        evidence=(_call("update_file_props_call", "spreadsheet_id", "title", "locale", "time_zone"), _USER_GOAL),
    ),
)

# --- Wave 2: sheet structure (9) ---

GOOGLE_SHEETS_ADD_SHEET_QUESTIONS = (
    VerificationQuestion(
        id="spreadsheet_correct",
        text="Is spreadsheet_id the workbook where the user wanted a new tab?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("add_sheet_call", "spreadsheet_id", "title"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
    VerificationQuestion(
        id="tab_name_matches_intent",
        text="Does the new tab title match what the user asked?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("add_sheet_call", "spreadsheet_id", "title"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="add_not_duplicate",
        text="Did the user want a new tab (not duplicate_sheet on existing)?",
        severity=SEVERITY_WARN,
        evidence=(_call("add_sheet_call", "spreadsheet_id", "title"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_DELETE_SHEET_QUESTIONS = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Was confirm=true set for this irreversible tab delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_sheet_call", "spreadsheet_id", "sheet_id", "confirm"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="correct_sheet_targeted",
        text="Does sheet_id match the tab the user asked to remove?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_sheet_call", "spreadsheet_id", "sheet_id"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
    VerificationQuestion(
        id="delete_not_clear",
        text="Did the user want to delete the tab (not just clear_values)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_sheet_call", "spreadsheet_id", "sheet_id"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_DUPLICATE_SHEET_QUESTIONS = (
    VerificationQuestion(
        id="source_sheet_correct",
        text="Does sheet_id match the tab the user wanted to duplicate?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("duplicate_sheet_call", "spreadsheet_id", "sheet_id", "new_sheet_name"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
    VerificationQuestion(
        id="copy_name_matches_intent",
        text="Does new_sheet_name match the name the user wanted for the copy?",
        severity=SEVERITY_WARN,
        evidence=(_call("duplicate_sheet_call", "new_sheet_name"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_COPY_SHEET_TO_SPREADSHEET_QUESTIONS = (
    VerificationQuestion(
        id="source_and_dest_correct",
        text="Are source_spreadsheet_id, sheet_id, and destination_spreadsheet_id correct for the user's copy request?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("copy_sheet_call", "source_spreadsheet_id", "sheet_id", "destination_spreadsheet_id"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
    VerificationQuestion(
        id="cross_file_intended",
        text="Did the user want to copy to another file (not duplicate within same file)?",
        severity=SEVERITY_WARN,
        evidence=(_call("copy_sheet_call", "source_spreadsheet_id", "destination_spreadsheet_id"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_UPDATE_SHEET_PROPERTIES_QUESTIONS = (
    VerificationQuestion(
        id="correct_sheet_targeted",
        text="Does sheet_id match the tab the user asked to rename/hide/freeze/reorder?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_sheet_props_call", "spreadsheet_id", "sheet_id", "title", "hidden", "index", "frozen_row_count"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
    VerificationQuestion(
        id="fields_match_request",
        text="Are only the tab properties the user mentioned being changed?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_sheet_props_call", "spreadsheet_id", "sheet_id", "title", "hidden", "frozen_row_count"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_INSERT_DIMENSION_QUESTIONS = (
    VerificationQuestion(
        id="dimension_and_range_correct",
        text="Are dimension (ROWS/COLUMNS), start_index, and end_index what the user asked to insert?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("insert_dim_call", "spreadsheet_id", "sheet_id", "dimension", "start_index", "end_index"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="insert_not_append_values",
        text="Did the user want blank rows/cols inserted (not append_values with data)?",
        severity=SEVERITY_WARN,
        evidence=(_call("insert_dim_call", "spreadsheet_id", "sheet_id", "dimension"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_DELETE_DIMENSION_QUESTIONS = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Was confirm=true set for deleting rows/columns?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_dim_call", "spreadsheet_id", "sheet_id", "dimension", "confirm"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="dimension_range_correct",
        text="Does the row/column range match what the user asked to delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_dim_call", "spreadsheet_id", "sheet_id", "dimension", "start_index", "end_index"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="delete_not_clear",
        text="Did the user want structural delete (not clear_values)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_dim_call", "spreadsheet_id", "sheet_id", "dimension"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_MOVE_DIMENSION_QUESTIONS = (
    VerificationQuestion(
        id="move_range_correct",
        text="Are source and destination indices correct for the row/column move?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("move_dim_call", "spreadsheet_id", "sheet_id", "dimension", "source_index", "destination_index"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="move_not_copy_paste",
        text="Was move_dimension appropriate (not copy_paste_range)?",
        severity=SEVERITY_WARN,
        evidence=(_call("move_dim_call", "spreadsheet_id", "sheet_id", "dimension"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_UPDATE_DIMENSION_PROPERTIES_QUESTIONS = (
    VerificationQuestion(
        id="dimension_range_correct",
        text="Does the row/column range match what the user asked to resize/hide?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_dim_props_call", "spreadsheet_id", "sheet_id", "dimension", "start_index", "end_index", "pixel_size", "hidden"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="properties_match_intent",
        text="Do pixel_size or hidden flags match the user's request?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_dim_props_call", "spreadsheet_id", "sheet_id", "pixel_size", "hidden"), _USER_GOAL),
    ),
)

# --- Wave 3: format & data (12) ---

_GOOGLE_SHEETS_GRID_RANGE_FIELDS = (
    "spreadsheet_id",
    "sheet_id",
    "start_row_index",
    "end_row_index",
    "start_column_index",
    "end_column_index",
)

GOOGLE_SHEETS_MERGE_CELLS_QUESTIONS = (
    VerificationQuestion(
        id="merge_range_correct",
        text="Does the grid range match the cells the user asked to merge?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("merge_call", *_GOOGLE_SHEETS_GRID_RANGE_FIELDS, "merge_type"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="merge_intended",
        text="Did the user want merge (not just format_cells)?",
        severity=SEVERITY_WARN,
        evidence=(_call("merge_call", "merge_type"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_UNMERGE_CELLS_QUESTIONS = (
    VerificationQuestion(
        id="unmerge_range_correct",
        text="Does the range match merged cells the user asked to split?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("unmerge_call", *_GOOGLE_SHEETS_GRID_RANGE_FIELDS), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
)

GOOGLE_SHEETS_FORMAT_CELLS_QUESTIONS = (
    VerificationQuestion(
        id="format_range_correct",
        text="Does the range match cells the user asked to format (bold, color, number format)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("format_call", *_GOOGLE_SHEETS_GRID_RANGE_FIELDS, "number_format", "background_color", "bold"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="format_matches_intent",
        text="Do format options match what the user described visually?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("format_call", "number_format", "background_color", "text_color", "bold", "italic"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_SET_BORDERS_QUESTIONS = (
    VerificationQuestion(
        id="border_range_correct",
        text="Does the range match where the user wanted borders?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("borders_call", *_GOOGLE_SHEETS_GRID_RANGE_FIELDS, "border_style"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="border_style_matches_intent",
        text="Do border style/width/color match the user's request?",
        severity=SEVERITY_WARN,
        evidence=(_call("borders_call", "border_style", "border_width", "outer_borders", "inner_borders"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_AUTO_RESIZE_COLUMNS_QUESTIONS = (
    VerificationQuestion(
        id="column_range_correct",
        text="Does the column index range match columns the user asked to auto-fit?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("auto_resize_cols_call", "spreadsheet_id", "sheet_id", "start_column_index", "end_column_index"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_AUTO_RESIZE_ROWS_QUESTIONS = (
    VerificationQuestion(
        id="row_range_correct",
        text="Does the row index range match rows the user asked to auto-fit?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("auto_resize_rows_call", "spreadsheet_id", "sheet_id", "start_row_index", "end_row_index"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_COPY_PASTE_RANGE_QUESTIONS = (
    VerificationQuestion(
        id="source_dest_correct",
        text="Are source and destination grid ranges correct for the copy?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("copy_paste_call", "spreadsheet_id", "sheet_id", "paste_type"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="paste_type_matches_intent",
        text="Does paste_type (values/format/formulas/all) match what the user wanted copied?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("copy_paste_call", "paste_type"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="copy_not_cut",
        text="Did the user want copy (keep source), not cut_paste_range?",
        severity=SEVERITY_WARN,
        evidence=(_call("copy_paste_call", "spreadsheet_id", "sheet_id"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_CUT_PASTE_RANGE_QUESTIONS = (
    VerificationQuestion(
        id="source_dest_correct",
        text="Are source and destination ranges correct for the move?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("cut_paste_call", "spreadsheet_id", "sheet_id"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="cut_intended",
        text="Did the user want to move data (cut), not copy while keeping source?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("cut_paste_call", "paste_type"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_SORT_RANGE_QUESTIONS = (
    VerificationQuestion(
        id="sort_range_correct",
        text="Does the table range include all rows/columns the user wanted sorted?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("sort_call", *_GOOGLE_SHEETS_GRID_RANGE_FIELDS, "sort_specs"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="sort_specs_match_intent",
        text="Do sort_specs (column index, ASC/DESC) match how the user asked to sort?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("sort_call", "sort_specs"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_FIND_REPLACE_QUESTIONS = (
    VerificationQuestion(
        id="find_replace_text_correct",
        text="Do find and replace strings match what the user asked to swap?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("find_replace_call", "spreadsheet_id", "find", "replacement", "sheet_id", "match_case"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="scope_not_too_broad",
        text="Is scope limited to the intended sheet/range (not accidental whole-workbook replace)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("find_replace_call", "spreadsheet_id", "sheet_id", "all_sheets"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_ADD_NAMED_RANGE_QUESTIONS = (
    VerificationQuestion(
        id="name_and_range_correct",
        text="Do named range name and A1/grid range match the user's request?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("add_named_range_call", "spreadsheet_id", "name", "range"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_DELETE_NAMED_RANGE_QUESTIONS = (
    VerificationQuestion(
        id="named_range_correct",
        text="Does the named range id/name match what the user asked to remove?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_named_range_call", "spreadsheet_id", "named_range_id"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
)

# --- Wave 4: validation, filters, charts, protection (11) ---

GOOGLE_SHEETS_SET_DATA_VALIDATION_QUESTIONS = (
    VerificationQuestion(
        id="validation_range_correct",
        text="Does the range match cells where the user wanted validation/dropdown?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("set_validation_call", *_GOOGLE_SHEETS_GRID_RANGE_FIELDS, "condition_type", "values"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="rule_matches_intent",
        text="Does condition_type and values match the validation rule the user described?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("set_validation_call", "condition_type", "values", "min_value", "max_value"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_CLEAR_DATA_VALIDATION_QUESTIONS = (
    VerificationQuestion(
        id="validation_range_correct",
        text="Does the range match where the user asked to remove validation?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("clear_validation_call", *_GOOGLE_SHEETS_GRID_RANGE_FIELDS), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_ADD_CONDITIONAL_FORMAT_RULE_QUESTIONS = (
    VerificationQuestion(
        id="rule_range_correct",
        text="Does the range match cells the user wanted conditionally highlighted?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("add_cond_format_call", *_GOOGLE_SHEETS_GRID_RANGE_FIELDS, "condition_type"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="condition_matches_intent",
        text="Does the condition (threshold, text contains, formula) match the user's rule?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("add_cond_format_call", "condition_type", "condition_value", "formula"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_DELETE_CONDITIONAL_FORMAT_RULE_QUESTIONS = (
    VerificationQuestion(
        id="correct_rule_index",
        text="Does rule_index target the conditional format rule the user asked to remove?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_cond_format_call", "spreadsheet_id", "sheet_id", "rule_index"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
)

GOOGLE_SHEETS_SET_BASIC_FILTER_QUESTIONS = (
    VerificationQuestion(
        id="filter_range_correct",
        text="Does the range include the table header and data the user wanted filter dropdowns on?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("set_filter_call", *_GOOGLE_SHEETS_GRID_RANGE_FIELDS), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
)

GOOGLE_SHEETS_CLEAR_BASIC_FILTER_QUESTIONS = (
    VerificationQuestion(
        id="correct_sheet_targeted",
        text="Does sheet_id match the tab where the user asked to remove the filter?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("clear_filter_call", "spreadsheet_id", "sheet_id"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
)

GOOGLE_SHEETS_ADD_CHART_QUESTIONS = (
    VerificationQuestion(
        id="data_range_correct",
        text="Does the data range include the series and categories the user wanted charted?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("add_chart_call", *_GOOGLE_SHEETS_GRID_RANGE_FIELDS, "chart_type", "domain_column_index"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="chart_type_matches_intent",
        text="Does chart_type and title match what the user asked for (bar, pie, line)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("add_chart_call", "chart_type", "title"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_UPDATE_CHART_QUESTIONS = (
    VerificationQuestion(
        id="correct_chart_targeted",
        text="Does chart_id match the chart the user asked to update?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_chart_call", "spreadsheet_id", "chart_id", "title", "chart_type"), _USER_GOAL, _PRIOR_SHEETS_CONTEXT),
    ),
    VerificationQuestion(
        id="update_fields_match_intent",
        text="Are title/type/data range changes what the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_chart_call", "spreadsheet_id", "chart_id", "title"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_DELETE_CHART_QUESTIONS = (
    VerificationQuestion(
        id="correct_chart_targeted",
        text="Does chart_id match the chart the user asked to delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_chart_call", "spreadsheet_id", "chart_id"), _USER_GOAL, _PRIOR_SHEETS_CONTEXT),
    ),
    VerificationQuestion(
        id="delete_intent",
        text="Did the user intend to remove the chart (not update it)?",
        severity=SEVERITY_WARN,
        evidence=(_call("delete_chart_call", "chart_id"), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_ADD_PROTECTED_RANGE_QUESTIONS = (
    VerificationQuestion(
        id="protection_range_correct",
        text="Does the protected range match cells the user asked to lock?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("add_protection_call", *_GOOGLE_SHEETS_GRID_RANGE_FIELDS, "description"), _USER_GOAL, _PRIOR_SHEET_READ),
    ),
    VerificationQuestion(
        id="protection_scope_intended",
        text="Is protection limited to what the user asked (not whole sheet by mistake)?",
        severity=SEVERITY_WARN,
        evidence=(_call("add_protection_call", *_GOOGLE_SHEETS_GRID_RANGE_FIELDS), _USER_GOAL),
    ),
)

GOOGLE_SHEETS_DELETE_PROTECTED_RANGE_QUESTIONS = (
    VerificationQuestion(
        id="correct_protection_targeted",
        text="Does protected_range_id match the protection the user asked to remove?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_protection_call", "spreadsheet_id", "protected_range_id"), _USER_GOAL, _PRIOR_SPREADSHEET_META),
    ),
)

# --- Registry ---

SHEETS_CHECKER_ALL_TOOL_NAMES: tuple[str, ...] = (
    "google.sheets.get_spreadsheet",
    "google.sheets.create_spreadsheet",
    "google.sheets.update_spreadsheet_properties",
    "google.sheets.get_values",
    "google.sheets.read_sheet",
    "google.sheets.batch_get_values",
    "google.sheets.update_values",
    "google.sheets.append_values",
    "google.sheets.clear_values",
    "google.sheets.batch_update_values",
    "google.sheets.batch_clear_values",
    "google.sheets.add_sheet",
    "google.sheets.delete_sheet",
    "google.sheets.duplicate_sheet",
    "google.sheets.copy_sheet_to_spreadsheet",
    "google.sheets.update_sheet_properties",
    "google.sheets.insert_dimension",
    "google.sheets.delete_dimension",
    "google.sheets.move_dimension",
    "google.sheets.update_dimension_properties",
    "google.sheets.merge_cells",
    "google.sheets.unmerge_cells",
    "google.sheets.format_cells",
    "google.sheets.set_borders",
    "google.sheets.auto_resize_columns",
    "google.sheets.auto_resize_rows",
    "google.sheets.copy_paste_range",
    "google.sheets.cut_paste_range",
    "google.sheets.sort_range",
    "google.sheets.find_replace",
    "google.sheets.add_named_range",
    "google.sheets.delete_named_range",
    "google.sheets.set_data_validation",
    "google.sheets.clear_data_validation",
    "google.sheets.add_conditional_format_rule",
    "google.sheets.delete_conditional_format_rule",
    "google.sheets.set_basic_filter",
    "google.sheets.clear_basic_filter",
    "google.sheets.add_chart",
    "google.sheets.update_chart",
    "google.sheets.delete_chart",
    "google.sheets.add_protected_range",
    "google.sheets.delete_protected_range",
)

SHEETS_CHECKER_READ_TOOL_NAMES: tuple[str, ...] = (
    "google.sheets.get_spreadsheet",
    "google.sheets.get_values",
    "google.sheets.read_sheet",
    "google.sheets.batch_get_values",
)

SHEETS_CHECKER_WRITE_TOOL_NAMES: tuple[str, ...] = tuple(
    name for name in SHEETS_CHECKER_ALL_TOOL_NAMES if name not in SHEETS_CHECKER_READ_TOOL_NAMES
)

SHEETS_CHECKER_QUESTIONS_BY_TOOL: dict[str, tuple[VerificationQuestion, ...]] = {
    "google.sheets.get_spreadsheet": GOOGLE_SHEETS_GET_SPREADSHEET_QUESTIONS,
    "google.sheets.create_spreadsheet": GOOGLE_SHEETS_CREATE_SPREADSHEET_QUESTIONS,
    "google.sheets.update_spreadsheet_properties": GOOGLE_SHEETS_UPDATE_SPREADSHEET_PROPERTIES_QUESTIONS,
    "google.sheets.get_values": GOOGLE_SHEETS_GET_VALUES_QUESTIONS,
    "google.sheets.read_sheet": GOOGLE_SHEETS_READ_SHEET_QUESTIONS,
    "google.sheets.batch_get_values": GOOGLE_SHEETS_BATCH_GET_VALUES_QUESTIONS,
    "google.sheets.update_values": GOOGLE_SHEETS_UPDATE_VALUES_QUESTIONS,
    "google.sheets.append_values": GOOGLE_SHEETS_APPEND_VALUES_QUESTIONS,
    "google.sheets.clear_values": GOOGLE_SHEETS_CLEAR_VALUES_QUESTIONS,
    "google.sheets.batch_update_values": GOOGLE_SHEETS_BATCH_UPDATE_VALUES_QUESTIONS,
    "google.sheets.batch_clear_values": GOOGLE_SHEETS_BATCH_CLEAR_VALUES_QUESTIONS,
    "google.sheets.add_sheet": GOOGLE_SHEETS_ADD_SHEET_QUESTIONS,
    "google.sheets.delete_sheet": GOOGLE_SHEETS_DELETE_SHEET_QUESTIONS,
    "google.sheets.duplicate_sheet": GOOGLE_SHEETS_DUPLICATE_SHEET_QUESTIONS,
    "google.sheets.copy_sheet_to_spreadsheet": GOOGLE_SHEETS_COPY_SHEET_TO_SPREADSHEET_QUESTIONS,
    "google.sheets.update_sheet_properties": GOOGLE_SHEETS_UPDATE_SHEET_PROPERTIES_QUESTIONS,
    "google.sheets.insert_dimension": GOOGLE_SHEETS_INSERT_DIMENSION_QUESTIONS,
    "google.sheets.delete_dimension": GOOGLE_SHEETS_DELETE_DIMENSION_QUESTIONS,
    "google.sheets.move_dimension": GOOGLE_SHEETS_MOVE_DIMENSION_QUESTIONS,
    "google.sheets.update_dimension_properties": GOOGLE_SHEETS_UPDATE_DIMENSION_PROPERTIES_QUESTIONS,
    "google.sheets.merge_cells": GOOGLE_SHEETS_MERGE_CELLS_QUESTIONS,
    "google.sheets.unmerge_cells": GOOGLE_SHEETS_UNMERGE_CELLS_QUESTIONS,
    "google.sheets.format_cells": GOOGLE_SHEETS_FORMAT_CELLS_QUESTIONS,
    "google.sheets.set_borders": GOOGLE_SHEETS_SET_BORDERS_QUESTIONS,
    "google.sheets.auto_resize_columns": GOOGLE_SHEETS_AUTO_RESIZE_COLUMNS_QUESTIONS,
    "google.sheets.auto_resize_rows": GOOGLE_SHEETS_AUTO_RESIZE_ROWS_QUESTIONS,
    "google.sheets.copy_paste_range": GOOGLE_SHEETS_COPY_PASTE_RANGE_QUESTIONS,
    "google.sheets.cut_paste_range": GOOGLE_SHEETS_CUT_PASTE_RANGE_QUESTIONS,
    "google.sheets.sort_range": GOOGLE_SHEETS_SORT_RANGE_QUESTIONS,
    "google.sheets.find_replace": GOOGLE_SHEETS_FIND_REPLACE_QUESTIONS,
    "google.sheets.add_named_range": GOOGLE_SHEETS_ADD_NAMED_RANGE_QUESTIONS,
    "google.sheets.delete_named_range": GOOGLE_SHEETS_DELETE_NAMED_RANGE_QUESTIONS,
    "google.sheets.set_data_validation": GOOGLE_SHEETS_SET_DATA_VALIDATION_QUESTIONS,
    "google.sheets.clear_data_validation": GOOGLE_SHEETS_CLEAR_DATA_VALIDATION_QUESTIONS,
    "google.sheets.add_conditional_format_rule": GOOGLE_SHEETS_ADD_CONDITIONAL_FORMAT_RULE_QUESTIONS,
    "google.sheets.delete_conditional_format_rule": GOOGLE_SHEETS_DELETE_CONDITIONAL_FORMAT_RULE_QUESTIONS,
    "google.sheets.set_basic_filter": GOOGLE_SHEETS_SET_BASIC_FILTER_QUESTIONS,
    "google.sheets.clear_basic_filter": GOOGLE_SHEETS_CLEAR_BASIC_FILTER_QUESTIONS,
    "google.sheets.add_chart": GOOGLE_SHEETS_ADD_CHART_QUESTIONS,
    "google.sheets.update_chart": GOOGLE_SHEETS_UPDATE_CHART_QUESTIONS,
    "google.sheets.delete_chart": GOOGLE_SHEETS_DELETE_CHART_QUESTIONS,
    "google.sheets.add_protected_range": GOOGLE_SHEETS_ADD_PROTECTED_RANGE_QUESTIONS,
    "google.sheets.delete_protected_range": GOOGLE_SHEETS_DELETE_PROTECTED_RANGE_QUESTIONS,
}
