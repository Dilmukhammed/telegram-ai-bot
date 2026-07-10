from __future__ import annotations

from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_LIVE_FETCH,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_USER_GOAL,
    FETCH_WORKSPACE_STAT,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    EvidenceRef,
    VerificationQuestion,
)

_USER_GOAL = EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal")

_LIVE_WORKSPACE_STAT = EvidenceRef(
    kind=EVIDENCE_LIVE_FETCH,
    fetch=FETCH_WORKSPACE_STAT,
    label="workspace_stat_live",
)

_PRIOR_PATH_READ = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "workspace.stat",
        "workspace.read_file",
        "workspace.read_lines",
        "workspace.list_dir",
        "workspace.find",
        "workspace.grep",
    ),
    match=(("path", "$call.path"),),
    optional=True,
    max_age_steps=10,
    label="prior_path_read",
)

_PRIOR_FROM_PATH = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "workspace.stat",
        "workspace.list_dir",
        "workspace.find",
        "workspace.read_file",
    ),
    match=(("path", "$call.from_path"),),
    optional=True,
    max_age_steps=10,
    label="prior_from_path",
)

_PRIOR_FILE_REF = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_name_pattern="*",
    optional=True,
    max_age_steps=5,
    label="prior_file_ref_context",
)

_PRIOR_WORKSPACE_CONTEXT = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_name_pattern="workspace.*",
    optional=True,
    max_age_steps=10,
    label="prior_workspace_context",
)


def _call(label: str, *fields: str) -> EvidenceRef:
    return EvidenceRef(kind=EVIDENCE_CALL, fields=fields, label=label)


# --- Read ---

WORKSPACE_LIST_DIR_QUESTIONS = (
    VerificationQuestion(
        id="path_scope",
        text="Does path (or root default) match the folder the user asked to list?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_dir_call", "path", "recursive", "max_entries"), _USER_GOAL, _PRIOR_WORKSPACE_CONTEXT),
    ),
    VerificationQuestion(
        id="recursive_intentional",
        text="If recursive=true, did the user need a deep listing rather than one level?",
        severity=SEVERITY_INFO,
        evidence=(_call("list_dir_call", "recursive"), _USER_GOAL),
    ),
)

WORKSPACE_STAT_QUESTIONS = (
    VerificationQuestion(
        id="path_correct",
        text="Is path the file or directory the user asked to inspect?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("stat_call", "path"), _USER_GOAL, _PRIOR_WORKSPACE_CONTEXT),
    ),
    VerificationQuestion(
        id="stat_before_action",
        text="If a read/write/send follows, was stat used on the right target path?",
        severity=SEVERITY_INFO,
        evidence=(_call("stat_call", "path"), _USER_GOAL),
    ),
)

WORKSPACE_READ_FILE_QUESTIONS = (
    VerificationQuestion(
        id="path_correct",
        text="Is path the file the user asked to preview?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("read_file_call", "path", "preview_lines"), _USER_GOAL, _PRIOR_PATH_READ),
    ),
    VerificationQuestion(
        id="read_lines_for_range",
        text="If the user asked for a specific line range, should read_lines have been used?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="stat_before_large_read",
        text="Was stat or list_dir used first when file size or type was unknown?",
        severity=SEVERITY_INFO,
        evidence=(_call("read_file_call", "path"), _PRIOR_WORKSPACE_CONTEXT),
    ),
)

WORKSPACE_READ_LINES_QUESTIONS = (
    VerificationQuestion(
        id="path_correct",
        text="Is path the text file the user asked to read partially?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("read_lines_call", "path", "start_line", "end_line", "limit"), _USER_GOAL, _PRIOR_PATH_READ),
    ),
    VerificationQuestion(
        id="line_range_matches",
        text="Do start_line/end_line/limit cover the lines the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("read_lines_call", "start_line", "end_line", "limit"), _USER_GOAL),
    ),
)

