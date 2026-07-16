from __future__ import annotations

from typing import Any

from config import browser_tools_enabled, browser_viewer_configured, steel_configured
from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser.cookies import cookies_summary, parse_cookies_payload
from tools.builtins.browser.errors import BrowserError, BrowserNoSessionError
from tools.builtins.browser.profile_store import get_browser_profile_store
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.session_manager import require_browser_session_manager
from tools.builtins.browser.steel_client import get_steel_client
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.context import get_run_context
from tools.run_files import require_run_file_store
from tools.schema import ToolSpec
from tools.workspace.store import read_workspace_bytes


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise BrowserError("Telegram user_id is missing in tool context")
    return user_id


async def _profile_status_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    store = get_browser_profile_store()
    profile = store.get_profile(user_id)
    refreshed = False
    remote_status = None
    refresh = bool(arguments.get("refresh", True))

    # Local DB can be stuck on uploading/ready_poll_timeout — re-check Steel.
    if (
        refresh
        and profile is not None
        and profile.status in {"uploading", "error"}
        and steel_configured()
    ):
        try:
            from tools.builtins.browser.profile_store import (
                PROFILE_STATUS_ERROR,
                PROFILE_STATUS_READY,
            )
            from tools.builtins.browser.session_manager import fetch_profile_status
            from datetime import datetime, timezone

            remote_status, err = await fetch_profile_status(profile.steel_profile_id)
            if remote_status == PROFILE_STATUS_READY:
                profile = store.upsert_profile(
                    telegram_user_id=user_id,
                    steel_profile_id=profile.steel_profile_id,
                    status=PROFILE_STATUS_READY,
                    last_snapshot_at=datetime.now(timezone.utc)
                    .replace(tzinfo=None)
                    .isoformat(),
                    snapshot_error=None,
                    touch_used=False,
                )
                refreshed = True
            elif remote_status == PROFILE_STATUS_ERROR:
                profile = store.upsert_profile(
                    telegram_user_id=user_id,
                    steel_profile_id=profile.steel_profile_id,
                    status=PROFILE_STATUS_ERROR,
                    snapshot_error=err,
                    touch_used=False,
                )
                refreshed = True
            else:
                remote_status = remote_status
        except Exception as exc:
            remote_status = f"refresh_failed:{type(exc).__name__}"

    payload = {
        "configured": steel_configured() and browser_tools_enabled(),
        "viewer_configured": browser_viewer_configured(),
        "has_profile": profile is not None,
        "profile_id": profile.steel_profile_id if profile else None,
        "status": profile.status if profile else "none",
        "last_used_at": profile.last_used_at if profile else None,
        "last_snapshot_at": profile.last_snapshot_at if profile else None,
        "snapshot_error": profile.snapshot_error if profile else None,
        "refreshed_from_steel": refreshed,
        "remote_status": remote_status,
    }
    return redact_browser_payload(payload)


async def _profile_disconnect_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    delete_remote = bool(arguments.get("delete_remote", True))
    store = get_browser_profile_store()
    profile = store.get_profile(user_id)
    if profile is None:
        return {"ok": True, "disconnected": False, "steel_profile_deleted": False}

    steel_deleted = False
    if delete_remote and steel_configured():
        try:
            await get_steel_client().delete_profile(profile.steel_profile_id)
            steel_deleted = True
        except Exception:
            steel_deleted = False

    store.delete_profile(user_id)
    return {
        "ok": True,
        "disconnected": True,
        "steel_profile_deleted": steel_deleted,
    }


