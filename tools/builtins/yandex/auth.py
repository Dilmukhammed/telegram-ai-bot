from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from yandex_music import ClientAsync, OAuthToken

from tools.builtins.yandex.music_client import get_anonymous_client
from tools.builtins.yandex.token_store import StoredYandexToken, get_token_store

logger = logging.getLogger(__name__)


async def _persist_account(client: ClientAsync, telegram_user_id: int, oauth: OAuthToken) -> StoredYandexToken:
    login = None
    uid = None
    try:
        status = await client.account_status()
        if status and status.account:
            login = status.account.login
            uid = status.account.uid
    except Exception:
        logger.warning("Failed to fetch Yandex account status for user %s", telegram_user_id, exc_info=True)

    expiry = None
    if oauth.expires_in:
        expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=int(oauth.expires_in))

    stored = StoredYandexToken(
        telegram_user_id=telegram_user_id,
        access_token=oauth.access_token,
        refresh_token=oauth.refresh_token,
        token_expiry=expiry,
        login=login,
        uid=uid,
    )
    get_token_store().save(
        telegram_user_id=telegram_user_id,
        access_token=stored.access_token,
        refresh_token=stored.refresh_token,
        token_expiry=stored.token_expiry,
        login=stored.login,
        uid=stored.uid,
    )
    return stored


async def save_oauth_token(telegram_user_id: int, oauth: OAuthToken, client: ClientAsync) -> StoredYandexToken:
    return await _persist_account(client, telegram_user_id, oauth)


async def start_device_connect(telegram_user_id: int) -> dict[str, Any]:
    client = await get_anonymous_client()
    code = await client.request_device_code(device_name=f"HermesBot-{telegram_user_id}")
    get_token_store().save_device_pending(
        telegram_user_id=telegram_user_id,
        device_code=code.device_code,
        user_code=code.user_code,
        verification_url=code.verification_url,
        expires_in=int(code.expires_in or 600),
    )
    return {
        "ok": True,
        "verification_url": code.verification_url,
        "user_code": code.user_code,
        "expires_in": code.expires_in,
        "interval": code.interval,
        "message": (
            f"Open {code.verification_url} and enter code {code.user_code}. "
            "The bot will detect confirmation automatically."
        ),
    }


async def poll_device_connect_once(telegram_user_id: int) -> StoredYandexToken | None:
    pending = get_token_store().get_device_pending(telegram_user_id)
    if pending is None:
        return None

    client = await get_anonymous_client()
    token = await client.poll_device_token(pending["device_code"])
    if token is None:
        return None

    get_token_store().clear_device_pending(telegram_user_id)
    client.token = token.access_token
    return await save_oauth_token(telegram_user_id, token, client)


async def revoke_and_delete(telegram_user_id: int) -> bool:
    return get_token_store().delete(telegram_user_id)


def auth_status_payload(telegram_user_id: int) -> dict[str, Any]:
    stored = get_token_store().get(telegram_user_id)
    pending = get_token_store().get_device_pending(telegram_user_id)
    return {
        "configured": True,
        "connected": stored is not None,
        "music_ready": stored is not None,
        "login": stored.login if stored else None,
        "uid": stored.uid if stored else None,
        "token_expiry": stored.token_expiry.isoformat() if stored and stored.token_expiry else None,
        "device_auth_pending": pending is not None,
        "pending_user_code": pending.get("user_code") if pending else None,
    }