WORKSPACE_USAGE_QUESTIONS = (
    VerificationQuestion(
        id="quota_intent",
        text="Did the user ask for workspace storage quota or usage limits?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

WORKSPACE_FIND_QUESTIONS = (
    VerificationQuestion(
        id="pattern_matches_intent",
        text="Does glob pattern match the files the user asked to locate?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("find_call", "pattern", "max_results"), _USER_GOAL),
    ),
)

WORKSPACE_GREP_QUESTIONS = (
    VerificationQuestion(
        id="pattern_matches_intent",
        text="Does regex pattern match what the user asked to search for in files?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("grep_call", "pattern", "path", "glob"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="search_scope",
        text="Is path/glob scope narrow enough (not whole workspace when one file was meant)?",
        severity=SEVERITY_WARN,
        evidence=(_call("grep_call", "path", "glob"), _USER_GOAL, _PRIOR_WORKSPACE_CONTEXT),
    ),
)

# --- Write ---

WORKSPACE_WRITE_FILE_QUESTIONS = (
    VerificationQuestion(
        id="path_correct",
        text="Is path where the user asked to save the file?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("write_call", "path", "mime_type", "overwrite"), _USER_GOAL, _PRIOR_WORKSPACE_CONTEXT),
    ),
    VerificationQuestion(
        id="content_provided",
        text="Was content_text or content_base64 provided for the file body?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("write_call", "content_text", "content_base64"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="overwrite_intentional",
        text="If overwrite=true on an existing path, did the user intend to replace the file?",
        severity=SEVERITY_WARN,
        evidence=(_call("write_call", "path", "overwrite"), _PRIOR_PATH_READ, _USER_GOAL),
    ),
    VerificationQuestion(
        id="file_written_live",
        text="Does live workspace.stat confirm the file exists at path after write?",
        severity=SEVERITY_WARN,
        evidence=(_call("write_call", "path"), _LIVE_WORKSPACE_STAT, _USER_GOAL),
    ),
)

WORKSPACE_APPEND_FILE_QUESTIONS = (
    VerificationQuestion(
        id="path_correct",
        text="Is path the file the user asked to append to?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("append_call", "path", "content_text"), _USER_GOAL, _PRIOR_PATH_READ),
    ),
    VerificationQuestion(
        id="append_not_overwrite",
        text="Did the user want to append, not overwrite with write_file?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="file_exists_live",
        text="Does live workspace.stat show the file exists after append?",
        severity=SEVERITY_INFO,
        evidence=(_call("append_call", "path"), _LIVE_WORKSPACE_STAT, _USER_GOAL),
    ),
)

WORKSPACE_MKDIR_QUESTIONS = (
    VerificationQuestion(
        id="path_correct",
        text="Is path the directory the user asked to create?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("mkdir_call", "path", "parents"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="dir_created_live",
        text="Does live workspace.stat confirm the directory exists?",
        severity=SEVERITY_INFO,
        evidence=(_call("mkdir_call", "path"), _LIVE_WORKSPACE_STAT, _USER_GOAL),
    ),
)

WORKSPACE_MOVE_QUESTIONS = (
    VerificationQuestion(
        id="from_path_correct",
        text="Is from_path the file or folder the user asked to move/rename?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("move_call", "from_path", "to_path", "overwrite"), _USER_GOAL, _PRIOR_FROM_PATH),
    ),
    VerificationQuestion(
        id="to_path_correct",
        text="Is to_path the destination the user specified?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("move_call", "to_path"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="destination_live",
        text="Does live workspace.stat on to_path confirm the moved item exists?",
        severity=SEVERITY_WARN,
        evidence=(_call("move_call", "to_path"), _LIVE_WORKSPACE_STAT, _USER_GOAL),
    ),
)

# --- Maintain ---

WORKSPACE_COPY_QUESTIONS = (
    VerificationQuestion(
        id="from_path_correct",
        text="Is from_path the source file/folder the user asked to copy?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("copy_call", "from_path", "to_path", "overwrite"), _USER_GOAL, _PRIOR_FROM_PATH),
    ),
    VerificationQuestion(
        id="to_path_correct",
        text="Is to_path the copy destination the user wanted?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("copy_call", "to_path"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="copy_not_move",
        text="Did the user want a copy (source kept), not move?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="copy_dest_live",
        text="Does live workspace.stat on to_path confirm the copy exists?",
        severity=SEVERITY_WARN,
        evidence=(_call("copy_call", "to_path"), _LIVE_WORKSPACE_STAT, _USER_GOAL),
    ),
)

WORKSPACE_DELETE_QUESTIONS = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Is confirm=true set for this delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_call", "path", "confirm", "recursive"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="path_correct",
        text="Is path the file or directory the user explicitly asked to delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_call", "path"), _USER_GOAL, _PRIOR_PATH_READ),
    ),
    VerificationQuestion(
        id="recursive_for_dir",
        text="If deleting a non-empty directory, is recursive=true set?",
        severity=SEVERITY_WARN,
        evidence=(_call("delete_call", "recursive"), _USER_GOAL),
    ),
)