BROWSER_PROFILE_STATUS = ToolSpec(
    name="browser.profile.status",
    description=(
        "Check whether this Telegram user has a saved Steel browser profile "
        "(cookies/logins). If local status is uploading/error, refreshes from Steel "
        "by default. Use before automation when login may be required."
    ),
    parameters={
        "type": "object",
        "properties": {
            "refresh": {
                "type": "boolean",
                "description": "Re-check Steel when local status is uploading/error (default true).",
                "default": True,
            },
        },
        "required": [],
    },
    handler=_profile_status_handler,
    tags=("browser", "web", "auth", "profile"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.profile.status"),
    checker_enabled=False,
    examples=("browser profile status", "is google logged in browser", "check browser login"),
)

async def _load_cookies_from_args(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    if arguments.get("cookies") is not None:
        return parse_cookies_payload(arguments.get("cookies"))
    if arguments.get("cookies_json"):
        return parse_cookies_payload(arguments.get("cookies_json"))

    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    if file_ref:
        stored = require_run_file_store().resolve(str(file_ref))
        raw = stored.path.read_text(encoding="utf-8")
        return parse_cookies_payload(raw)
    if path:
        user_id = _require_user_id()
        _p, data, _mime = read_workspace_bytes(user_id, str(path))
        return parse_cookies_payload(data.decode("utf-8"))

    raise BrowserError(
        "Provide cookies, cookies_json, file_ref, or workspace path to a JSON cookie export"
    )


async def _profile_import_cookies_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    cookies = await _load_cookies_from_args(arguments)
    manager = require_browser_session_manager()

    # Ensure a persisting session exists (reuse held/login/automation).
    if manager.lease is None or manager.lease.closed:
        opened = await manager.open(purpose="automation", persist=True)
        session_handle = opened["session_handle"]
        opened_now = True
    else:
        # Force persist so close snapshots cookies into the Steel profile.
        manager.lease.persist = True
        session_handle = manager.lease.handle
        opened_now = False

    try:
        _lease, session = await manager.get_playwright(session_handle)
    except BrowserNoSessionError:
        opened = await manager.open(purpose="automation", persist=True)
        _lease, session = await manager.get_playwright(opened["session_handle"])
        opened_now = True

    added = await pw.add_cookies(session, cookies)

    start_url = arguments.get("start_url") or "https://www.google.com/"
    nav = None
    if bool(arguments.get("navigate", True)):
        nav = await pw.navigate(session, str(start_url))

    summary = cookies_summary(cookies)
    payload = {
        "ok": True,
        "imported": added,
        "session_handle": manager.lease.handle if manager.lease else session_handle,
        "session_opened": opened_now,
        "persist": True,
        "domains": summary["domains"],
        "names_sample": summary["names_sample"],
        "navigation": nav,
        "next_step": (
            "Call browser.session_close after verifying login (e.g. screenshot of mail.google.com) "
            "so the Steel profile snapshots these cookies."
        ),
    }
    return redact_browser_payload(payload)


BROWSER_PROFILE_IMPORT_COOKIES = ToolSpec(
    name="browser.profile.import_cookies",
    description=(
        "Import browser cookies into the active Steel session (or open one with persist=true). "
        "Use this to seed Google/other logins from a real Chrome export when Steel HITL login "
        "is blocked ('browser may not be secure'). Accepts Playwright/EditThisCookie/Cookie-Editor "
        "JSON via cookies, cookies_json, workspace path, or file_ref. "
        "After import, verify with navigate/screenshot, then browser.session_close to persist profile."
    ),
    parameters={
        "type": "object",
        "properties": {
            "cookies": {
                "type": "array",
                "description": "JSON array of cookie objects (name, value, domain|url, ...).",
                "items": {"type": "object"},
            },
            "cookies_json": {
                "type": "string",
                "description": "Raw JSON string of cookie array / {cookies:[...]}.",
            },
            "path": {
                "type": "string",
                "description": "Workspace path to cookies JSON (e.g. uploads/google_cookies.json).",
            },
            "file_ref": {
                "type": "string",
                "description": "Run file_ref to cookies JSON.",
            },
            "start_url": {
                "type": "string",
                "description": "URL to open after import (default https://www.google.com/).",
                "default": "https://www.google.com/",
            },
            "navigate": {
                "type": "boolean",
                "description": "Navigate to start_url after importing (default true).",
                "default": True,
            },
        },
        "required": [],
    },
    handler=_profile_import_cookies_handler,
    tags=("browser", "web", "auth", "profile", "cookies"),
    cache_ttl_seconds=None,
    rate_limit=(10, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.session_open"),
    checker_enabled=False,
    examples=(
        "import google cookies into browser",
        "seed browser profile from chrome cookies",
        "load cookies json for google login",
    ),
)


BROWSER_PROFILE_DISCONNECT = ToolSpec(
    name="browser.profile.disconnect",
    description=(
        "Delete the saved Steel browser profile for this user (local DB and optionally remote)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "delete_remote": {
                "type": "boolean",
                "description": "Also delete the profile on Steel (default true).",
                "default": True,
            },
        },
        "required": [],
    },
    handler=_profile_disconnect_handler,
    tags=("browser", "web", "auth", "profile"),
    cache_ttl_seconds=None,
    rate_limit=(10, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.profile.disconnect"),
    checker_enabled=False,
    examples=("disconnect browser profile", "forget browser login"),
)

BROWSER_PROFILE_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_PROFILE_STATUS,
    BROWSER_PROFILE_IMPORT_COOKIES,
    BROWSER_PROFILE_DISCONNECT,
)
