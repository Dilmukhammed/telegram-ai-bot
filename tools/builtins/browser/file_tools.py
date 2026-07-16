from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser._common import SESSION_HANDLE_PROP, lease_page
from tools.builtins.browser.errors import BrowserError
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.context import get_run_context
from tools.run_files import require_run_file_store
from tools.schema import ToolSpec
from tools.workspace.paths import resolve_workspace_path, sanitize_relative_path


def _resolve_upload_paths(arguments: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    file_refs = arguments.get("file_refs") or []
    if arguments.get("file_ref"):
        file_refs = [arguments["file_ref"], *file_refs]
    for ref in file_refs:
        stored = require_run_file_store().resolve(str(ref))
        paths.append(Path(stored.path))

    rel_paths = arguments.get("paths") or []
    if arguments.get("path"):
        rel_paths = [arguments["path"], *rel_paths]
    if rel_paths:
        user_id = get_run_context().user_id
        if user_id is None:
            raise BrowserError("Telegram user_id is missing in tool context")
        for rel in rel_paths:
            target = resolve_workspace_path(user_id, sanitize_relative_path(str(rel)))
            if not target.exists():
                raise BrowserError(f"Upload path not found: {rel}")
            paths.append(target)

    if not paths:
        raise BrowserError("Provide path/paths and/or file_ref/file_refs for upload")
    return paths


def _save_download(data: bytes, filename: str) -> dict[str, Any]:
    mime, _ = mimetypes.guess_type(filename)
    mime_type = mime or "application/octet-stream"
    store = require_run_file_store()
    saved = store.save(data, filename=filename, mime_type=mime_type)
    return {
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
        "mime_type": saved["mime_type"],
        "size": saved["size"],
    }


async def _upload_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    paths = _resolve_upload_paths(arguments)
    result = await pw.upload_files(session, str(arguments["ref"]), paths)
    result["size"] = sum(p.stat().st_size for p in paths if p.exists())
    return redact_browser_payload(result)


async def _download_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    ref = arguments.get("ref")
    data, filename = await pw.click_and_download(
        session,
        str(ref) if ref else None,
        timeout_ms=int(arguments.get("timeout_ms") or 60_000),
    )
    saved = _save_download(data, filename)
    return redact_browser_payload({"ok": True, **saved})


async def _wait_for_download_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    data, filename = await pw.wait_for_download(
        session,
        timeout_ms=int(arguments.get("timeout_ms") or 60_000),
    )
    saved = _save_download(data, filename)
    return redact_browser_payload({"ok": True, **saved})


BROWSER_UPLOAD = ToolSpec(
    name="browser.upload",
    description=(
        "Upload one or more files into a file input by ref. "
        "Use workspace path/paths and/or file_ref/file_refs."
    ),
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "ref": {"type": "string"},
            "path": {"type": "string", "description": "Workspace-relative path."},
            "paths": {
                "type": "array",
                "items": {"type": "string"},
            },
            "file_ref": {"type": "string"},
            "file_refs": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["ref"],
    },
    handler=_upload_handler,
    tags=("browser", "web", "write", "files"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.upload"),
    examples=("upload file to browser input", "attach file form"),
)

BROWSER_DOWNLOAD = ToolSpec(
    name="browser.download",
    description=(
        "Click a download trigger ref and capture the file into a file_ref "
        "(for telegram.send_file)."
    ),
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "ref": {
                "type": "string",
                "description": "Element that starts the download (required).",
            },
            "timeout_ms": {"type": "integer", "default": 60000},
        },
        "required": ["ref"],
    },
    handler=_download_handler,
    tags=("browser", "web", "files", "read"),
    cache_ttl_seconds=None,
    rate_limit=(20, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.download"),
    examples=("download file from browser", "click download link"),
)

BROWSER_WAIT_FOR_DOWNLOAD = ToolSpec(
    name="browser.wait_for_download",
    description=(
        "Wait for the next browser download event and save it as file_ref. "
        "Use when download was already triggered (or will fire soon)."
    ),
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "timeout_ms": {"type": "integer", "default": 60000},
        },
        "required": [],
    },
    handler=_wait_for_download_handler,
    tags=("browser", "web", "files", "read"),
    cache_ttl_seconds=None,
    rate_limit=(20, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.wait_for_download"),
    examples=("wait for browser download", "catch download file"),
)

BROWSER_FILE_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_UPLOAD,
    BROWSER_DOWNLOAD,
    BROWSER_WAIT_FOR_DOWNLOAD,
)
