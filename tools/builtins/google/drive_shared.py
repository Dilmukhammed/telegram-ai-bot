from __future__ import annotations

import uuid
from typing import Any

from tools.builtins.google.drive_client import run_drive_call
from tools.builtins.google.drive_files import _require_confirm
from tools.builtins.google.drive_serialize import (
    SHARED_DRIVE_FIELDS,
    SHARED_DRIVE_LIST_FIELDS,
    build_shared_drives_list_response,
    compact_shared_drive,
)
from tools.context import get_run_context

_MAX_PAGE_SIZE = 100


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


def _require_drive_id(arguments: dict[str, Any]) -> str:
    drive_id = str(arguments.get("drive_id", "")).strip()
    if not drive_id:
        raise ValueError("drive_id is required")
    return drive_id


def _update_body(arguments: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if "name" in arguments and arguments["name"] is not None:
        name = str(arguments["name"]).strip()
        if not name:
            raise ValueError("name cannot be empty")
        body["name"] = name
    if "color_rgb" in arguments and arguments["color_rgb"] is not None:
        body["colorRgb"] = str(arguments["color_rgb"]).strip()
    if "theme_id" in arguments and arguments["theme_id"] is not None:
        body["themeId"] = str(arguments["theme_id"]).strip()
    if "hidden" in arguments and arguments["hidden"] is not None:
        body["hidden"] = bool(arguments["hidden"])
    if "restrictions" in arguments and arguments["restrictions"] is not None:
        body["restrictions"] = dict(arguments["restrictions"])
    if not body:
        raise ValueError("Provide at least one of: name, color_rgb, theme_id, hidden, restrictions")
    return body


async def list_shared_drives_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    page_size = min(int(arguments.get("page_size", 100)), _MAX_PAGE_SIZE)
    page_token = str(arguments.get("page_token") or "").strip() or None
    query = str(arguments.get("q") or "").strip() or None

    def _call(service):
        kwargs: dict[str, Any] = {
            "pageSize": page_size,
            "fields": SHARED_DRIVE_LIST_FIELDS,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        if query:
            kwargs["q"] = query
        return service.drives().list(**kwargs).execute()

    response = await run_drive_call(user_id, _call)
    return build_shared_drives_list_response(response)


async def get_shared_drive_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    drive_id = _require_drive_id(arguments)

    def _call(service):
        return (
            service.drives()
            .get(driveId=drive_id, fields=SHARED_DRIVE_FIELDS)
            .execute()
        )

    drive = await run_drive_call(user_id, _call)
    return {"shared_drive": compact_shared_drive(drive)}


async def create_shared_drive_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    name = str(arguments.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")
    request_id = str(arguments.get("request_id") or "").strip() or str(uuid.uuid4())
    body: dict[str, Any] = {"name": name}
    if "color_rgb" in arguments and arguments["color_rgb"] is not None:
        body["colorRgb"] = str(arguments["color_rgb"]).strip()
    if "theme_id" in arguments and arguments["theme_id"] is not None:
        body["themeId"] = str(arguments["theme_id"]).strip()
    if "hidden" in arguments and arguments["hidden"] is not None:
        body["hidden"] = bool(arguments["hidden"])
    if "restrictions" in arguments and arguments["restrictions"] is not None:
        body["restrictions"] = dict(arguments["restrictions"])

    def _call(service):
        return (
            service.drives()
            .create(
                requestId=request_id,
                body=body,
                fields=SHARED_DRIVE_FIELDS,
            )
            .execute()
        )

    drive = await run_drive_call(user_id, _call)
    return {
        "created": True,
        "request_id": request_id,
        "shared_drive": compact_shared_drive(drive),
    }


async def update_shared_drive_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    drive_id = _require_drive_id(arguments)
    body = _update_body(arguments)

    def _call(service):
        return (
            service.drives()
            .update(
                driveId=drive_id,
                body=body,
                fields=SHARED_DRIVE_FIELDS,
            )
            .execute()
        )

    drive = await run_drive_call(user_id, _call)
    return {"updated": True, "shared_drive": compact_shared_drive(drive)}


async def delete_shared_drive_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(
        arguments,
        "confirm=true is required — this permanently deletes the shared drive.",
    )
    user_id = _require_user_id()
    drive_id = _require_drive_id(arguments)

    def _call(service):
        service.drives().delete(driveId=drive_id).execute()
        return {"deleted": True, "drive_id": drive_id}

    return await run_drive_call(user_id, _call)


async def hide_shared_drive_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    drive_id = _require_drive_id(arguments)

    def _call(service):
        return service.drives().hide(driveId=drive_id, fields=SHARED_DRIVE_FIELDS).execute()

    drive = await run_drive_call(user_id, _call)
    return {"hidden": True, "shared_drive": compact_shared_drive(drive)}


async def unhide_shared_drive_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    drive_id = _require_drive_id(arguments)

    def _call(service):
        return service.drives().unhide(driveId=drive_id, fields=SHARED_DRIVE_FIELDS).execute()

    drive = await run_drive_call(user_id, _call)
    return {"hidden": False, "shared_drive": compact_shared_drive(drive)}
