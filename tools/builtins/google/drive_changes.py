from __future__ import annotations

from typing import Any

from tools.builtins.google.drive_client import drive_list_kwargs, drive_support_kwargs, run_drive_call
from tools.builtins.google.drive_serialize import CHANGE_LIST_FIELDS, build_changes_list_response
from tools.context import get_run_context

_MAX_PAGE_SIZE = 100


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


def _optional_drive_id(arguments: dict[str, Any]) -> str | None:
    drive_id = str(arguments.get("drive_id") or "").strip()
    return drive_id or None


async def get_changes_start_token_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    drive_id = _optional_drive_id(arguments)

    def _call(service):
        kwargs: dict[str, Any] = {**drive_support_kwargs()}
        if drive_id:
            kwargs["driveId"] = drive_id
        return service.changes().getStartPageToken(**kwargs).execute()

    response = await run_drive_call(user_id, _call)
    token = str(response.get("startPageToken") or "").strip()
    if not token:
        raise RuntimeError("Drive API did not return startPageToken")
    payload: dict[str, Any] = {"start_page_token": token}
    if drive_id:
        payload["drive_id"] = drive_id
    return payload


async def list_changes_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    page_token = str(arguments.get("page_token") or "").strip()
    if not page_token:
        raise ValueError("page_token is required — call get_changes_start_token first")
    page_size = min(int(arguments.get("page_size", 100)), _MAX_PAGE_SIZE)
    drive_id = _optional_drive_id(arguments)

    def _call(service):
        kwargs: dict[str, Any] = {
            "pageToken": page_token,
            "pageSize": page_size,
            "fields": CHANGE_LIST_FIELDS,
            "includeRemoved": True,
            **drive_list_kwargs(),
        }
        if drive_id:
            kwargs["driveId"] = drive_id
        return service.changes().list(**kwargs).execute()

    response = await run_drive_call(user_id, _call)
    payload = build_changes_list_response(response)
    if drive_id:
        payload["drive_id"] = drive_id
    return payload
