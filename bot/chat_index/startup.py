from __future__ import annotations

import asyncio
import logging

from bot.chat_index.sync import rebuild_all_users_index
from config import get_settings

logger = logging.getLogger(__name__)


async def run_chat_index_startup() -> None:
    settings = get_settings()
    if not settings.chat_index_on_startup:
        return
    try:
        users, chunks = rebuild_all_users_index()
        logger.info("chat_index startup users=%s chunks=%s", users, chunks)
    except Exception:
        logger.exception("chat_index startup failed")


def enqueue_chat_index_startup() -> asyncio.Task[None] | None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return loop.create_task(run_chat_index_startup())
