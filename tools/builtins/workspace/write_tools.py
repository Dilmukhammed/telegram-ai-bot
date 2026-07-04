from __future__ import annotations

from typing import Any

from tools.schema import ToolSpec
from tools.workspace.errors import WorkspaceError
from tools.workspace.store import (
    _require_user_id,
    append_file,
    mkdir,
    move_path,
    write_file,
)

_WRITE_RATE_LIMIT = (30, 60)
_PATH = {
    "type": "string",
    "description": "Path relative to user workspace root.",
}


def _workspace_error_result(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


async def _write_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    path = str(arguments.get("path") or "").strip()
    if not path:
        raise ValueError("path is required")
    try:
        return write_file(
            user_id,
            relative=path,
            content_text=arguments.get("content_text"),
            content_base64=arguments.get("content_base64"),
            mime_type=str(arguments["mime_type"]) if arguments.get("mime_type") else None,
            overwrite=bool(arguments.get("overwrite", True)),
        )
    except (WorkspaceError, ValueError) as exc:
        return _workspace_error_result(exc)


async def _append_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    path = str(arguments.get("path") or "").strip()
    content_text = arguments.get("content_text")
    if not path:
        raise ValueError("path is required")
    if content_text is None:
        raise ValueError("content_text is required")
    try:
        return append_file(user_id, relative=path, content_text=str(content_text))
    except (WorkspaceError, ValueError) as exc:
        return _workspace_error_result(exc)


async def _mkdir_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    path = str(arguments.get("path") or "").strip()
    if not path:
        raise ValueError("path is required")
    try:
        return mkdir(
            user_id,
            relative=path,
            parents=bool(arguments.get("parents", True)),
        )
    except WorkspaceError as exc:
        return _workspace_error_result(exc)


async def _move_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    from_path = str(arguments.get("from_path") or "").strip()
    to_path = str(arguments.get("to_path") or "").strip()
    if not from_path or not to_path:
        raise ValueError("from_path and to_path are required")
    try:
        return move_path(
            user_id,
            from_relative=from_path,
            to_relative=to_path,
            overwrite=bool(arguments.get("overwrite", False)),
        )
    except WorkspaceError as exc:
        return _workspace_error_result(exc)


WORKSPACE_WRITE_FILE = ToolSpec(
    name="workspace.write_file",
    description="Create or overwrite a file in the user workspace sandbox.",
    parameters={
        "type": "object",
        "properties": {
            "path": _PATH,
            "content_text": {"type": "string", "description": "UTF-8 text content."},
            "content_base64": {
                "type": "string",
                "description": "Base64-encoded binary content (xor content_text).",
            },
            "mime_type": {"type": "string"},
            "overwrite": {"type": "boolean", "default": True},
        },
        "required": ["path"],
    },
    handler=_write_file_handler,
    tags=("workspace", "write", "filesystem"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("save notes to agent/file.md", "write json file"),
)

WORKSPACE_APPEND_FILE = ToolSpec(
    name="workspace.append_file",
    description="Append UTF-8 text to a workspace file (create if missing).",
    parameters={
        "type": "object",
        "properties": {
            "path": _PATH,
            "content_text": {"type": "string"},
        },
        "required": ["path", "content_text"],
    },
    handler=_append_file_handler,
    tags=("workspace", "write", "filesystem"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("append log line", "add to notes"),
)

WORKSPACE_MKDIR = ToolSpec(
    name="workspace.mkdir",
    description="Create a directory in the workspace sandbox.",
    parameters={
        "type": "object",
        "properties": {
            "path": _PATH,
            "parents": {"type": "boolean", "default": True},
        },
        "required": ["path"],
    },
    handler=_mkdir_handler,
    tags=("workspace", "write", "filesystem"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("create agent/reports folder"),
)

WORKSPACE_MOVE = ToolSpec(
    name="workspace.move",
    description="Move or rename a file/directory within the workspace sandbox.",
    parameters={
        "type": "object",
        "properties": {
            "from_path": _PATH,
            "to_path": _PATH,
            "overwrite": {"type": "boolean", "default": False},
        },
        "required": ["from_path", "to_path"],
    },
    handler=_move_handler,
    tags=("workspace", "write", "filesystem"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("rename file", "move to uploads"),
)

WORKSPACE_WRITE_TOOLS: tuple[ToolSpec, ...] = (
    WORKSPACE_WRITE_FILE,
    WORKSPACE_APPEND_FILE,
    WORKSPACE_MKDIR,
    WORKSPACE_MOVE,
)
