from __future__ import annotations

import logging

from aiohttp import web

from bot.telegram_notify import send_telegram_message
from config import (
    browser_tools_enabled,
    get_settings,
    google_oauth_configured,
    google_oauth_remote_ready,
)
from tools.builtins.browser.errors import BrowserViewerTokenError
from tools.builtins.browser.viewer_tokens import resolve_viewer_redirect
from tools.builtins.google.auth import build_authorization_url, complete_oauth

logger = logging.getLogger(__name__)


async def start_oauth_handler(request: web.Request) -> web.Response:
    if not google_oauth_configured():
        raise web.HTTPServiceUnavailable(text="Google OAuth is not configured")

    user_id_raw = request.query.get("user_id") or request.query.get("state")
    if not user_id_raw or not user_id_raw.isdigit():
        raise web.HTTPBadRequest(text="Missing user_id query parameter")

    telegram_user_id = int(user_id_raw)
    url = build_authorization_url(telegram_user_id)
    raise web.HTTPFound(url)


async def callback_oauth_handler(request: web.Request) -> web.Response:
    if not google_oauth_configured():
        raise web.HTTPServiceUnavailable(text="Google OAuth is not configured")

    error = request.query.get("error")
    if error:
        return web.Response(
            text=f"Google OAuth failed: {error}",
            content_type="text/plain",
            status=400,
        )

    code = request.query.get("code")
    state = request.query.get("state")
    if not code or not state or not state.isdigit():
        raise web.HTTPBadRequest(text="Missing OAuth code or state")

    telegram_user_id = int(state)
    stored = await complete_oauth(telegram_user_id, code)
    email = stored.email or "unknown"
    await send_telegram_message(
        telegram_user_id,
        f"Google подключён (Calendar, Gmail, Drive): {email}\nМожешь возвращаться в Telegram.",
    )
    return web.Response(
        text=(
            "Google connected successfully (Calendar, Gmail, Drive).\n"
            f"Telegram user: {telegram_user_id}\n"
            f"Google account: {email}\n\n"
            "You can close this tab and return to Telegram."
        ),
        content_type="text/plain",
    )


async def browser_viewer_handler(request: web.Request) -> web.Response:
    token = request.match_info.get("token") or ""
    if not token:
        raise web.HTTPBadRequest(text="Missing viewer token")
    try:
        debug_url = resolve_viewer_redirect(token)
    except BrowserViewerTokenError as exc:
        message = str(exc) or "Invalid viewer token"
        if "already used" in message.lower():
            raise web.HTTPGone(text=message) from exc
        if "expired" in message.lower() or "revoked" in message.lower():
            raise web.HTTPGone(text=message) from exc
        if "not found" in message.lower():
            raise web.HTTPNotFound(text=message) from exc
        raise web.HTTPForbidden(text=message) from exc
    # Never log the raw debug URL (unauthenticated session control).
    logger.info("Browser viewer token accepted (redirecting)")
    raise web.HTTPFound(debug_url)


def create_oauth_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/oauth/google/start", start_oauth_handler)
    app.router.add_get("/oauth/google/callback", callback_oauth_handler)
    app.router.add_get("/browser/viewer/{token}", browser_viewer_handler)
    return app


async def start_oauth_server() -> web.AppRunner:
    settings = get_settings()
    app = create_oauth_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.google_oauth_host, settings.google_oauth_port)
    await site.start()
    logger.info(
        "HTTP server listening on http://%s:%s (OAuth + browser viewer)",
        settings.google_oauth_host,
        settings.google_oauth_port,
    )
    if google_oauth_configured():
        logger.info("Google OAuth callback URL: %s", settings.google_redirect_uri)
        if not google_oauth_remote_ready():
            logger.warning(
                "GOOGLE_PUBLIC_BASE_URL is not set to a public HTTPS URL. "
                "Remote users cannot complete OAuth from phone/other devices."
            )
    if browser_tools_enabled():
        base = settings.browser_viewer_public_base
        if base:
            logger.info("Browser viewer base: %s/browser/viewer/<token>", base.rstrip("/"))
        else:
            logger.warning(
                "BROWSER_VIEWER_PUBLIC_BASE is not set; browser.session_open purpose=login will fail"
            )
    return runner
