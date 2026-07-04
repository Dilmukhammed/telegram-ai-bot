from __future__ import annotations

from typing import Any

from tools.builtins.google.drive_client import run_drive_call
from tools.builtins.google.drive_serialize import (
    APP_FIELDS,
    APP_LIST_FIELDS,
    build_apps_list_response,
    compact_app,
)
from tools.context import get_run_context

_MAX_PAGE_SIZE = 100


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


def _require_app_id(arguments: dict[str, Any]) -> str:
    app_id = str(arguments.get("app_id", "")).strip()
    if not app_id:
        raise ValueError("app_id is required")
    return app_id


async def list_apps_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    page_size = min(int(arguments.get("page_size", 100)), _MAX_PAGE_SIZE)
    page_token = str(arguments.get("page_token") or "").strip() or None
    app_filter_extensions = str(arguments.get("app_filter_extensions") or "").strip() or None
    app_filter_mime_types = str(arguments.get("app_filter_mime_types") or "").strip() or None
    language_code = str(arguments.get("language_code") or "").strip() or None

    def _call(service):
        kwargs: dict[str, Any] = {
            "pageSize": page_size,
            "fields": APP_LIST_FIELDS,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        if app_filter_extensions:
            kwargs["appFilterExtensions"] = app_filter_extensions
        if app_filter_mime_types:
            kwargs["appFilterMimeTypes"] = app_filter_mime_types
        if language_code:
            kwargs["languageCode"] = language_code
        return service.apps().list(**kwargs).execute()

    response = await run_drive_call(user_id, _call)
    return build_apps_list_response(response)


async def get_app_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    app_id = _require_app_id(arguments)

    def _call(service):
        return service.apps().get(appId=app_id, fields=APP_FIELDS).execute()

    app = await run_drive_call(user_id, _call)
    return {"app": compact_app(app)}