WORKSPACE_CLEAR_QUESTIONS = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Is confirm=true set for clearing the workspace zone?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("clear_call", "zone", "confirm"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="zone_matches_intent",
        text="Does zone (agent/exports/uploads/all) match what the user asked to wipe?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("clear_call", "zone"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="clear_not_single_file",
        text="Did the user want to clear a whole zone, not delete one file?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

WORKSPACE_IMPORT_FROM_FILE_REF_QUESTIONS = (
    VerificationQuestion(
        id="file_ref_correct",
        text="Is file_ref from the Drive/Gmail download the user asked to persist?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("import_call", "file_ref", "path", "overwrite"), _USER_GOAL, _PRIOR_FILE_REF),
    ),
    VerificationQuestion(
        id="path_correct",
        text="Is path the workspace location the user asked to save to?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("import_call", "path"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="imported_live",
        text="Does live workspace.stat confirm the file exists at path after import?",
        severity=SEVERITY_WARN,
        evidence=(_call("import_call", "path"), _LIVE_WORKSPACE_STAT, _USER_GOAL),
    ),
)

WORKSPACE_UNZIP_QUESTIONS = (
    VerificationQuestion(
        id="zip_path_correct",
        text="Is path the .zip archive the user asked to extract?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("unzip_call", "path", "dest", "overwrite"), _USER_GOAL, _PRIOR_PATH_READ),
    ),
    VerificationQuestion(
        id="dest_matches_intent",
        text="Does dest (or default stem folder) match where the user wanted files extracted?",
        severity=SEVERITY_WARN,
        evidence=(_call("unzip_call", "dest"), _USER_GOAL),
    ),
)

WORKSPACE_CHECKER_QUESTIONS_BY_TOOL: dict[str, tuple[VerificationQuestion, ...]] = {
    "workspace.list_dir": WORKSPACE_LIST_DIR_QUESTIONS,
    "workspace.stat": WORKSPACE_STAT_QUESTIONS,
    "workspace.read_file": WORKSPACE_READ_FILE_QUESTIONS,
    "workspace.read_lines": WORKSPACE_READ_LINES_QUESTIONS,
    "workspace.usage": WORKSPACE_USAGE_QUESTIONS,
    "workspace.find": WORKSPACE_FIND_QUESTIONS,
    "workspace.grep": WORKSPACE_GREP_QUESTIONS,
    "workspace.write_file": WORKSPACE_WRITE_FILE_QUESTIONS,
    "workspace.append_file": WORKSPACE_APPEND_FILE_QUESTIONS,
    "workspace.mkdir": WORKSPACE_MKDIR_QUESTIONS,
    "workspace.move": WORKSPACE_MOVE_QUESTIONS,
    "workspace.copy": WORKSPACE_COPY_QUESTIONS,
    "workspace.delete": WORKSPACE_DELETE_QUESTIONS,
    "workspace.clear": WORKSPACE_CLEAR_QUESTIONS,
    "workspace.import_from_file_ref": WORKSPACE_IMPORT_FROM_FILE_REF_QUESTIONS,
    "workspace.unzip": WORKSPACE_UNZIP_QUESTIONS,
}

WORKSPACE_CHECKER_ALL_TOOL_NAMES = tuple(WORKSPACE_CHECKER_QUESTIONS_BY_TOOL.keys())

WORKSPACE_CHECKER_READ_TOOL_NAMES = tuple(
    name
    for name in WORKSPACE_CHECKER_ALL_TOOL_NAMES
    if name.endswith(
        (
            ".list_dir",
            ".stat",
            ".read_file",
            ".read_lines",
            ".usage",
            ".find",
            ".grep",
        )
    )
)

WORKSPACE_CHECKER_WRITE_TOOL_NAMES = tuple(
    name for name in WORKSPACE_CHECKER_ALL_TOOL_NAMES if name not in WORKSPACE_CHECKER_READ_TOOL_NAMES
)
