from __future__ import annotations

import asyncio
import logging

from bot.telegram_notify import send_telegram_message
from tools.builtins.yandex.auth import auth_status_payload, poll_device_connect_once, start_device_connect

logger = logging.getLogger(__name__)

_poll_tasks: dict[int, asyncio.Task[None]] = {}


async def _poll_until_connected(telegram_user_id: int) -> None:
    try:
        for _ in range(120):
            stored = await poll_device_connect_once(telegram_user_id)
            if stored is not None:
                login = stored.login or "Yandex Music"
                await send_telegram_message(
                    telegram_user_id,
                    f"Яндекс.Музыка подключена: {login}\nМожно искать треки, плейлисты и скачивать аудио.",
                )
                return
            await asyncio.sleep(5)
        await send_telegram_message(
            telegram_user_id,
            "Время ожидания подключения Яндекс.Музыки истекло. Запусти /connect_yandex снова.",
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Yandex device auth poll failed for user %s", telegram_user_id)
        await send_telegram_message(
            telegram_user_id,
            "Не удалось завершить подключение Яндекс.Музыки. Попробуй /connect_yandex ещё раз.",
        )
    finally:
        _poll_tasks.pop(telegram_user_id, None)


def start_yandex_connect_poll(telegram_user_id: int) -> None:
    existing = _poll_tasks.get(telegram_user_id)
    if existing is not None and not existing.done():
        existing.cancel()
    _poll_tasks[telegram_user_id] = asyncio.create_task(
        _poll_until_connected(telegram_user_id),
        name=f"yandex-connect:{telegram_user_id}",
    )


async def begin_yandex_connect(telegram_user_id: int) -> str:
    payload = await start_device_connect(telegram_user_id)
    start_yandex_connect_poll(telegram_user_id)
    return (
        "Подключение Яндекс.Музыки (Device OAuth):\n\n"
        f"1. Открой: {payload['verification_url']}\n"
        f"2. Введи код: **{payload['user_code']}**\n\n"
        "После подтверждения бот напишет, когда аккаунт подключён."
    )


def yandex_status_text(telegram_user_id: int) -> str:
    status = auth_status_payload(telegram_user_id)
    if status.get("connected"):
        login = status.get("login") or "unknown"
        return f"Яндекс.Музыка подключена: {login}\nuid={status.get('uid')}"
    if status.get("device_auth_pending"):
        code = status.get("pending_user_code") or "?"
        return f"Ожидаю подтверждение OAuth. Код: {code}\n/connect_yandex — начать заново."
    return "Яндекс.Музыка не подключена. /connect_yandex"
