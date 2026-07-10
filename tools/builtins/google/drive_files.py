from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

from googleapiclient.http import MediaIoBaseDownload

from config import get_settings, google_limit_label
from tools.builtins.google.drive_client import drive_list_kwargs, drive_support_kwargs, run_drive_call
from tools.builtins.google.drive_serialize import (
    CREATE_FILE_FIELDS,
    FOLDER_MIME,
    GET_FILE_FIELDS,
    LIST_FILE_FIELDS,
    SHORTCUT_MIME,
    build_list_response,
    compact_about,
    compact_created_file,
    compact_file_detail,
    default_export_mime,
    is_google_workspace_file,
    truncate_text,
)
from tools.builtins.google.drive_upload import (
    create_file_with_content,
    create_metadata_file,
    update_file_with_content,
)
from tools.context import get_run_context
from tools.run_files import require_run_file_store
from tools.workspace.errors import WorkspaceError
from tools.workspace.store import read_workspace_bytes

_MAX_PAGE_SIZE = 100
_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/csv",
    "application/x-yaml",
}


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


def _page_size(arguments: dict[str, Any]) -> int:
    settings = get_settings()
    default = settings.drive_default_max_results
    return min(int(arguments.get("page_size", default)), _MAX_PAGE_SIZE)


def _append_trash_filter(q: str, *, include_trashed: bool) -> str:
    if include_trashed:
        return q.strip()
    lowered = q.lower()
    if "trashed" in lowered:
        return q.strip()
    q = q.strip()
    if q:
        return f"{q} and trashed=false"
    return "trashed=false"


def _list_files_call(
    service,
    *,
    q: str | None = None,
    page_size: int,
    page_token: str | None = None,
    order_by: str | None = None,
    corpora: str | None = None,
    drive_id: str | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "pageSize": page_size,
        "fields": LIST_FILE_FIELDS,
        **drive_list_kwargs(),
    }
    if q:
        kwargs["q"] = q
    if page_token:
        kwargs["pageToken"] = page_token
    if order_by:
        kwargs["orderBy"] = order_by
    if corpora:
        kwargs["corpora"] = corpora
    if drive_id:
        kwargs["driveId"] = drive_id
    return service.files().list(**kwargs).execute()


def _download_bytes(service, file_id: str) -> bytes:
    request = service.files().get_media(fileId=file_id, **drive_support_kwargs())
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _is_probably_text(mime_type: str | None) -> bool:
    if not mime_type:
        return True
    if mime_type.startswith(_TEXT_MIME_PREFIXES):
        return True
    return mime_type in _TEXT_MIME_TYPES


def _store_bytes_for_agent(
    data: bytes,
    *,
    filename: str,
    mime_type: str | None,
) -> dict[str, Any]:
    store = require_run_file_store()
    stored = store.save(data, filename=filename, mime_type=mime_type)
    payload: dict[str, Any] = dict(stored)
    if _is_probably_text(mime_type):
        text = _decode_bytes(data)
        settings = get_settings()
        if len(text) <= settings.drive_max_export_chars:
            payload["text"] = text
        else:
            payload["text_preview"] = truncate_text(text, 2000)
    return payload


async def get_about_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()

    def _call(service):
        return service.about().get(
            fields="user,storageQuota,maxUploadSize,canCreateDrives,importFormats,exportFormats"
        ).execute()

    about = await run_drive_call(user_id, _call)
    return compact_about(about)


async def search_files_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    q = str(arguments.get("q", "")).strip()
    if not q:
        raise ValueError("q is required")
    include_trashed = bool(arguments.get("include_trashed", False))
    page_size = _page_size(arguments)
    page_token = str(arguments.get("page_token") or "").strip() or None
    order_by = str(arguments.get("order_by") or "").strip() or None
    corpora = str(arguments.get("corpora") or "").strip() or None
    drive_id = str(arguments.get("drive_id") or "").strip() or None
    query = _append_trash_filter(q, include_trashed=include_trashed)

    def _call(service):
        return _list_files_call(
            service,
            q=query,
            page_size=page_size,
            page_token=page_token,
            order_by=order_by,
            corpora=corpora,
            drive_id=drive_id,
        )

    response = await run_drive_call(user_id, _call)
    return {"q": q, **build_list_response(response)}


