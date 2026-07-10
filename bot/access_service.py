from __future__ import annotations

import html
import logging
import re
from typing import TYPE_CHECKING

from aiogram.enums import ParseMode
from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, User

from bot.access_store import AccessStore, get_access_store
from config import get_settings
from tools.phase4_config import admin_user_ids, allowed_user_ids

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
_CALLBACK_APPROVE_PREFIX = "acc:ok:"
_CALLBACK_DENY_PREFIX = "acc:no:"
_CALLBACK_GOOGLE_VERIFY_PREFIX = "gacc:verify:"


def access_approval_enabled() -> bool:
    return get_settings().access_approval_enabled


def parse_email(text: str) -> str | None:
    candidate = text.strip().lower()
    if not candidate or "@" not in candidate:
        return None
    if candidate.startswith("mailto:"):
        candidate = candidate.removeprefix("mailto:")
    if _EMAIL_RE.match(candidate):
        return candidate
    return None


def format_user_brief(user: User) -> str:
    parts: list[str] = []
    if user.username:
        parts.append(f"@{user.username}")
    name = " ".join(part for part in (user.first_name, user.last_name) if part)
    if name:
        parts.append(name)
    if not parts:
        parts.append("без имени")
    return " / ".join(parts)


def google_test_users_console_url() -> str:
    settings = get_settings()
    override = settings.google_cloud_test_users_url.strip()
    if override:
        return override
    project_id = settings.google_cloud_project_id.strip()
    if project_id:
        return (
            "https://console.cloud.google.com/apis/credentials/consent"
            f"?project={project_id}"
        )
    return "https://console.cloud.google.com/apis/credentials/consent"


def build_google_email_admin_markup(user_id: int, email: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Скопировать email",
                    copy_text=CopyTextButton(text=email),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔗 Google Console — Test users",
                    url=google_test_users_console_url(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✅ Добавил — проверить",
                    callback_data=f"{_CALLBACK_GOOGLE_VERIFY_PREFIX}{user_id}",
                ),
            ],
        ]
    )


