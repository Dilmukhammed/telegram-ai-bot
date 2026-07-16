from __future__ import annotations

from typing import Any

from bot.browser_login_notify import send_browser_login_link
from tools.builtins.browser.errors import BrowserError, BrowserViewerNotConfiguredError
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.session_manager import require_browser_session_manager
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.builtins.browser.viewer_tokens import mint_viewer_token
from tools.context import get_run_context
from tools.schema import ToolSpec


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise BrowserError("Telegram user_id is missing in tool context")
    return user_id


async def _session_open_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    purpose = str(arguments.get("purpose") or "automation").lower().strip()
    if purpose in {"hitl", "auth", "signin", "sign_in"}:
        purpose = "login"
    if purpose not in {"automation", "login"}:
        purpose = "automation"

    persist = arguments.get("persist")
    persist_bool = None if persist is None else bool(persist)
    start_url = arguments.get("start_url")

    manager = require_browser_session_manager()
    opened = await manager.open(
        purpose=purpose,
        persist=persist_bool,
        start_url=start_url,
    )

    login_info = None
    if purpose == "login" and not opened.get("reused"):
        debug_url = opened.pop("_debug_url_internal", "") or ""
        if not debug_url:
            await manager.close(reason="login_missing_debug_url")
            raise BrowserViewerNotConfiguredError(
                "Steel session did not return a debug/viewer URL"
            )
        try:
            _token, public_url, expires_at = mint_viewer_token(
                telegram_user_id=user_id,
                steel_session_id=manager.lease.steel_session_id if manager.lease else "",
                debug_url=debug_url,
            )
        except BrowserViewerNotConfiguredError:
            await manager.close(reason="viewer_not_configured")
            raise

        await send_browser_login_link(
            user_id,
            public_url=public_url,
            expires_at=expires_at,
        )
        login_info = {
            "viewer_dispatched": True,
            "expires_at": expires_at,
        }
    else:
        opened.pop("_debug_url_internal", None)

    result = {
        "session_handle": opened["session_handle"],
        "reused": opened["reused"],
        "purpose": opened["purpose"],
        "profile_id": opened.get("profile_id"),
        "persist": opened.get("persist"),
        "expires_at": opened.get("expires_at"),
        "login": login_info,
    }
    return redact_browser_payload(result)


async def _session_close_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    manager = require_browser_session_manager()
    handle = arguments.get("session_handle")
    closed = await manager.close(
        session_handle=str(handle) if handle else None,
        reason="explicit",
    )
    return redact_browser_payload(closed)


BROWSER_SESSION_OPEN = ToolSpec(
    name="browser.session_open",
    description=(
        "Open a Steel cloud browser session for this user. "
        "purpose=login sends a one-time interactive viewer link in Telegram so the user "
        "can sign into websites (e.g. Google); always close afterward to persist the profile. "
        "purpose=automation reuses the saved profile for browsing. "
        "Not for plain web search — use exa.web_search instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "purpose": {
                "type": "string",
                "enum": ["automation", "login"],
                "description": "automation (default) or login (HITL Google/web sign-in).",
                "default": "automation",
            },
            "persist": {
                "type": "boolean",
                "description": "Persist cookies/profile on close (forced true for login).",
            },
            "start_url": {
                "type": "string",
                "description": "Optional URL to open immediately after connect.",
            },
        },
        "required": [],
    },
    handler=_session_open_handler,
    tags=("browser", "web", "automation", "login", "session"),
    cache_ttl_seconds=None,
    rate_limit=(6, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.session_open"),
    checker_enabled=False,
    examples=(
        "open browser login google",
        "start browser session",
        "login website in browser",
        "open interactive browser",
    ),
)

BROWSER_SESSION_CLOSE = ToolSpec(
    name="browser.session_close",
    description=(
        "Release the Steel browser session. Required to stop billing and to snapshot "
        "the profile when persist was enabled (e.g. after login)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "session_handle": {
                "type": "string",
                "description": "Optional handle from session_open; defaults to the active run session.",
            },
        },
        "required": [],
    },
    handler=_session_close_handler,
    tags=("browser", "web", "automation", "session"),
    cache_ttl_seconds=None,
    rate_limit=(12, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.session_close"),
    checker_enabled=False,
    examples=("close browser session", "save browser profile", "release browser"),
)

BROWSER_SESSION_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_SESSION_OPEN,
    BROWSER_SESSION_CLOSE,
)
