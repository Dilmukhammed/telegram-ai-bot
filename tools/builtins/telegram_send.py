from __future__ import annotations

from typing import Any

from tools.schema import ToolSpec
from tools.context import get_run_context
from tools.outbound_files import OutboundDelivery, require_outbound_queue
from tools.run_files import require_run_file_store
from tools.telegram_limits import (
    format_byte_size,
    resolve_send_kind,
    telegram_limit_bytes,
    telegram_limit_error,
)
from tools.text_file_encoding import ensure_utf8_bom_for_mobile
from tools.filename_utils import ensure_filename_extension
from tools.workspace.errors import WorkspaceNotFoundError
from tools.workspace.store import read_workspace_bytes


async def _queue_outbound(
    *,
    raw: bytes,
    filename: str,
    mime_type: str | None,
    as_kind: str | None,
    caption: str | None,
    source_label: str,
) -> dict[str, Any]:
    from config import get_settings

    settings = get_settings()
    queue = require_outbound_queue()

    kind = resolve_send_kind(as_kind or "auto", mime_type)
    limit_bytes = telegram_limit_bytes(kind, settings=settings)
    size = len(raw)
    if size > limit_bytes:
        return {
            "ok": False,
            "error": telegram_limit_error(
                size_bytes=size,
                kind=kind,
                limit_bytes=limit_bytes,
            ),
            "filename": filename,
            "size_bytes": size,
            "telegram_kind": kind,
            "telegram_limit_bytes": limit_bytes,
            "telegram_limit": format_byte_size(limit_bytes),
            "source": source_label,
        }

    delivery_name = ensure_filename_extension(filename, mime_type)
    payload = ensure_utf8_bom_for_mobile(
        raw,
        filename=delivery_name,
        mime_type=mime_type,
    )
    queue.enqueue(
        OutboundDelivery(
            data=payload,
            filename=delivery_name,
            mime_type=mime_type,
            kind=kind,
            caption=caption,
        )
    )
    return {
        "ok": True,
        "queued": True,
        "filename": delivery_name,
        "mime_type": mime_type,
        "size_bytes": size,
        "telegram_kind": kind,
        "caption": caption,
        "source": source_label,
    }


async def _send_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = str(arguments.get("file_ref") or "").strip()
    workspace_path = str(arguments.get("path") or "").strip()
    if bool(file_ref) == bool(workspace_path):
        raise ValueError("provide exactly one of file_ref or path")

    caption = str(arguments.get("caption") or "").strip() or None
    as_kind = str(arguments.get("as") or "auto") if arguments.get("as") is not None else "auto"

    if workspace_path:
        ctx = get_run_context()
        if ctx.user_id is None:
            return {"ok": False, "error": "Telegram user_id is missing in tool context"}
        try:
            target, raw, mime_type = read_workspace_bytes(ctx.user_id, workspace_path)
        except WorkspaceNotFoundError as exc:
            return {"ok": False, "error": str(exc), "path": workspace_path}
        result = await _queue_outbound(
            raw=raw,
            filename=target.name,
            mime_type=mime_type,
            as_kind=as_kind,
            caption=caption,
            source_label=f"workspace:{workspace_path}",
        )
        if result.get("ok"):
            result["path"] = workspace_path
        return result

    store = require_run_file_store()
    ctx = get_run_context()

    try:
        stored = store.resolve(file_ref)
    except KeyError as exc:
        return {"ok": False, "error": str(exc), "file_ref": file_ref}

    if ctx.user_id is None or stored.user_id != ctx.user_id:
        return {
            "ok": False,
            "error": "file_ref is not available for this user in the current run",
            "file_ref": file_ref,
        }

    raw = stored.path.read_bytes()
    result = await _queue_outbound(
        raw=raw,
        filename=stored.filename,
        mime_type=stored.mime_type,
        as_kind=as_kind,
        caption=caption,
        source_label=f"file_ref:{file_ref}",
    )
    if result.get("ok"):
        result["file_ref"] = file_ref
    return result


TELEGRAM_SEND_FILE = ToolSpec(
    name="telegram.send_file",
    description=(
        "Send a file to the user in Telegram chat. "
        "Use file_ref from google.drive.download_file, google.drive.export_file, "
        "google.gmail.get_attachment, or workspace.stat/read_file. "
        "Alternatively use path for a workspace file (e.g. uploads/doc.pdf). "
        "Call only when the user asked to receive the file. "
        "Returns an error if the file exceeds Telegram size limits."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_ref": {
                "type": "string",
                "description": "Opaque ref from a download/export/attachment tool in this run.",
            },
            "path": {
                "type": "string",
                "description": "Workspace-relative path (xor file_ref), e.g. agent/report.pdf.",
            },
            "as": {
                "type": "string",
                "enum": ["auto", "document", "photo", "audio"],
                "default": "auto",
                "description": "How to send in Telegram. auto picks from mime_type.",
            },
            "caption": {
                "type": "string",
                "description": "Optional caption (document/photo only).",
            },
        },
    },
    handler=_send_file_handler,
    tags=("telegram", "bot", "delivery"),
    cache_ttl_seconds=None,
    rate_limit=(40, 60),
    parallel_safe=True,
    examples=(
        "send downloaded drive file to user",
        "deliver gmail attachment in chat",
        "send workspace file to telegram",
    ),
)
