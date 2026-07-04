from __future__ import annotations

from typing import Any

from tools.schema import ToolSpec
from tools.workspace.errors import WorkspaceError
from tools.workspace.store import (
    _require_user_id,
    find_files,
    grep_files,
    list_dir,
    read_file_preview,
    read_lines,
    stat_path,
    usage,
)

_READ_RATE_LIMIT = (60, 60)
_PATH = {
    "type": "string",
    "description": "Path relative to user workspace root (e.g. uploads/doc.pdf, agent/notes.md).",
}


def _workspace_error_result(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


async def _list_dir_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    try:
        return list_dir(
            user_id,
            relative=str(arguments.get("path") or "."),
            recursive=bool(arguments.get("recursive", False)),
            max_entries=int(arguments.get("max_entries", 100)),
        )
    except WorkspaceError as exc:
        return _workspace_error_result(exc)


async def _stat_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    path = str(arguments.get("path") or "").strip()
    if not path:
        raise ValueError("path is required")
    return stat_path(user_id, path)


async def _read_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    path = str(arguments.get("path") or "").strip()
    if not path:
        raise ValueError("path is required")
    preview_lines = arguments.get("preview_lines")
    try:
        return read_file_preview(
            user_id,
            relative=path,
            preview_lines=int(preview_lines) if preview_lines is not None else None,
        )
    except (WorkspaceError, ValueError) as exc:
        return _workspace_error_result(exc)


async def _read_lines_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    path = str(arguments.get("path") or "").strip()
    if not path:
        raise ValueError("path is required")
    start_line = int(arguments.get("start_line", 0))
    end_line = arguments.get("end_line")
    limit = arguments.get("limit")
    try:
        return read_lines(
            user_id,
            relative=path,
            start_line=start_line,
            end_line=int(end_line) if end_line is not None else None,
            limit=int(limit) if limit is not None else None,
        )
    except (WorkspaceError, ValueError) as exc:
        return _workspace_error_result(exc)


async def _usage_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    return usage(user_id)


async def _find_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    pattern = str(arguments.get("pattern") or "").strip()
    if not pattern:
        raise ValueError("pattern is required")
    try:
        return find_files(
            user_id,
            pattern=pattern,
            max_results=int(arguments.get("max_results", 50)),
        )
    except WorkspaceError as exc:
        return _workspace_error_result(exc)


async def _grep_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    pattern = str(arguments.get("pattern") or "").strip()
    if not pattern:
        raise ValueError("pattern is required")
    try:
        return grep_files(
            user_id,
            pattern=pattern,
            relative=str(arguments.get("path") or "."),
            glob_pattern=str(arguments["glob"]) if arguments.get("glob") else None,
            ignore_case=bool(arguments.get("ignore_case", False)),
            max_matches=int(arguments["max_matches"]) if arguments.get("max_matches") else None,
            context_lines=int(arguments.get("context_lines", 0)),
        )
    except (WorkspaceError, ValueError) as exc:
        return _workspace_error_result(exc)


WORKSPACE_LIST_DIR = ToolSpec(
    name="workspace.list_dir",
    description=(
        "List files and directories in the user's workspace sandbox (like ls -l). "
        "Paths are relative to the per-user workspace root."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {**_PATH, "default": "."},
            "recursive": {
                "type": "boolean",
                "default": False,
                "description": "List recursively when true.",
            },
            "max_entries": {
                "type": "integer",
                "default": 100,
                "description": "Maximum entries to return.",
            },
        },
    },
    handler=_list_dir_handler,
    tags=("workspace", "read", "filesystem"),
    rate_limit=_READ_RATE_LIMIT,
    examples=("list workspace files", "ls uploads folder"),
)

