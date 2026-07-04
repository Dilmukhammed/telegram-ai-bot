from __future__ import annotations

import logging

from aiohttp import web

from bot.telegram_notify import send_telegram_message
from config import get_settings, google_oauth_configured, google_oauth_remote_ready
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


def create_oauth_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/oauth/google/start", start_oauth_handler)
    app.router.add_get("/oauth/google/callback", callback_oauth_handler)
    return app


async def start_oauth_server() -> web.AppRunner:
    settings = get_settings()
    app = create_oauth_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.google_oauth_host, settings.google_oauth_port)
    await site.start()
    logger.info(
        "Google OAuth server listening on http://%s:%s",
        settings.google_oauth_host,
        settings.google_oauth_port,
    )
    logger.info("Google OAuth callback URL: %s", settings.google_redirect_uri)
    if not google_oauth_remote_ready():
        logger.warning(
            "GOOGLE_PUBLIC_BASE_URL is not set to a public HTTPS URL. "
            "Remote users cannot complete OAuth from phone/other devices."
        )
    return runner
