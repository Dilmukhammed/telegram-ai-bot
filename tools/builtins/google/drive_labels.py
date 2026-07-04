from __future__ import annotations

from typing import Any

from tools.builtins.google.drive_client import drive_support_kwargs, run_drive_call
from tools.builtins.google.drive_serialize import (
    LABEL_LIST_FIELDS,
    MODIFIED_LABEL_FIELDS,
    build_labels_list_response,
    compact_label,
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


def _label_ids(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("add_labels and remove_labels must be arrays of label ids")
    ids: list[str] = []
    for item in values:
        label_id = str(item).strip()
        if label_id:
            ids.append(label_id)
    return ids


async def list_file_labels_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    page_size = min(int(arguments.get("page_size", 100)), _MAX_PAGE_SIZE)
    page_token = str(arguments.get("page_token") or "").strip() or None

    def _call(service):
        kwargs: dict[str, Any] = {
            "fileId": file_id,
            "maxResults": page_size,
            "fields": LABEL_LIST_FIELDS,
            **drive_support_kwargs(),
        }
        if page_token:
            kwargs["pageToken"] = page_token
        return service.files().listLabels(**kwargs).execute()

    response = await run_drive_call(user_id, _call)
    return {"file_id": file_id, **build_labels_list_response(response)}


async def modify_file_labels_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    add_labels = _label_ids(arguments.get("add_labels"))
    remove_labels = _label_ids(arguments.get("remove_labels"))
    if not add_labels and not remove_labels:
        raise ValueError("Provide at least one of: add_labels, remove_labels")

    modifications: list[dict[str, Any]] = []
    for label_id in remove_labels:
        modifications.append({"labelId": label_id, "removeLabel": True})
    for label_id in add_labels:
        modifications.append({"labelId": label_id})

    def _call(service):
        return (
            service.files()
            .modifyLabels(
                fileId=file_id,
                body={"labelModifications": modifications},
                fields=MODIFIED_LABEL_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    response = await run_drive_call(user_id, _call)
    modified = response.get("modifiedLabels") or []
    return {
        "updated": True,
        "file_id": file_id,
        "count": len(modified),
        "labels": [compact_label(item) for item in modified],
    }