class AccessService:
    def __init__(self, store: AccessStore | None = None) -> None:
        self._store = store or get_access_store()

    def is_admin(self, user_id: int) -> bool:
        return user_id in admin_user_ids()

    def is_allowed(self, user_id: int) -> bool:
        if self.is_admin(user_id):
            return True

        static_allowed = allowed_user_ids()
        if user_id in static_allowed:
            return True

        if not access_approval_enabled():
            if not static_allowed:
                return True
            return user_id in static_allowed

        record = self._store.get(user_id)
        return record is not None and record.status == "approved"

    def needs_google_email(self, user_id: int) -> bool:
        record = self._store.get(user_id)
        if record is None:
            return True
        return not record.google_email

    def is_google_email_pending(self, user_id: int) -> bool:
        record = self._store.get(user_id)
        return bool(record and record.google_email_pending)

    def is_google_test_user_verified(self, user_id: int) -> bool:
        record = self._store.get(user_id)
        return bool(record and record.google_test_user_verified)

    def begin_google_email_collection(self, user_id: int) -> None:
        self._store.set_google_email_pending(user_id, True)

    def get_google_email(self, user_id: int) -> str | None:
        record = self._store.get(user_id)
        if record is None:
            return None
        return record.google_email

    def save_google_email(self, user_id: int, email: str):
        return self._store.save_google_email(user_id, email)

    def build_access_request_markup(self, user_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Добавить",
                        callback_data=f"{_CALLBACK_APPROVE_PREFIX}{user_id}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Отказать",
                        callback_data=f"{_CALLBACK_DENY_PREFIX}{user_id}",
                    ),
                ]
            ]
        )

    @staticmethod
    def parse_google_access_callback(data: str) -> int | None:
        if not data.startswith(_CALLBACK_GOOGLE_VERIFY_PREFIX):
            return None
        suffix = data.removeprefix(_CALLBACK_GOOGLE_VERIFY_PREFIX)
        if suffix.isdigit():
            return int(suffix)
        return None

    @staticmethod
    def parse_access_callback(data: str) -> tuple[str, int] | None:
        if data.startswith(_CALLBACK_APPROVE_PREFIX):
            suffix = data.removeprefix(_CALLBACK_APPROVE_PREFIX)
            if suffix.isdigit():
                return ("approve", int(suffix))
        if data.startswith(_CALLBACK_DENY_PREFIX):
            suffix = data.removeprefix(_CALLBACK_DENY_PREFIX)
            if suffix.isdigit():
                return ("deny", int(suffix))
        return None

    async def handle_blocked_message(self, message: Message, bot: Bot) -> None:
        user = message.from_user
        if user is None:
            return

        record = self._store.get(user.id)
        if record and record.status == "denied":
            await message.answer("Доступ к боту отклонён администратором.")
            return

        if record and record.status == "pending":
            await message.answer("Запрос уже отправлен администратору. Ожидай одобрения.")
            return

        if record and record.status == "approved":
            return

        self._store.upsert_pending(
            user.id,
            username=user.username,
            display_name=" ".join(part for part in (user.first_name, user.last_name) if part) or None,
        )
        await self._notify_admins_access_request(bot, user)
        await message.answer(
            "Запрос на доступ отправлен администратору.\n"
            "Когда тебя одобрят — сможешь пользоваться ботом."
        )

    async def _notify_admins_access_request(self, bot: Bot, user: User) -> None:
        admins = admin_user_ids()
        if not admins:
            logger.warning("access_request user_id=%s but ADMIN_USER_IDS is empty", user.id)
            return

        text = (
            "Новый пользователь запрашивает доступ к боту:\n\n"
            f"Telegram ID: <code>{user.id}</code>\n"
            f"Профиль: {html.escape(format_user_brief(user))}"
        )
        markup = self.build_access_request_markup(user.id)
        for admin_id in admins:
            try:
                await bot.send_message(
                    admin_id,
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
            except Exception:
                logger.exception("failed to notify admin_id=%s about access request", admin_id)

    async def notify_admins_google_email(self, bot: Bot, user: User, email: str) -> None:
        admins = admin_user_ids()
        if not admins:
            logger.warning("google_email user_id=%s but ADMIN_USER_IDS is empty", user.id)
            return

        text = (
            "Пользователь хочет подключить Google.\n"
            "Добавь email в <b>Test users</b> Google Cloud Console:\n\n"
            f"Email: <code>{html.escape(email)}</code>\n"
            f"Telegram ID: <code>{user.id}</code>\n"
            f"Профиль: {html.escape(format_user_brief(user))}\n\n"
            "Нажми «Скопировать email» или тапни по адресу в сообщении."
        )
        markup = build_google_email_admin_markup(user.id, email)
        for admin_id in admins:
            try:
                await bot.send_message(
                    admin_id,
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
            except Exception:
                logger.exception("failed to notify admin_id=%s about google email", admin_id)

    async def approve_user(self, bot: Bot, user_id: int, *, admin_id: int) -> str:
        record = self._store.set_status(user_id, "approved", approved_by=admin_id)
        if record is None:
            self._store.upsert_pending(user_id, username=None, display_name=None)
            record = self._store.set_status(user_id, "approved", approved_by=admin_id)
        if record is None:
            return "Не удалось одобрить пользователя."

        try:
            await bot.send_message(
                user_id,
                "Доступ к боту одобрен. Можешь писать и пользоваться командами.",
            )
        except Exception:
            logger.exception("failed to notify user_id=%s about approval", user_id)
        return f"Пользователь {user_id} одобрен."

    async def deny_user(self, bot: Bot, user_id: int, *, admin_id: int) -> str:
        record = self._store.set_status(user_id, "denied", approved_by=admin_id)
        if record is None:
            return "Запрос не найден."

        try:
            await bot.send_message(user_id, "Доступ к боту отклонён администратором.")
        except Exception:
            logger.exception("failed to notify user_id=%s about denial", user_id)
        return f"Пользователю {user_id} отказано в доступе."

    async def verify_google_test_user(
        self,
        bot: Bot,
        user_id: int,
        *,
        admin_id: int,
        oauth_start_url,
    ) -> str:
        from bot.google_test_user_verify import verify_google_test_user_email

        record = self._store.get(user_id)
        if record is None or not record.google_email:
            return "У пользователя не сохранён Google email."

        email = record.google_email
        if self.is_google_test_user_verified(user_id):
            return f"Google email {email} уже подтверждён."

        result = verify_google_test_user_email(email)
        if not result.ok:
            return f"Не удалось проверить автоматически: {result.detail}"
        if result.found is False:
            return (
                f"❌ {email} не найден в Test users.\n"
                "Добавь email в Google Cloud Console и нажми «Добавил — проверить» снова."
            )

        updated = self._store.set_google_test_user_verified(user_id, verified=True)
        if updated is None:
            return "Не удалось сохранить статус проверки."

        from bot.google_connect_flow import send_google_connect_url_to_user

        user_text = (
            f"✅ Google-почта <code>{html.escape(email)}</code> добавлена в Test users.\n\n"
            "Можешь подключить Google:"
        )
        try:
            await bot.send_message(user_id, user_text, parse_mode=ParseMode.HTML)
            await send_google_connect_url_to_user(
                bot,
                user_id,
                oauth_start_url=oauth_start_url,
            )
        except Exception:
            logger.exception("failed to notify user_id=%s about google test user verify", user_id)

        admin_note = (
            f"✅ {html.escape(email)} добавлен и проверен для Telegram ID "
            f"<code>{user_id}</code>."
        )
        for notify_admin_id in admin_user_ids():
            if notify_admin_id == admin_id:
                continue
            try:
                await bot.send_message(notify_admin_id, admin_note, parse_mode=ParseMode.HTML)
            except Exception:
                logger.exception(
                    "failed to notify admin_id=%s about google test user verify",
                    notify_admin_id,
                )

        return f"✅ {email} добавлен и проверен для Telegram ID {user_id}."


_service: AccessService | None = None


def get_access_service() -> AccessService:
    global _service
    if _service is None:
        _service = AccessService()
    return _service


def reset_access_service(service: AccessService | None = None) -> None:
    global _service
    _service = service
