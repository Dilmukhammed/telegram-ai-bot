from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING, Callable

from aiogram.enums import ParseMode

from bot.access_service import get_access_service, parse_email
from config import google_oauth_configured, google_oauth_manual_mode
from tools.builtins.google.auth import (
    build_authorization_url,
    missing_oauth_scopes,
    revoke_and_delete,
)
from tools.builtins.google.token_store import get_token_store

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

logger = logging.getLogger(__name__)


async def _build_google_connect_text(user_id: int, *, oauth_start_url: Callable[[int], str]) -> str:
    stored = get_token_store().get(user_id)
    missing = missing_oauth_scopes(stored)
    prefix = ""
    if missing:
        await revoke_and_delete(user_id)
        short = ", ".join(scope.rsplit("/", 1)[-1] for scope in missing)
        prefix = (
            f"Старый токен без: {short}. Сбросил подключение — "
            "Google покажет полный consent заново.\n\n"
        )
    if google_oauth_manual_mode():
        url = build_authorization_url(user_id)
    else:
        url = oauth_start_url(user_id)
    return prefix + connect_google_instructions(url)


async def send_google_connect_url_to_user(
    bot: Bot,
    user_id: int,
    *,
    oauth_start_url: Callable[[int], str],
) -> None:
    text = await _build_google_connect_text(user_id, oauth_start_url=oauth_start_url)
    await bot.send_message(user_id, text)


def connect_google_instructions(url: str) -> str:
    if google_oauth_manual_mode():
        return (
            "Подключение Google Calendar, Gmail, Drive, Sheets и Tasks:\n\n"
            f"1. Открой ссылку (телефон или комп):\n{url}\n\n"
            "2. Войди в Google и разреши доступ к календарю, почте и Drive.\n\n"
            "3. Браузер перейдёт на localhost и покажет ошибку — это нормально.\n\n"
            "4. Скопируй **весь URL** из адресной строки и пришли сюда "
            "(или `/google_callback <url>`)."
        )
    return (
        "Подключение Google Calendar, Gmail, Drive, Sheets и Tasks:\n"
        f"Открой ссылку с любого устройства:\n{url}\n\n"
        "После логина Google пришлю подтверждение сюда в Telegram."
    )


async def deliver_google_connect_url(
    message: Message,
    *,
    oauth_start_url: Callable[[int], str],
) -> None:
    user_id = message.from_user.id
    text = await _build_google_connect_text(user_id, oauth_start_url=oauth_start_url)
    await message.answer(text)


async def start_google_connect(
    message: Message,
    *,
    oauth_start_url: Callable[[int], str],
) -> None:
    if not google_oauth_configured():
        await message.answer("Google OAuth не настроен. Добавь GOOGLE_CLIENT_ID и GOOGLE_CLIENT_SECRET в .env")
        return

    access = get_access_service()
    user = message.from_user
    if not access.is_allowed(user.id):
        await message.answer("Сначала нужен доступ к боту. Напиши любое сообщение — админ одобрит.")
        return

    # Admins skip Test-users email gate; clear any stale pending flag.
    if access.is_admin(user.id):
        if access.is_google_email_pending(user.id):
            access.clear_google_email_collection(user.id)
        await deliver_google_connect_url(message, oauth_start_url=oauth_start_url)
        return

    if access.needs_google_email(user.id):
        access.begin_google_email_collection(user.id)
        await message.answer(
            "Перед подключением Google пришли **свою Google-почту** "
            "(ту, через которую будешь входить в Google).\n\n"
            "Администратор добавит её в Test users Google Cloud Console, "
            "после этого пришлю OAuth-ссылку."
        )
        return

    if not access.is_google_test_user_verified(user.id):
        email = access.get_google_email(user.id) or "—"
        await message.answer(
            f"Google-почта <code>{html.escape(email)}</code> ещё не подтверждена администратором.\n"
            "Когда добавят в Test users — пришлю OAuth-ссылку автоматически.",
            parse_mode=ParseMode.HTML,
        )
        return

    await deliver_google_connect_url(message, oauth_start_url=oauth_start_url)


async def try_handle_google_email(
    message: Message,
    bot: Bot,
    *,
    oauth_start_url: Callable[[int], str],
) -> bool:
    from tools.builtins.google.auth import looks_like_manual_oauth_callback

    user = message.from_user
    if user is None:
        return False

    access = get_access_service()
    # Admin / OAuth callback must not be trapped by email collection.
    if access.is_admin(user.id):
        if access.is_google_email_pending(user.id):
            access.clear_google_email_collection(user.id)
        return False

    if not access.is_google_email_pending(user.id):
        return False

    text = message.text or ""
    if looks_like_manual_oauth_callback(text):
        return False

    email = parse_email(text)
    if not email:
        await message.answer("Пришли Google email в формате name@gmail.com")
        return True

    access.save_google_email(user.id, email)
    await access.notify_admins_google_email(bot, user, email)
    await message.answer(
        f"Принял Google-почту: <code>{html.escape(email)}</code>\n\n"
        "Администратор добавит её в Test users Google Cloud Console.\n"
        "Когда подтвердит — пришлю OAuth-ссылку автоматически.",
        parse_mode=ParseMode.HTML,
    )
    return True
