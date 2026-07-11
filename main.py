import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from agent.loop import Agent
from bot.access_control import AccessControlMiddleware
from bot.access_service import get_access_service
from bot.chat_service import ChatService
from bot.chat_store.migrate_v1 import run_v1_migration_if_needed
from bot.google_connect_flow import start_google_connect, try_handle_google_email
from bot.instance_lock import BotInstanceLockError, acquire_instance_lock
from bot.inbound_files import save_telegram_document, save_telegram_photo
from bot.yandex_connect import begin_yandex_connect, yandex_status_text
from bot.reply import reply_to_user_text, reset_user_queue, send_transcription_to_chat
from bot.user_location import format_location_user_message
from bot.workspace_notify import format_document_agent_message, format_photo_agent_message
from bot.transcription import GroqTranscriber, TranscriptionError, get_transcriber
from bot.vision import ImageTooLargeError, download_message_photo
from config import get_settings, google_oauth_configured, google_oauth_manual_mode
from oauth_server import start_oauth_server
from rich_demo import build_rich_blocks_demo_markdown
from streaming import TelegramDraftStreamer
from tools.bootstrap import get_tool_runtime
from tools.tool_results.maintenance import run_tool_result_maintenance, tool_result_cleanup_loop
from tools.builtins.google.auth import (
    auth_status_payload,
    complete_oauth,
    extract_oauth_code_from_text,
    extract_oauth_state_from_text,
    looks_like_manual_oauth_callback,
    revoke_and_delete,
)
from tools.builtins.yandex.auth import revoke_and_delete as revoke_yandex
from tools.phase4_config import admin_user_ids

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings(require_telegram_token=True)
    instance_lock = None
    if settings.instance_lock_enabled:
        try:
            instance_lock = acquire_instance_lock(settings.instance_lock_path)
        except BotInstanceLockError as exc:
            logger.error("%s", exc)
            raise SystemExit(1) from exc

    runtime = await get_tool_runtime()
    migration = run_v1_migration_if_needed()
    if migration.applied:
        logger.info(
            "chat_v1_migration startup users=%s messages=%s backup=%s",
            migration.users_migrated,
            migration.messages_migrated,
            migration.backup_path,
        )
    elif migration.reason not in {"disabled", "already migrated"}:
        logger.info("chat_v1_migration skipped reason=%s", migration.reason)

    chat_service = ChatService(Agent(settings, runtime))
    from bot.chat_store.day_archive import register_day_archive_callback

    register_day_archive_callback(chat_service.invalidate_user_history)
    memory_service = None
    memory_ingest_runtime = None
    memory_verification_scheduler = None

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
    dp.message.middleware(AccessControlMiddleware())

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
        chat_service.reset_history(message.from_user.id, closed_by="start")
        reset_user_queue(message.from_user.id)
        await message.answer(
            "Привет. Я AI-чат бот с доступом в интернет.\n\n"
            "Пиши текст, отправляй голосовое, фото или 📍 геолокацию — отвечу.\n"
            "/reset — очистить историю\n"
            "/sessions — список сохранённых сессий\n"
            "/session &lt;id&gt; — summary сессии\n"
            "/demo — пример форматирования\n"
            "/demo_rich — multi-block POC (текст + фото + collage + …)\n"
            "/stats — контекст: модель, токены (admin)\n"
            "/trace_last — последний RunTrace (admin)\n"
            "/coach_last — что именно получил trajectory coach (admin)\n"
            "/checker_last — последний tool checker review (admin)\n"
            "/dump_context — сохранить историю в data/context_dump.json (admin)\n"
            "/connect_google — подключить Google (Calendar, Gmail, Drive, Sheets, Tasks)\n"
            "/google_callback — вставить URL после OAuth\n"
            "/google_status — статус Google\n"
            "/disconnect_google — отключить Google\n"
            "/connect_yandex — подключить Яндекс.Музыку\n"
            "/yandex_status — статус Яндекс.Музыки\n"
            "/disconnect_yandex — отключить Яндекс.Музыку"
        )

    @dp.message(Command("reset"))
    async def on_reset(message: Message) -> None:
        archived_deleted = chat_service.reset_history(message.from_user.id)
        reset_user_queue(message.from_user.id)
        if archived_deleted:
            await message.answer(
                f"История диалога очищена. Удалено archived tool results: {archived_deleted}."
            )
        else:
            await message.answer("История диалога очищена.")

    @dp.message(Command("sessions"))
    async def on_sessions(message: Message) -> None:
        from bot.chat_commands import format_sessions_list
        from bot.chat_store import get_chat_store

        store = get_chat_store()
        sessions = store.list_sessions(message.from_user.id, limit=20)
        await message.answer(format_sessions_list(sessions))

    @dp.message(Command("session"))
    async def on_session(message: Message) -> None:
        from bot.chat_commands import format_session_detail
        from bot.chat_store import get_chat_store

        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.answer("Usage: /session <session_id>")
            return
        session_id = parts[1].strip()
        store = get_chat_store()
        session = store.get_session_for_user(session_id, message.from_user.id)
        if session is None:
            await message.answer("Session not found.")
            return
        trace_count = store.count_session_traces(session_id)
        await message.answer(format_session_detail(session, trace_count=trace_count))

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

    @dp.message(Command("demo_rich"))
    async def on_demo_rich(message: Message) -> None:
        streamer = TelegramDraftStreamer(
            bot=bot,
            chat_id=message.chat.id,
            draft_id=message.message_id,
            message_thread_id=message.message_thread_id,
        )
        await streamer.stream_status("Собираю multi-block POC…")
        await streamer.finalize(build_rich_blocks_demo_markdown())

    @dp.message(Command("memory_status"))
    async def on_memory_status(message: Message) -> None:
        admins = admin_user_ids()
        if not admins or message.from_user.id not in admins:
            await message.answer("Нет доступа. Добавь свой Telegram user id в ADMIN_USER_IDS.")
            return
        if memory_service is None:
            await message.answer(
                "Graph memory не активна (MEMORY_INGEST_ENABLED=0, MEMORY_WORKER_ENABLED=0)."
            )
            return
        from bot.memory_commands import format_memory_status

        text = format_memory_status(
            service=memory_service,
            ingest_runtime=memory_ingest_runtime,
            ingest_enabled=settings.memory_ingest_enabled,
            worker_enabled=settings.memory_worker_enabled,
            extraction_enabled=settings.memory_extraction_enabled,
            verification_enabled=settings.memory_verification_enabled,
        )
        await message.answer(text[:4000])

    @dp.message(Command("memory_scan_once"))
    async def on_memory_scan_once(message: Message) -> None:
        admins = admin_user_ids()
        if not admins or message.from_user.id not in admins:
            await message.answer("Нет доступа. Добавь свой Telegram user id в ADMIN_USER_IDS.")
            return
        if memory_ingest_runtime is None:
            await message.answer("Ingestion выключен (MEMORY_INGEST_ENABLED=0).")
            return
        memory_ingest_runtime.wake_scanner()
        await message.answer("Scanner wake queued.")

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
        async with streamer:
            await streamer.stream_status("Считаю токены…")
            report = await chat_service.context_stats_report(message.from_user.id)
            await streamer.finalize(report)

    @dp.message(Command("dump_context"))
    async def on_dump_context(message: Message) -> None:
        admins = admin_user_ids()
        if not admins or message.from_user.id not in admins:
            await message.answer("Нет доступа. Добавь свой Telegram user id в ADMIN_USER_IDS.")
            return

        user_id = message.from_user.id
        await message.answer("Сохраняю историю и считаю токены…")
        try:
            path, payload = await chat_service.dump_context_to_file(user_id)
        except Exception:
            logger.exception("context dump failed user_id=%s", user_id)
            await message.answer("Не удалось сохранить dump.")
            return

        summary = payload["summary"]
        tokens = payload.get("prompt_tokens")
        token_line = f"{tokens:,} tokens" if tokens is not None else "tokens: n/a"
        caption = (
            f"Context dump\n"
            f"{token_line} | {summary['messages']} msgs | {summary['user_turns']} turns\n"
            f"chars: {summary['chars_total']:,} (system {summary['system_prompt_chars']:,})\n"
            f"file: {path.resolve()}"
        )
        from aiogram.types import BufferedInputFile

        data = path.read_bytes()
        await message.answer_document(
            BufferedInputFile(data, filename=path.name),
            caption=caption[:1024],
        )

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

    @dp.message(Command("coach_last"))
    async def on_coach_last(message: Message) -> None:
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
        await streamer.finalize(chat_service.coach_last_report(message.from_user.id))

    @dp.message(Command("checker_last"))
    async def on_checker_last(message: Message) -> None:
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
        await streamer.finalize(chat_service.checker_last_report(message.from_user.id))

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
        await start_google_connect(message, oauth_start_url=oauth_start_url)

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

    @dp.message(Command("connect_yandex"))
    async def on_connect_yandex(message: Message) -> None:
        try:
            text = await begin_yandex_connect(message.from_user.id)
            await message.answer(text)
        except Exception as exc:
            logger.exception("Yandex connect failed for user %s", message.from_user.id)
            await message.answer(f"Не удалось начать подключение Яндекс.Музыки: {exc}")

    @dp.message(Command("yandex_status"))
    async def on_yandex_status(message: Message) -> None:
        await message.answer(yandex_status_text(message.from_user.id))

    @dp.message(Command("disconnect_yandex"))
    async def on_disconnect_yandex(message: Message) -> None:
        deleted = await revoke_yandex(message.from_user.id)
        if deleted:
            await message.answer("Яндекс.Музыка отключена.")
        else:
            await message.answer("Яндекс.Музыка не была подключена.")

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

    @dp.callback_query(F.data.startswith("gacc:"))
    async def on_google_access_callback(callback: CallbackQuery) -> None:
        admins = admin_user_ids()
        if not admins or callback.from_user.id not in admins:
            await callback.answer("Нет доступа", show_alert=True)
            return

        user_id = get_access_service().parse_google_access_callback(callback.data or "")
        if user_id is None:
            await callback.answer("Неизвестная команда")
            return

        note = await get_access_service().verify_google_test_user(
            callback.bot,
            user_id,
            admin_id=callback.from_user.id,
            oauth_start_url=oauth_start_url,
        )
        await callback.answer(note[:200], show_alert=len(note) > 200)
        if callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                logger.debug("could not remove google verify buttons", exc_info=True)
            await callback.message.answer(note)

    @dp.callback_query(F.data.startswith("acc:"))
    async def on_access_callback(callback: CallbackQuery) -> None:
        admins = admin_user_ids()
        if not admins or callback.from_user.id not in admins:
            await callback.answer("Нет доступа", show_alert=True)
            return

        parsed = get_access_service().parse_access_callback(callback.data or "")
        if parsed is None:
            await callback.answer("Неизвестная команда")
            return

        action, user_id = parsed
        access = get_access_service()
        if action == "approve":
            note = await access.approve_user(
                callback.bot,
                user_id,
                admin_id=callback.from_user.id,
            )
        else:
            note = await access.deny_user(
                callback.bot,
                user_id,
                admin_id=callback.from_user.id,
            )

        await callback.answer(note[:200])
        if callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                logger.debug("could not remove access request buttons", exc_info=True)
            await callback.message.answer(note)

    @dp.message(F.text & ~F.text.startswith("/"))
    async def on_text(message: Message) -> None:
        user_text = message.text.strip()
        if not user_text:
            return

        if await try_handle_google_email(
            message,
            bot,
            oauth_start_url=oauth_start_url,
        ):
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
    if settings.tool_result_archive_enabled:
        startup_deleted = run_tool_result_maintenance()
        if startup_deleted:
            logger.info("tool_result_archive startup purge deleted=%s", startup_deleted)
        asyncio.create_task(tool_result_cleanup_loop())
    from bot.chat_index.startup import enqueue_chat_index_startup
    from bot.chat_store.period_boundary import enqueue_period_boundary_loop

    index_task = enqueue_chat_index_startup()
    if index_task is not None:
        logger.info("chat_index startup queued")
    boundary_task = enqueue_period_boundary_loop()
    if boundary_task is not None:
        logger.info(
            "chat_period_boundary loop queued tz=%s poll=%ss",
            settings.bot_timezone,
            settings.chat_period_summary_boundary_poll_seconds,
        )
    if (
        settings.memory_ingest_enabled
        or settings.memory_worker_enabled
        or settings.memory_extraction_enabled
        or settings.memory_verification_enabled
    ):
        from memory.service import create_memory_runtime

        memory_service = create_memory_runtime()

    if settings.memory_ingest_enabled:
        from bot.chat_store import get_chat_store
        from bot.memory_chat_adapter import ChatEvidenceAdapter, set_text_ingest_sink
        from memory.config import memory_config_from_settings
        from memory.ingestion.runtime import TextIngestionRuntime
        from tools.tool_results.memory_adapter import ToolEvidenceAdapter, ToolMemoryLifecycleObserver
        from tools.tool_results.store import get_tool_result_store

        tool_store = get_tool_result_store()
        memory_ingest_runtime = TextIngestionRuntime(
            service=memory_service,
            config=memory_config_from_settings(),
            chat_reader=ChatEvidenceAdapter(get_chat_store()),
            tool_reader=ToolEvidenceAdapter(tool_store),
        )
        set_text_ingest_sink(memory_ingest_runtime.sink)
        tool_store.set_lifecycle_observer(
            ToolMemoryLifecycleObserver(memory_ingest_runtime.sink)
        )
        await memory_ingest_runtime.start()
        logger.info("memory ingest runtime started")

    if settings.memory_extraction_enabled and memory_service is not None:
        from memory.extraction.pipeline import LLMExtractionModel, register_text_extractor
        from llm import LLMClient

        extraction_client = LLMClient(
            settings,
            profile=settings.memory_extraction_model_profile,
        )
        register_text_extractor(
            memory_service.registry,
            service=memory_service,
            model=LLMExtractionModel(
                extraction_client,
                model_profile=settings.memory_extraction_model_profile,
                max_tokens=settings.memory_extraction_max_tokens,
            ),
            timezone=settings.bot_timezone,
        )
        logger.info("memory text extraction registered (shadow-only)")

    if settings.memory_verification_enabled and memory_service is not None:
        from llm import LLMClient
        from memory.verification.pipeline import (
            LLMVerificationModel,
            register_candidate_verifier,
        )
        from memory.verification.scheduler import VerificationScheduler

        support_client = LLMClient(
            settings,
            profile=settings.memory_verification_support_model_profile,
        )
        adversarial_client = LLMClient(
            settings,
            profile=settings.memory_verification_adversarial_model_profile,
        )
        register_candidate_verifier(
            memory_service.registry,
            service=memory_service,
            support_model=LLMVerificationModel(
                support_client,
                model_profile=settings.memory_verification_support_model_profile,
                max_tokens=settings.memory_verification_max_tokens,
            ),
            adversarial_model=LLMVerificationModel(
                adversarial_client,
                model_profile=settings.memory_verification_adversarial_model_profile,
                max_tokens=settings.memory_verification_max_tokens,
            ),
            policy_version=settings.memory_verification_policy_version,
            context_chars=settings.memory_verification_context_chars,
        )
        memory_verification_scheduler = VerificationScheduler(
            service=memory_service,
            support_profile=settings.memory_verification_support_model_profile,
            adversarial_profile=settings.memory_verification_adversarial_model_profile,
            policy_version=settings.memory_verification_policy_version,
            interval_seconds=settings.memory_verification_scan_interval_seconds,
            batch_size=settings.memory_verification_scan_batch_size,
        )
        await memory_verification_scheduler.start()
        logger.info("memory candidate verification registered (shadow-only)")

    if settings.memory_worker_enabled and memory_service is not None:
        await memory_service.start_worker()
        logger.info("memory worker started")
    logger.info(
        "Bot started with agent + rich streaming + %s + vision. Model: %s",
        voice_note,
        settings.openai_model,
    )
    try:
        await dp.start_polling(bot)
    finally:
        if memory_verification_scheduler is not None:
            await memory_verification_scheduler.stop()
        if memory_ingest_runtime is not None:
            from bot.memory_chat_adapter import set_text_ingest_sink
            from tools.tool_results.store import get_tool_result_store

            get_tool_result_store().set_lifecycle_observer(None)
            set_text_ingest_sink(None)
            await memory_ingest_runtime.stop(
                grace_seconds=settings.memory_ingest_shutdown_grace_seconds
            )
        if memory_service is not None and settings.memory_worker_enabled:
            await memory_service.stop_worker()
        if instance_lock is not None:
            instance_lock.release()


if __name__ == "__main__":
    asyncio.run(main())
