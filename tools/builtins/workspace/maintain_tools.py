from __future__ import annotations

from typing import Any

from tools.builtins.workspace.workspace_checker import WORKSPACE_CHECKER_QUESTIONS_BY_TOOL
from tools.schema import ToolSpec
from tools.workspace.errors import WorkspaceError
from tools.workspace.store import (
    _require_user_id,
    clear_zone,
    copy_path,
    delete_path,
    import_from_file_ref,
    unzip_file,
)

_WRITE_RATE_LIMIT = (60, 60)
_DELETE_RATE_LIMIT = (20, 60)
_PATH = {
    "type": "string",
    "description": "Path relative to user workspace root.",
}


def _workspace_error_result(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


async def _copy_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    from_path = str(arguments.get("from_path") or "").strip()
    to_path = str(arguments.get("to_path") or "").strip()
    if not from_path or not to_path:
        raise ValueError("from_path and to_path are required")
    try:
        return copy_path(
            user_id,
            from_relative=from_path,
            to_relative=to_path,
            overwrite=bool(arguments.get("overwrite", False)),
        )
    except WorkspaceError as exc:
        return _workspace_error_result(exc)


async def _delete_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    path = str(arguments.get("path") or "").strip()
    if not path:
        raise ValueError("path is required")
    try:
        return delete_path(
            user_id,
            relative=path,
            recursive=bool(arguments.get("recursive", False)),
            confirm=bool(arguments.get("confirm", False)),
        )
    except (WorkspaceError, ValueError) as exc:
        return _workspace_error_result(exc)


async def _clear_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    zone = str(arguments.get("zone") or "").strip()
    if not zone:
        raise ValueError("zone is required")
    try:
        return clear_zone(user_id, zone=zone, confirm=bool(arguments.get("confirm", False)))
    except ValueError as exc:
        return _workspace_error_result(exc)


async def _import_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_ref = str(arguments.get("file_ref") or "").strip()
    path = str(arguments.get("path") or "").strip()
    if not file_ref or not path:
        raise ValueError("file_ref and path are required")
    try:
        return import_from_file_ref(
            user_id,
            file_ref=file_ref,
            relative=path,
            overwrite=bool(arguments.get("overwrite", True)),
        )
    except (WorkspaceError, ValueError, RuntimeError) as exc:
        return _workspace_error_result(exc)


async def _unzip_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    path = str(arguments.get("path") or "").strip()
    if not path:
        raise ValueError("path is required")
    dest = arguments.get("dest")
    try:
        return unzip_file(
            user_id,
            relative=path,
            dest_relative=str(dest).strip() if dest else None,
            overwrite=bool(arguments.get("overwrite", False)),
        )
    except WorkspaceError as exc:
        return _workspace_error_result(exc)


WORKSPACE_COPY = ToolSpec(
    name="workspace.copy",
    description="Copy a file or directory within the workspace sandbox.",
    parameters={
        "type": "object",
        "properties": {
            "from_path": _PATH,
            "to_path": _PATH,
            "overwrite": {"type": "boolean", "default": False},
        },
        "required": ["from_path", "to_path"],
    },
    handler=_copy_handler,
    tags=("workspace", "write", "filesystem"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("copy file to exports", "duplicate notes"),
    verification_questions=WORKSPACE_CHECKER_QUESTIONS_BY_TOOL["workspace.copy"],
)

WORKSPACE_DELETE = ToolSpec(
    name="workspace.delete",
    description="Delete a workspace file or directory. Requires confirm=true.",
    parameters={
        "type": "object",
        "properties": {
            "path": _PATH,
            "recursive": {
                "type": "boolean",
                "default": False,
                "description": "Required for non-empty directories.",
            },
            "confirm": {
                "type": "boolean",
                "default": False,
                "description": "Must be true to delete.",
            },
        },
        "required": ["path", "confirm"],
    },
    handler=_delete_handler,
    tags=("workspace", "write", "filesystem"),
    rate_limit=_DELETE_RATE_LIMIT,
    parallel_safe=False,
    examples=("delete temp file", "remove empty folder"),
    verification_questions=WORKSPACE_CHECKER_QUESTIONS_BY_TOOL["workspace.delete"],
)

WORKSPACE_CLEAR = ToolSpec(
    name="workspace.clear",
    description=(
        "Clear a workspace zone (agent, exports, uploads, or all). "
        "Requires confirm=true."
    ),
    parameters={
        "type": "object",
        "properties": {
            "zone": {
                "type": "string",
                "enum": ["agent", "exports", "uploads", "all"],
            },
            "confirm": {"type": "boolean", "default": False},
        },
        "required": ["zone", "confirm"],
    },
    handler=_clear_handler,
    tags=("workspace", "write", "filesystem"),
    rate_limit=_DELETE_RATE_LIMIT,
    parallel_safe=False,
    examples=("clear agent folder", "wipe exports cache"),
    verification_questions=WORKSPACE_CHECKER_QUESTIONS_BY_TOOL["workspace.clear"],
)

WORKSPACE_IMPORT_FROM_FILE_REF = ToolSpec(
    name="workspace.import_from_file_ref",
    description=(
        "Copy a file from the current run's file_ref store (Drive/Gmail download) "
        "into the persistent workspace."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": {"type": "string"},
            "path": _PATH,
            "overwrite": {"type": "boolean", "default": True},
        },
        "required": ["file_ref", "path"],
    },
    handler=_import_handler,
    tags=("workspace", "write", "filesystem"),
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("persist drive download", "save attachment to workspace"),
    verification_questions=WORKSPACE_CHECKER_QUESTIONS_BY_TOOL["workspace.import_from_file_ref"],
)

WORKSPACE_UNZIP = ToolSpec(
    name="workspace.unzip",
    description=(
        "Extract a .zip file inside the workspace. Zip-slip safe; rejects encrypted archives."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to .zip file in workspace.",
            },
            "dest": {
                "type": "string",
                "description": "Destination directory (default: folder named like zip stem).",
            },
            "overwrite": {"type": "boolean", "default": False},
        },
        "required": ["path"],
    },
    handler=_unzip_handler,
    tags=("workspace", "write", "filesystem"),
    rate_limit=_WRITE_RATE_LIMIT,
    parallel_safe=False,
    examples=("extract uploaded zip", "unzip archive to agent"),
    verification_questions=WORKSPACE_CHECKER_QUESTIONS_BY_TOOL["workspace.unzip"],
)

WORKSPACE_MAINTAIN_TOOLS: tuple[ToolSpec, ...] = (
    WORKSPACE_COPY,
    WORKSPACE_DELETE,
    WORKSPACE_CLEAR,
    WORKSPACE_IMPORT_FROM_FILE_REF,
    WORKSPACE_UNZIP,
)
