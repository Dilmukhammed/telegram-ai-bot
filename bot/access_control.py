from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.access_service import get_access_service

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class AccessControlMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Handler,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)

        user_id = event.from_user.id
        access = get_access_service()
        if access.is_allowed(user_id):
            return await handler(event, data)

        bot = data.get("bot")
        if bot is not None:
            await access.handle_blocked_message(event, bot)
        return None
