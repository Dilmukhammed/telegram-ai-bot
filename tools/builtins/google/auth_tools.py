from __future__ import annotations

from typing import Any

from tools.builtins.google.auth import (
    auth_status_payload,
    build_authorization_url,
    revoke_and_delete,
)
from tools.builtins.google.errors import GoogleOAuthNotConfiguredError
from tools.context import get_run_context
from tools.schema import ToolSpec


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


async def _auth_status_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    return auth_status_payload(_require_user_id())


async def _auth_connect_url_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    try:
        url = build_authorization_url(user_id)
    except GoogleOAuthNotConfiguredError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "url": url,
        "message": (
            "Open the URL, approve access, then paste the localhost callback URL "
            "from the browser address bar back into Telegram."
        ),
    }


async def _auth_disconnect_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    deleted = await revoke_and_delete(_require_user_id())
    return {"ok": True, "disconnected": deleted}


GOOGLE_AUTH_STATUS = ToolSpec(
    name="google.auth.status",
    description=(
        "Check whether the current Telegram user has connected Google (Calendar + Gmail + Drive + Sheets + Tasks). "
        "Returns configured, connected, email, scopes, gmail_ready, drive_ready, sheets_ready, and tasks_ready."
    ),
    parameters={"type": "object", "properties": {}},
    handler=_auth_status_handler,
    tags=("google", "auth"),
    cache_ttl_seconds=10,
    parallel_safe=True,
    examples=("is google connected", "google auth status"),
)

GOOGLE_AUTH_CONNECT_URL = ToolSpec(
    name="google.auth.connect_url",
    description=(
        "Return an OAuth URL so the user can connect Google Calendar, Gmail, Drive, Sheets, and Tasks. "
        "Alternative: user can run /connect_google in the bot."
    ),
    parameters={"type": "object", "properties": {}},
    handler=_auth_connect_url_handler,
    tags=("google", "auth"),
    parallel_safe=True,
    examples=("connect google calendar", "google oauth link"),
)

GOOGLE_AUTH_DISCONNECT = ToolSpec(
    name="google.auth.disconnect",
    description=(
        "Disconnect Google (Calendar + Gmail + Drive + Sheets + Tasks) for the current Telegram user. "
        "Alternative: /disconnect_google in the bot."
    ),
    parameters={"type": "object", "properties": {}},
    handler=_auth_disconnect_handler,
    tags=("google", "auth"),
    parallel_safe=True,
    examples=("disconnect google", "remove google access"),
)

GOOGLE_AUTH_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_AUTH_STATUS,
    GOOGLE_AUTH_CONNECT_URL,
    GOOGLE_AUTH_DISCONNECT,
)
