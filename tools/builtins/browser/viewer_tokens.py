from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from config import browser_viewer_configured, get_settings
from tools.builtins.browser.errors import (
    BrowserViewerNotConfiguredError,
    BrowserViewerTokenError,
)
from tools.builtins.browser.profile_store import (
    StoredViewerToken,
    get_browser_profile_store,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def mint_viewer_token(
    *,
    telegram_user_id: int,
    steel_session_id: str,
    debug_url: str,
    ttl_seconds: int | None = None,
) -> tuple[str, str, str]:
    """Return (token, gated_public_url, expires_at_iso). Never expose debug_url to callers of tools."""
    if not browser_viewer_configured():
        raise BrowserViewerNotConfiguredError(
            "BROWSER_VIEWER_PUBLIC_BASE (or GOOGLE_PUBLIC_BASE_URL) is required for login"
        )

    settings = get_settings()
    ttl = ttl_seconds or settings.browser_viewer_token_ttl_seconds
    ttl = max(30, min(ttl, settings.browser_session_max_seconds))
    token = secrets.token_urlsafe(32)
    expires_at = (_utc_now() + timedelta(seconds=ttl)).isoformat()
    store = get_browser_profile_store()
    store.mint_viewer_token(
        token=token,
        telegram_user_id=telegram_user_id,
        steel_session_id=steel_session_id,
        debug_url=debug_url,
        expires_at=expires_at,
    )
    base = settings.browser_viewer_public_base.rstrip("/")  # type: ignore[union-attr]
    public_url = f"{base}/browser/viewer/{token}"
    return token, public_url, expires_at


def resolve_viewer_redirect(token: str) -> str:
    """Validate token and return Steel debug URL for HTTP 302. Marks token consumed."""
    store = get_browser_profile_store()
    stored = store.get_viewer_token(token)
    if stored is None:
        raise BrowserViewerTokenError("Viewer token not found")
    if stored.revoked_at:
        raise BrowserViewerTokenError("Viewer token revoked")
    if stored.consumed_at:
        raise BrowserViewerTokenError("Viewer token already used")
    if _parse_iso(stored.expires_at) <= _utc_now():
        raise BrowserViewerTokenError("Viewer token expired")

    consumed = store.consume_viewer_token(token)
    if consumed is None or not consumed.consumed_at:
        raise BrowserViewerTokenError("Viewer token already used")

    debug_url = stored.debug_url
    separator = "&" if "?" in debug_url else "?"
    if "interactive=" not in debug_url:
        debug_url = f"{debug_url}{separator}interactive=true"
    return debug_url


def peek_viewer_token(token: str) -> StoredViewerToken | None:
    return get_browser_profile_store().get_viewer_token(token)
