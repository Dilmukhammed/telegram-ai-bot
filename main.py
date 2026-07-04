import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from agent.loop import Agent
from bot.chat_service import ChatService
from bot.inbound_files import save_telegram_document, save_telegram_photo
from bot.reply import reply_to_user_text, reset_user_queue, send_transcription_to_chat
from bot.user_location import format_location_user_message
from bot.workspace_notify import format_document_agent_message, format_photo_agent_message
from bot.transcription import GroqTranscriber, TranscriptionError, get_transcriber
from bot.vision import ImageTooLargeError, download_message_photo
from config import get_settings, google_oauth_configured, google_oauth_manual_mode
from oauth_server import start_oauth_server
from streaming import TelegramDraftStreamer
from tools.bootstrap import get_tool_runtime
from tools.builtins.google.auth import (
    auth_status_payload,
    build_authorization_url,
    complete_oauth,
    extract_oauth_code_from_text,
    extract_oauth_state_from_text,
    looks_like_manual_oauth_callback,
    missing_oauth_scopes,
    revoke_and_delete,
)
from tools.builtins.google.token_store import get_token_store
from tools.phase4_config import admin_user_ids

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings(require_telegram_token=True)
    runtime = await get_tool_runtime()
    chat_service = ChatService(Agent(settings, runtime))

    oauth_runner = None
    if google_oauth_configured() and not google_oauth_manual_mode():
        oauth_runner = await start_oauth_server()

    transcriber: GroqTranscriber | None
    try:
        transcriber = get_transcriber()
    except TranscriptionError as exc:
        transcriber = None
        logger.warning("Voice disabled: %s", exc)

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()

    def oauth_start_url(user_id: int) -> str:
        settings = get_settings()
        if settings.google_public_base_url:
            return f"{settings.google_public_base_url}/oauth/google/start?user_id={user_id}"
        return (
            f"http://{settings.google_oauth_host}:{settings.google_oauth_port}"
            f"/oauth/google/start?user_id={user_id}"
        )

    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        chat_service.reset_history(message.from_user.id)
        reset_user_queue(message.from_user.id)
        await message.answer(
            "Привет. Я AI-чат бот с доступом в интернет.\n\n"
            "Пиши текст, отправляй голосовое, фото или 📍 геолокацию — отвечу.\n"
            "/reset — очистить историю\n"
            "/demo — пример форматирования\n"
            "/stats — статистика tools + supervisor (admin)\n"
            "/trace_last — последний RunTrace (admin)\n"
            "/connect_google — подключить Google (Calendar, Gmail, Drive, Sheets, Tasks)\n"
            "/google_callback — вставить URL после OAuth\n"
            "/google_status — статус Google\n"
            "/disconnect_google — отключить Google"
        )

    @dp.message(Command("reset"))
    async def on_reset(message: Message) -> None:
        chat_service.reset_history(message.from_user.id)
        reset_user_queue(message.from_user.id)
        await message.answer("История диалога очищена.")

    @dp.message(Command("demo"))
    async def on_demo(message: Message) -> None:
        demo = """# Rich Markdown demo

Inline math: $a^2 + b^2 = c^2$

Block formula:

$$\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}$$

| Feature | Status |
|:--------|:------:|
| Tables  | ✅ |
| Math    | ✅ |
| Agent   | ✅ |

> Бот рендерит это через `sendRichMessage`."""

        streamer = TelegramDraftStreamer(
            bot=bot,
            chat_id=message.chat.id,
            draft_id=message.message_id,
            message_thread_id=message.message_thread_id,
        )
        await streamer.finalize(demo)

    @dp.message(Command("stats"))
    async def on_stats(message: Message) -> None:
        admins = admin_user_ids()
        if not admins or message.from_user.id not in admins:
            await message.answer("Нет доступа. Добавь свой Telegram user id в ADMIN_USER_IDS.")
            return

        streamer = TelegramDraftStreamer(
            bot=bot,
            chat_id=message.chat.id,
            draft_id=message.message_id,
            message_thread_id=message.message_thread_id,
        )
        await streamer.finalize(chat_service.stats_report(runtime))

    @dp.message(Command("trace_last"))
    async def on_trace_last(message: Message) -> None:
        admins = admin_user_ids()
        if not admins or message.from_user.id not in admins:
            await message.answer("Нет доступа. Добавь свой Telegram user id в ADMIN_USER_IDS.")
            return

        streamer = TelegramDraftStreamer(
            bot=bot,
            chat_id=message.chat.id,
            draft_id=message.message_id,
            message_thread_id=message.message_thread_id,
        )
        await streamer.finalize(chat_service.trace_last_report(message.from_user.id))

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

    async def finish_google_connect(message: Message, code: str, *, source_text: str = "") -> None:
        if source_text:
            state_user = extract_oauth_state_from_text(source_text)
            if state_user is not None and state_user != message.from_user.id:
                await message.answer(
                    "Этот OAuth-код от другого пользователя. Запусти /connect_google заново."
                )
                return
        try:
            stored = await complete_oauth(message.from_user.id, code)
            status = auth_status_payload(message.from_user.id)
            gmail_note = " Gmail: OK." if status.get("gmail_ready") else " Gmail: нет — /connect_google."
            drive_note = " Drive: OK." if status.get("drive_ready") else " Drive: нет — /connect_google."
            sheets_note = " Sheets: OK." if status.get("sheets_ready") else " Sheets: нет — /connect_google."
            tasks_note = " Tasks: OK." if status.get("tasks_ready") else " Tasks: нет — /connect_google."
            await message.answer(
                f"Google подключён: {stored.email or 'account'}.{gmail_note}{drive_note}{sheets_note}{tasks_note}"
            )
        except Exception as exc:
            logger.exception("Google OAuth failed for user %s", message.from_user.id)
            await message.answer(f"Не удалось подключить Google: {exc}")

    @dp.message(Command("connect_google"))
    async def on_connect_google(message: Message) -> None:
        if not google_oauth_configured():
            await message.answer("Google OAuth не настроен. Добавь GOOGLE_CLIENT_ID и GOOGLE_CLIENT_SECRET в .env")
            return
        user_id = message.from_user.id
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
        await message.answer(prefix + connect_google_instructions(url))

    @dp.message(Command("google_callback"))
    async def on_google_callback(message: Message) -> None:
        if not google_oauth_configured():
            await message.answer("Google OAuth не настроен на сервере.")
            return
        payload = (message.text or "").partition(" ")[2].strip()
        if not payload:
            await message.answer("Пришли URL после OAuth: `/google_callback http://localhost:1/?code=...`")
            return
        try:
            code = extract_oauth_code_from_text(payload)
        except RuntimeError as exc:
            await message.answer(str(exc))
            return
        if not code:
            await message.answer("В URL нет параметра code. Скопируй адрес целиком из браузера.")
            return
        await finish_google_connect(message, code, source_text=payload)

    @dp.message(Command("google_status"))
    async def on_google_status(message: Message) -> None:
        status = auth_status_payload(message.from_user.id)
        if not status["configured"]:
            await message.answer("Google OAuth не настроен на сервере.")
            return
        if status["connected"]:
            scopes = status.get("scopes") or []
            gmail_ready = status.get("gmail_ready")
            drive_ready = status.get("drive_ready")
            sheets_ready = status.get("sheets_ready")
            tasks_ready = status.get("tasks_ready")
            scope_lines = "\n".join(f"• {scope}" for scope in scopes) or "—"
            await message.answer(
                "Google подключён.\n"
                f"Email: {status['email'] or 'account'}\n"
                f"Gmail: {'готов' if gmail_ready else 'нет — /disconnect_google, затем /connect_google'}\n"
                f"Drive: {'готов' if drive_ready else 'нет — /disconnect_google, затем /connect_google'}\n"
                f"Sheets: {'готов' if sheets_ready else 'нет — /disconnect_google, затем /connect_google'}\n"
                f"Tasks: {'готов' if tasks_ready else 'нет — /disconnect_google, затем /connect_google'}\n\n"
                f"Scopes:\n{scope_lines}"
            )
        else:
            await message.answer("Google не подключён. Используй /connect_google")

    @dp.message(Command("disconnect_google"))
    async def on_disconnect_google(message: Message) -> None:
        deleted = await revoke_and_delete(message.from_user.id)
        if deleted:
            await message.answer("Google Calendar, Gmail, Drive, Sheets и Tasks отключены.")
        else:
            await message.answer("Google не был подключён.")

    @dp.message(F.voice | F.audio)
    async def on_audio(message: Message) -> None:
        if transcriber is None:
            await message.answer("Голосовые отключены: задай GROQ_API_KEY в .env")
            return
        source = "voice" if message.voice else "audio"
        audio = message.voice or message.audio
        if audio is None:
            return

        streamer = TelegramDraftStreamer(
            bot=bot,
            chat_id=message.chat.id,
            draft_id=message.message_id,
            message_thread_id=message.message_thread_id,
        )

        try:
            await streamer.stream_status("Расшифровываю аудио…")
            transcript = await transcriber.transcribe_telegram_audio(bot, audio)
            user_text = await send_transcription_to_chat(message, transcript, source)
            await streamer.aclose()
            await reply_to_user_text(
                message=message,
                chat_service=chat_service,
                user_text=user_text,
            )
        except TranscriptionError as exc:
            logger.warning("Transcription failed for user %s: %s", message.from_user.id, exc)
            await streamer.finalize(f"Не удалось расшифровать аудио: {exc}")
        except Exception:
            logger.exception("Audio message failed for user %s", message.from_user.id)
            await streamer.finalize("Не удалось обработать аудио. Попробуй ещё раз.")

    @dp.message(F.photo)
    async def on_photo(message: Message) -> None:
        streamer = TelegramDraftStreamer(
            bot=bot,
            chat_id=message.chat.id,
            draft_id=message.message_id,
            message_thread_id=message.message_thread_id,
        )

        try:
            await streamer.stream_status("Загружаю изображение…")
            image = await download_message_photo(bot, message)
            caption = (message.caption or "").strip()
            saved = await save_telegram_photo(
                message.from_user.id,
                message,
                raw=image.raw,
                mime_type=image.mime_type,
            )
            user_text = format_photo_agent_message(caption=caption, saved=saved)
            await streamer.aclose()
            await reply_to_user_text(
                message=message,
                chat_service=chat_service,
                user_text=user_text,
                image_data_urls=[image.data_url],
            )
        except ImageTooLargeError as exc:
            await streamer.finalize(f"Изображение слишком большое: {exc}")
        except Exception:
            logger.exception("Photo message failed for user %s", message.from_user.id)
            await streamer.finalize("Не удалось обработать изображение. Попробуй ещё раз.")

    @dp.message(F.document)
    async def on_document(message: Message) -> None:
        streamer = TelegramDraftStreamer(
            bot=bot,
            chat_id=message.chat.id,
            draft_id=message.message_id,
            message_thread_id=message.message_thread_id,
        )

        try:
            await streamer.stream_status("Сохраняю файл…")
            saved = await save_telegram_document(bot, message.from_user.id, message)
            caption = (message.caption or "").strip()
            user_text = format_document_agent_message(saved, caption=caption)
            await streamer.aclose()
            await reply_to_user_text(
                message=message,
                chat_service=chat_service,
                user_text=user_text,
            )
        except ValueError as exc:
            await streamer.finalize(str(exc))
        except Exception:
            logger.exception("Document message failed for user %s", message.from_user.id)
            await streamer.finalize("Не удалось обработать файл. Попробуй ещё раз.")

    @dp.message(F.location)
    async def on_location(message: Message) -> None:
        location = message.location
        if location is None:
            return

        venue = message.venue
        user_text = format_location_user_message(
            lat=location.latitude,
            lng=location.longitude,
            label=venue.title if venue else None,
            caption=message.caption,
        )
        await reply_to_user_text(
            message=message,
            chat_service=chat_service,
            user_text=user_text,
        )

    @dp.message(F.text & ~F.text.startswith("/"))
    async def on_text(message: Message) -> None:
        user_text = message.text.strip()
        if not user_text:
            return

        if google_oauth_configured() and google_oauth_manual_mode():
            if looks_like_manual_oauth_callback(user_text):
                try:
                    code = extract_oauth_code_from_text(user_text)
                except RuntimeError as exc:
                    await message.answer(str(exc))
                    return
                if code:
                    await finish_google_connect(message, code, source_text=user_text)
                    return

        await reply_to_user_text(
            message=message,
            chat_service=chat_service,
            user_text=user_text,
        )

    voice_note = "voice" if transcriber is not None else "no voice (GROQ_API_KEY)"
    logger.info(
        "Bot started with agent + rich streaming + %s + vision. Model: %s",
        voice_note,
        settings.openai_model,
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
