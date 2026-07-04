from __future__ import annotations

from typing import Any

from tools.builtins.google.drive_client import drive_support_kwargs, run_drive_call
from tools.builtins.google.drive_serialize import (
    PERMISSION_FIELDS,
    PERMISSION_LIST_FIELDS,
    build_permissions_list_response,
    compact_permission,
)
from tools.context import get_run_context

_MAX_PAGE_SIZE = 100
_SHARE_ROLES = frozenset({"reader", "writer", "commenter"})
_UPDATE_ROLES = frozenset({"reader", "writer", "commenter", "owner", "organizer", "fileOrganizer"})
_PERMISSION_TYPES = frozenset({"user", "group", "domain", "anyone"})


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


def _require_permission_id(arguments: dict[str, Any]) -> str:
    permission_id = str(arguments.get("permission_id", "")).strip()
    if not permission_id:
        raise ValueError("permission_id is required")
    return permission_id


def _build_share_body(arguments: dict[str, Any]) -> dict[str, Any]:
    perm_type = str(arguments.get("type", "user")).strip().lower()
    role = str(arguments.get("role", "reader")).strip().lower()
    if perm_type not in _PERMISSION_TYPES:
        raise ValueError(f"type must be one of: {', '.join(sorted(_PERMISSION_TYPES))}")
    if role not in _SHARE_ROLES:
        raise ValueError("role must be reader, writer, or commenter")

    body: dict[str, Any] = {"type": perm_type, "role": role}
    email = str(arguments.get("email") or "").strip()
    domain = str(arguments.get("domain") or "").strip()

    if perm_type in {"user", "group"}:
        if not email:
            raise ValueError("email is required when type is user or group")
        body["emailAddress"] = email
    elif perm_type == "domain":
        if not domain:
            raise ValueError("domain is required when type is domain")
        body["domain"] = domain
    return body


async def list_permissions_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    page_size = min(int(arguments.get("page_size", 100)), _MAX_PAGE_SIZE)
    page_token = str(arguments.get("page_token") or "").strip() or None

    def _call(service):
        kwargs: dict[str, Any] = {
            "fileId": file_id,
            "fields": PERMISSION_LIST_FIELDS,
            "pageSize": page_size,
            **drive_support_kwargs(),
        }
        if page_token:
            kwargs["pageToken"] = page_token
        return service.permissions().list(**kwargs).execute()

    response = await run_drive_call(user_id, _call)
    return {"file_id": file_id, **build_permissions_list_response(response)}


async def get_permission_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    permission_id = _require_permission_id(arguments)

    def _call(service):
        return (
            service.permissions()
            .get(
                fileId=file_id,
                permissionId=permission_id,
                fields=PERMISSION_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    permission = await run_drive_call(user_id, _call)
    return {"file_id": file_id, "permission": compact_permission(permission)}


async def share_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    body = _build_share_body(arguments)
    send_notification = bool(arguments.get("send_notification", True))

    def _call(service):
        return (
            service.permissions()
            .create(
                fileId=file_id,
                body=body,
                sendNotificationEmail=send_notification,
                fields=PERMISSION_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    permission = await run_drive_call(user_id, _call)
    return {"shared": True, "file_id": file_id, "permission": compact_permission(permission)}


async def update_permission_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    permission_id = _require_permission_id(arguments)
    role = str(arguments.get("role", "")).strip().lower()
    if role not in _UPDATE_ROLES:
        raise ValueError(
            "role is required — reader, writer, commenter, owner, organizer, or fileOrganizer"
        )

    def _call(service):
        return (
            service.permissions()
            .update(
                fileId=file_id,
                permissionId=permission_id,
                body={"role": role},
                fields=PERMISSION_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    permission = await run_drive_call(user_id, _call)
    return {
        "updated": True,
        "file_id": file_id,
        "permission": compact_permission(permission),
    }


async def remove_permission_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    permission_id = _require_permission_id(arguments)

    def _call(service):
        service.permissions().delete(
            fileId=file_id,
            permissionId=permission_id,
            **drive_support_kwargs(),
        ).execute()
        return {
            "removed": True,
            "file_id": file_id,
            "permission_id": permission_id,
        }

    return await run_drive_call(user_id, _call)