async def list_files_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    folder_id = str(arguments.get("folder_id") or "").strip()
    page_size = _page_size(arguments)
    page_token = str(arguments.get("page_token") or "").strip() or None
    order_by = str(arguments.get("order_by") or "").strip() or None
    if folder_id:
        query = _append_trash_filter(f"'{folder_id}' in parents", include_trashed=False)
    else:
        query = "trashed=false"

    def _call(service):
        return _list_files_call(
            service,
            q=query,
            page_size=page_size,
            page_token=page_token,
            order_by=order_by,
        )

    response = await run_drive_call(user_id, _call)
    return build_list_response(response)


async def get_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = str(arguments["file_id"]).strip()

    def _call(service):
        return (
            service.files()
            .get(fileId=file_id, fields=GET_FILE_FIELDS, **drive_support_kwargs())
            .execute()
        )

    file_obj = await run_drive_call(user_id, _call)
    return {"file": compact_file_detail(file_obj)}


async def download_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = str(arguments["file_id"]).strip()
    settings = get_settings()

    def _fetch_meta(service):
        return (
            service.files()
            .get(fileId=file_id, fields="id,name,mimeType,size", **drive_support_kwargs())
            .execute()
        )

    meta = await run_drive_call(user_id, _fetch_meta)
    mime_type = str(meta.get("mimeType") or "")
    if is_google_workspace_file(mime_type):
        return {
            "ok": False,
            "error": (
                "Google Workspace files cannot be downloaded directly. "
                f"Use export_file with mime_type={default_export_mime(mime_type)!r}."
            ),
            "file_id": file_id,
            "mime_type": mime_type,
        }

    declared_size = int(meta.get("size") or 0)
    if declared_size > settings.drive_max_download_bytes:
        return {
            "ok": False,
            "error": (
                f"File too large ({declared_size} bytes; "
                f"{google_limit_label('drive_blob')}: {settings.drive_max_download_bytes} bytes)"
            ),
            "file_id": file_id,
            "filename": meta.get("name"),
            "mime_type": mime_type,
            "size": declared_size,
        }

    def _fetch_bytes(service):
        return _download_bytes(service, file_id)

    data = await run_drive_call(user_id, _fetch_bytes)
    if len(data) > settings.drive_max_download_bytes:
        return {
            "ok": False,
            "error": (
                f"File too large ({len(data)} bytes; "
                f"{google_limit_label('drive_blob')}: {settings.drive_max_download_bytes} bytes)"
            ),
            "file_id": file_id,
            "filename": meta.get("name"),
            "mime_type": mime_type,
            "size": len(data),
        }

    filename = str(meta.get("name") or "file")
    result: dict[str, Any] = {
        "ok": True,
        "file_id": file_id,
        **_store_bytes_for_agent(data, filename=filename, mime_type=mime_type),
    }
    return result


async def export_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = str(arguments["file_id"]).strip()
    settings = get_settings()

    def _fetch_meta(service):
        return (
            service.files()
            .get(fileId=file_id, fields="id,name,mimeType", **drive_support_kwargs())
            .execute()
        )

    meta = await run_drive_call(user_id, _fetch_meta)
    mime_type = str(meta.get("mimeType") or "")
    export_mime = str(arguments.get("mime_type") or "").strip() or default_export_mime(mime_type)

    def _export(service):
        return service.files().export(fileId=file_id, mimeType=export_mime).execute()

    data = await run_drive_call(user_id, _export)
    if isinstance(data, bytes):
        raw = data
    else:
        raw = str(data).encode("utf-8")

    if export_mime.startswith("text/") or export_mime in {"application/json", "application/csv"}:
        text = _decode_bytes(raw)
        filename = str(meta.get("name") or "export")
        stored = _store_bytes_for_agent(raw, filename=filename, mime_type=export_mime)
        return {
            "ok": True,
            "file_id": file_id,
            "filename": stored.get("filename"),
            "source_mime_type": mime_type,
            "mime_type": export_mime,
            "file_ref": stored["file_ref"],
            "size": stored["size"],
            "text": truncate_text(text, settings.drive_max_export_chars),
        }

    if len(raw) > settings.drive_max_export_bytes:
        return {
            "ok": False,
            "error": (
                f"Export too large ({len(raw)} bytes; "
                f"{google_limit_label('drive_export')}: {settings.drive_max_export_bytes} bytes). "
                "Google files.export cannot return more than 10 MB — use google.sheets.* for large Sheets "
                "or download a non-Workspace blob file."
            ),
            "file_id": file_id,
            "mime_type": export_mime,
        }

    filename = str(meta.get("name") or "export")
    stored = _store_bytes_for_agent(raw, filename=filename, mime_type=export_mime)
    return {
        "ok": True,
        "file_id": file_id,
        "source_mime_type": mime_type,
        "mime_type": export_mime,
        **stored,
    }


