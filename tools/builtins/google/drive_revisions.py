from __future__ import annotations

from typing import Any

from tools.builtins.google.drive_client import drive_support_kwargs, run_drive_call
from tools.builtins.google.drive_files import _require_confirm
from tools.builtins.google.drive_serialize import (
    REVISION_FIELDS,
    REVISION_LIST_FIELDS,
    build_revisions_list_response,
    compact_revision,
)
from tools.context import get_run_context

_MAX_PAGE_SIZE = 100


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


def _require_file_id(arguments: dict[str, Any]) -> str:
    file_id = str(arguments.get("file_id", "")).strip()
    if not file_id:
        raise ValueError("file_id is required")
    return file_id


def _require_revision_id(arguments: dict[str, Any]) -> str:
    revision_id = str(arguments.get("revision_id", "")).strip()
    if not revision_id:
        raise ValueError("revision_id is required")
    return revision_id


async def list_revisions_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    page_size = min(int(arguments.get("page_size", 100)), _MAX_PAGE_SIZE)
    page_token = str(arguments.get("page_token") or "").strip() or None

    def _call(service):
        kwargs: dict[str, Any] = {
            "fileId": file_id,
            "fields": REVISION_LIST_FIELDS,
            "pageSize": page_size,
            **drive_support_kwargs(),
        }
        if page_token:
            kwargs["pageToken"] = page_token
        return service.revisions().list(**kwargs).execute()

    response = await run_drive_call(user_id, _call)
    return {"file_id": file_id, **build_revisions_list_response(response)}


async def get_revision_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    revision_id = _require_revision_id(arguments)

    def _call(service):
        return (
            service.revisions()
            .get(
                fileId=file_id,
                revisionId=revision_id,
                fields=REVISION_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    revision = await run_drive_call(user_id, _call)
    return {"file_id": file_id, "revision": compact_revision(revision)}


async def update_revision_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    revision_id = _require_revision_id(arguments)
    if "keep_forever" not in arguments:
        raise ValueError("keep_forever is required")
    keep_forever = bool(arguments["keep_forever"])

    def _call(service):
        return (
            service.revisions()
            .update(
                fileId=file_id,
                revisionId=revision_id,
                body={"keepForever": keep_forever},
                fields=REVISION_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    revision = await run_drive_call(user_id, _call)
    return {
        "updated": True,
        "file_id": file_id,
        "revision": compact_revision(revision),
    }


async def delete_revision_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(
        arguments,
        "confirm=true is required — this permanently deletes a file revision.",
    )
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    revision_id = _require_revision_id(arguments)

    def _call(service):
        service.revisions().delete(
            fileId=file_id,
            revisionId=revision_id,
            **drive_support_kwargs(),
        ).execute()
        return {
            "deleted": True,
            "file_id": file_id,
            "revision_id": revision_id,
        }

    return await run_drive_call(user_id, _call)