WORKSPACE_STAT = ToolSpec(
    name="workspace.stat",
    description=(
        "Get metadata for a workspace file or directory: size, mime, timestamps, "
        "line count for text, file_ref for binary. Use before read/send."
    ),
    parameters={
        "type": "object",
        "properties": {"path": _PATH},
        "required": ["path"],
    },
    handler=_stat_handler,
    tags=("workspace", "read", "filesystem"),
    rate_limit=_READ_RATE_LIMIT,
    examples=("check file size", "file metadata", "does path exist"),
)

WORKSPACE_READ_FILE = ToolSpec(
    name="workspace.read_file",
    description=(
        "Preview a workspace file. Text files return the first ~30 lines only — "
        "use workspace.read_lines for ranges. Image files load into vision context "
        "(like Telegram photos). Binary files return file_ref for telegram.send_file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": _PATH,
            "preview_lines": {
                "type": "integer",
                "description": "Optional preview line count (capped by server config).",
            },
        },
        "required": ["path"],
    },
    handler=_read_file_handler,
    tags=("workspace", "read", "filesystem"),
    rate_limit=_READ_RATE_LIMIT,
    parallel_safe=False,
    examples=("preview text file", "view saved image", "peek at log"),
)

WORKSPACE_READ_LINES = ToolSpec(
    name="workspace.read_lines",
    description=(
        "Read a line range from a text workspace file. "
        "Use start_line + end_line (inclusive), e.g. 20–145."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": _PATH,
            "start_line": {
                "type": "integer",
                "description": "First line to read (1-based).",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to read (1-based, inclusive).",
            },
            "limit": {
                "type": "integer",
                "description": "Alternative to end_line: number of lines from start_line.",
            },
        },
        "required": ["path", "start_line"],
    },
    handler=_read_lines_handler,
    tags=("workspace", "read", "filesystem"),
    rate_limit=_READ_RATE_LIMIT,
    examples=("read lines 20-145", "read chunk of csv"),
)

WORKSPACE_USAGE = ToolSpec(
    name="workspace.usage",
    description="Workspace storage quota: bytes used, file count, limits, zone paths.",
    parameters={"type": "object", "properties": {}},
    handler=_usage_handler,
    tags=("workspace", "read", "filesystem"),
    rate_limit=_READ_RATE_LIMIT,
    examples=("workspace quota", "disk usage sandbox"),
)

WORKSPACE_FIND = ToolSpec(
    name="workspace.find",
    description="Find workspace files/directories by glob pattern (e.g. agent/**/*.md).",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob from workspace root, e.g. uploads/*.pdf or agent/**/*.txt",
            },
            "max_results": {"type": "integer", "default": 50},
        },
        "required": ["pattern"],
    },
    handler=_find_handler,
    tags=("workspace", "read", "filesystem"),
    rate_limit=_READ_RATE_LIMIT,
    examples=("find all markdown files", "locate pdf in uploads"),
)

WORKSPACE_GREP = ToolSpec(
    name="workspace.grep",
    description=(
        "Search text files in workspace with regex. Skips binary files. "
        "Use read_lines on match paths for surrounding context."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern."},
            "path": {**_PATH, "default": ".", "description": "File or directory to search."},
            "glob": {
                "type": "string",
                "description": "Optional filename glob filter when path is a directory (e.g. *.py).",
            },
            "ignore_case": {"type": "boolean", "default": False},
            "max_matches": {"type": "integer", "description": "Cap on returned matches."},
            "context_lines": {
                "type": "integer",
                "default": 0,
                "description": "Lines of context before/after each match (0-3).",
            },
        },
        "required": ["pattern"],
    },
    handler=_grep_handler,
    tags=("workspace", "read", "filesystem"),
    rate_limit=_READ_RATE_LIMIT,
    examples=("grep error in logs", "search csv column value"),
)

WORKSPACE_READ_TOOLS: tuple[ToolSpec, ...] = (
    WORKSPACE_LIST_DIR,
    WORKSPACE_STAT,
    WORKSPACE_READ_FILE,
    WORKSPACE_READ_LINES,
    WORKSPACE_USAGE,
    WORKSPACE_FIND,
    WORKSPACE_GREP,
)