async def list_folder_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    folder_id = str(arguments.get("folder_id") or "root").strip() or "root"
    return await list_files_handler({**arguments, "folder_id": folder_id})


async def list_starred_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    page_size = _page_size(arguments)
    page_token = str(arguments.get("page_token") or "").strip() or None

    def _call(service):
        return _list_files_call(
            service,
            q="starred=true and trashed=false",
            page_size=page_size,
            page_token=page_token,
        )

    response = await run_drive_call(user_id, _call)
    return build_list_response(response)


async def list_trash_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    page_size = _page_size(arguments)
    page_token = str(arguments.get("page_token") or "").strip() or None

    def _call(service):
        return _list_files_call(
            service,
            q="trashed=true",
            page_size=page_size,
            page_token=page_token,
        )

    response = await run_drive_call(user_id, _call)
    return build_list_response(response)


async def list_shared_with_me_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    page_size = _page_size(arguments)
    page_token = str(arguments.get("page_token") or "").strip() or None

    def _call(service):
        return _list_files_call(
            service,
            q="sharedWithMe=true and trashed=false",
            page_size=page_size,
            page_token=page_token,
        )

    response = await run_drive_call(user_id, _call)
    return build_list_response(response)


async def list_recent_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    page_size = _page_size(arguments)
    page_token = str(arguments.get("page_token") or "").strip() or None

    def _call(service):
        return _list_files_call(
            service,
            q="trashed=false",
            page_size=page_size,
            page_token=page_token,
            order_by="viewedByMeTime desc",
        )

    response = await run_drive_call(user_id, _call)
    return build_list_response(response)


def _require_confirm(arguments: dict[str, Any], message: str) -> None:
    if arguments.get("confirm") is not True:
        raise ValueError(message)


def _parent_ids(parent_id: str | None) -> list[str]:
    parent = str(parent_id or "").strip()
    if not parent or parent == "root":
        return []
    return [parent]


def _decode_upload_content(
    arguments: dict[str, Any],
    *,
    user_id: int | None = None,
) -> tuple[bytes, str, str | None]:
    """Return (content, mime_type, source_path).

    Exactly one of: workspace ``path``, ``content_text``, ``content_base64``.
    """
    path = str(arguments.get("path") or "").strip()
    has_text = "content_text" in arguments and arguments["content_text"] is not None
    has_b64 = "content_base64" in arguments and arguments["content_base64"] is not None
    sources = sum(bool(x) for x in (path, has_text, has_b64))
    if sources != 1:
        raise ValueError("provide exactly one of path, content_text, or content_base64")

    if path:
        if user_id is None:
            raise RuntimeError("Telegram user_id is missing in tool context")
        try:
            _target, content, guessed_mime = read_workspace_bytes(user_id, path)
        except WorkspaceError as exc:
            raise ValueError(f"workspace path error: {exc}") from exc
        mime_override = str(arguments.get("mime_type") or "").strip()
        mime_type = mime_override or guessed_mime or "application/octet-stream"
        return content, mime_type, path

    if has_text:
        text = str(arguments["content_text"])
        mime_type = str(arguments.get("mime_type") or "text/plain").strip() or "text/plain"
        return text.encode("utf-8"), mime_type, None

    raw = str(arguments["content_base64"]).strip()
    mime_type = str(arguments.get("mime_type") or "application/octet-stream").strip()
    if not mime_type:
        mime_type = "application/octet-stream"
    return base64.b64decode(raw), mime_type, None


