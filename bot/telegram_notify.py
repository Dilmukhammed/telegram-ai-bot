from __future__ import annotations

import logging

from aiogram import Bot

from config import get_settings

logger = logging.getLogger(__name__)


async def send_telegram_message(user_id: int, text: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return

    bot = Bot(token=settings.telegram_bot_token)
    try:
        await bot.send_message(user_id, text)
    except Exception:
        logger.exception("Failed to send Telegram message to user %s", user_id)
    finally:
        await bot.session.close()