def _created_payload(file_obj: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"created": True, "file": compact_created_file(file_obj), **extra}


async def _fetch_parents(user_id: int, file_id: str) -> list[str]:
    def _call(service):
        result = (
            service.files()
            .get(fileId=file_id, fields="parents", **drive_support_kwargs())
            .execute()
        )
        return [str(item) for item in (result.get("parents") or [])]

    return await run_drive_call(user_id, _call)


async def create_folder_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    name = str(arguments.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")
    metadata: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME}
    parents = _parent_ids(arguments.get("parent_id"))
    if parents:
        metadata["parents"] = parents

    def _call(service):
        return create_metadata_file(service, metadata=metadata)

    file_obj = await run_drive_call(user_id, _call)
    return _created_payload(file_obj)


async def create_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    name = str(arguments.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")
    mime_type = str(arguments.get("mime_type") or "application/octet-stream").strip()
    metadata: dict[str, Any] = {"name": name, "mimeType": mime_type}
    description = str(arguments.get("description") or "").strip()
    if description:
        metadata["description"] = description
    parents = _parent_ids(arguments.get("parent_id"))
    if parents:
        metadata["parents"] = parents

    def _call(service):
        return create_metadata_file(service, metadata=metadata)

    file_obj = await run_drive_call(user_id, _call)
    return _created_payload(file_obj)


async def upload_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    settings = get_settings()
    content, mime_type, source_path = _decode_upload_content(arguments, user_id=user_id)
    name = str(arguments.get("name") or "").strip()
    if not name:
        if source_path:
            name = Path(source_path).name
        else:
            raise ValueError("name is required when uploading content_text/content_base64")
    if len(content) > settings.drive_max_upload_bytes:
        raise ValueError(
            f"Upload too large ({len(content)} bytes; max {settings.drive_max_upload_bytes})"
        )
    metadata: dict[str, Any] = {"name": name, "mimeType": mime_type}
    parents = _parent_ids(arguments.get("parent_id"))
    if parents:
        metadata["parents"] = parents

    def _call(service):
        return create_file_with_content(
            service,
            metadata=metadata,
            content=content,
            mime_type=mime_type,
        )

    file_obj = await run_drive_call(user_id, _call)
    extra: dict[str, Any] = {"uploaded": True}
    if source_path:
        extra["source_path"] = source_path
    return _created_payload(file_obj, **extra)


async def update_file_metadata_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = str(arguments["file_id"]).strip()
    metadata: dict[str, Any] = {}
    if "name" in arguments and arguments["name"] is not None:
        metadata["name"] = str(arguments["name"]).strip()
    if "description" in arguments and arguments["description"] is not None:
        metadata["description"] = str(arguments["description"])
    if "starred" in arguments and arguments["starred"] is not None:
        metadata["starred"] = bool(arguments["starred"])
    if "trashed" in arguments and arguments["trashed"] is not None:
        metadata["trashed"] = bool(arguments["trashed"])
    if "properties" in arguments and arguments["properties"] is not None:
        metadata["properties"] = dict(arguments["properties"])
    if not metadata:
        raise ValueError("Provide at least one of: name, description, starred, trashed, properties")

    def _call(service):
        return (
            service.files()
            .update(
                fileId=file_id,
                body=metadata,
                fields=CREATE_FILE_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    file_obj = await run_drive_call(user_id, _call)
    return {"updated": True, "file": compact_created_file(file_obj)}


async def update_file_content_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    settings = get_settings()
    file_id = str(arguments["file_id"]).strip()
    content, mime_type, source_path = _decode_upload_content(arguments, user_id=user_id)

    def _fetch_meta(service):
        return (
            service.files()
            .get(fileId=file_id, fields="mimeType", **drive_support_kwargs())
            .execute()
        )

    meta = await run_drive_call(user_id, _fetch_meta)
    if is_google_workspace_file(str(meta.get("mimeType") or "")):
        raise ValueError("Cannot replace content of Google Workspace files via Drive upload.")

    if len(content) > settings.drive_max_upload_bytes:
        raise ValueError(
            f"Upload too large ({len(content)} bytes; max {settings.drive_max_upload_bytes})"
        )

    def _call(service):
        return update_file_with_content(
            service,
            file_id=file_id,
            content=content,
            mime_type=mime_type,
        )

    file_obj = await run_drive_call(user_id, _call)
    result: dict[str, Any] = {"updated": True, "file": compact_created_file(file_obj)}
    if source_path:
        result["source_path"] = source_path
    return result


async def copy_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = str(arguments["file_id"]).strip()
    body: dict[str, Any] = {}
    name = str(arguments.get("name") or "").strip()
    if name:
        body["name"] = name
    parents = _parent_ids(arguments.get("parent_id"))
    if parents:
        body["parents"] = parents

    def _call(service):
        return (
            service.files()
            .copy(
                fileId=file_id,
                body=body,
                fields=CREATE_FILE_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    file_obj = await run_drive_call(user_id, _call)
    return {"copied": True, "file": compact_created_file(file_obj)}


async def move_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = str(arguments["file_id"]).strip()
    new_parent_id = str(arguments["new_parent_id"]).strip()
    if not new_parent_id:
        raise ValueError("new_parent_id is required")
    remove_parent_id = str(arguments.get("remove_parent_id") or "").strip()
    if remove_parent_id:
        remove_parents = remove_parent_id
    else:
        parents = await _fetch_parents(user_id, file_id)
        remove_parents = ",".join(parents)

    def _call(service):
        kwargs: dict[str, Any] = {
            "fileId": file_id,
            "addParents": new_parent_id,
            "fields": CREATE_FILE_FIELDS,
            **drive_support_kwargs(),
        }
        if remove_parents:
            kwargs["removeParents"] = remove_parents
        return service.files().update(**kwargs).execute()

    file_obj = await run_drive_call(user_id, _call)
    return {"moved": True, "file": compact_created_file(file_obj)}


async def rename_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    name = str(arguments.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")
    return await update_file_metadata_handler(
        {"file_id": arguments["file_id"], "name": name},
    )


async def star_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await update_file_metadata_handler(
        {"file_id": arguments["file_id"], "starred": True},
    )


async def unstar_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await update_file_metadata_handler(
        {"file_id": arguments["file_id"], "starred": False},
    )


async def trash_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await update_file_metadata_handler(
        {"file_id": arguments["file_id"], "trashed": True},
    )


async def untrash_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await update_file_metadata_handler(
        {"file_id": arguments["file_id"], "trashed": False},
    )


async def delete_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(
        arguments,
        "confirm=true is required — this permanently deletes the file, not trash.",
    )
    user_id = _require_user_id()
    file_id = str(arguments["file_id"]).strip()

    def _call(service):
        service.files().delete(fileId=file_id, **drive_support_kwargs()).execute()
        return {"deleted": True, "file_id": file_id}

    return await run_drive_call(user_id, _call)


async def empty_trash_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(
        arguments,
        "confirm=true is required — this permanently empties Drive trash.",
    )
    user_id = _require_user_id()

    def _call(service):
        service.files().emptyTrash(**drive_support_kwargs()).execute()
        return {"emptied": True}

    return await run_drive_call(user_id, _call)


async def create_shortcut_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    name = str(arguments.get("name", "")).strip()
    target_file_id = str(arguments.get("target_file_id", "")).strip()
    if not name:
        raise ValueError("name is required")
    if not target_file_id:
        raise ValueError("target_file_id is required")
    metadata: dict[str, Any] = {
        "name": name,
        "mimeType": SHORTCUT_MIME,
        "shortcutDetails": {"targetId": target_file_id},
    }
    parents = _parent_ids(arguments.get("parent_id"))
    if parents:
        metadata["parents"] = parents

    def _call(service):
        return create_metadata_file(service, metadata=metadata)

    file_obj = await run_drive_call(user_id, _call)
    return _created_payload(file_obj, shortcut=True)


async def generate_file_ids_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    count = min(max(int(arguments.get("count", 1)), 1), 10)

    def _call(service):
        return service.files().generateIds(count=count).execute()

    response = await run_drive_call(user_id, _call)
    ids = [str(item) for item in (response.get("ids") or [])]
    return {"count": len(ids), "ids": ids}
