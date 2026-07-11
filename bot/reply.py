import logging

from aiogram.types import InputRichMessage, Message, ReplyParameters

from bot.outbound_delivery import deliver_outbound_attachments
from bot.chat_request import ChatRequest, merge_chat_requests
from bot.chat_service import ChatService
from bot.session_queue import SessionQueueManager
from bot.transcription_format import (
    AudioSource,
    format_transcription_agent,
    format_transcription_chat,
)
from config import get_settings
from rich_format import prepare_telegram_rich_markdown
from streaming import TelegramDraftStreamer

logger = logging.getLogger(__name__)

_session_queue: SessionQueueManager[ChatRequest] = SessionQueueManager()


def reset_user_queue(user_id: int) -> None:
    _session_queue.reset(user_id)


async def send_transcription_to_chat(
    message: Message,
    transcript: str,
    source: AudioSource,
) -> str:
    chat_text = format_transcription_chat(transcript, source)
    agent_text = format_transcription_agent(transcript, source)
    try:
        await message.bot.send_rich_message(
            chat_id=message.chat.id,
            message_thread_id=message.message_thread_id,
            rich_message=InputRichMessage(markdown=prepare_telegram_rich_markdown(chat_text)),
            reply_parameters=ReplyParameters(message_id=message.message_id),
        )
    except Exception:
        logger.warning("Rich transcription message failed, using plain reply", exc_info=True)
        await message.reply(chat_text[: get_settings().telegram_plain_limit])
    return agent_text


async def _process_chat_requests(
    *,
    requests: list[ChatRequest],
    chat_service: ChatService,
) -> None:
    message, user_text, image_data_urls, message_at = merge_chat_requests(requests)
    user_id = message.from_user.id
    streamer = TelegramDraftStreamer(
        bot=message.bot,
        chat_id=message.chat.id,
        draft_id=message.message_id,
        message_thread_id=message.message_thread_id,
    )

    async with streamer:
        try:
            response = await chat_service.generate_reply(
                user_id,
                user_text,
                on_status=streamer.stream_status,
                message_at=message_at,
                image_data_urls=image_data_urls,
                telegram_message_id=message.message_id,
                telegram_chat_id=message.chat.id,
                telegram_message=message,
            )
            if not response.text:
                raise RuntimeError("Empty response from agent")

            await streamer.stream_prefilled(response.text)
            await streamer.finalize(response.text, reply_markup=response.reply_markup)
            if response.outbound_files:
                await deliver_outbound_attachments(
                    message.bot,
                    chat_id=message.chat.id,
                    message_thread_id=message.message_thread_id,
                    items=response.outbound_files,
                )
        except Exception:
            logger.exception("Agent failed for user %s", user_id)
            await streamer.finalize("Не удалось получить ответ. Попробуй ещё раз.")


async def reply_to_user_text(
    *,
    message: Message,
    chat_service: ChatService,
    user_text: str,
    image_data_urls: list[str] | None = None,
) -> None:
    user_id = message.from_user.id
    request = ChatRequest(
        message=message,
        user_text=user_text,
        image_data_urls=image_data_urls,
    )

    async def process_batch(requests: list[ChatRequest]) -> None:
        await _process_chat_requests(requests=requests, chat_service=chat_service)

    async def on_busy() -> None:
        await message.answer(
            "⏳ Предыдущий запрос ещё обрабатывается. "
            "Сообщения объединятся и отправятся одним запросом, как только бот освободится."
        )

    async def on_queue_full() -> None:
        await message.answer(
            "⏳ Очередь переполнена. Дождись ответа на предыдущие сообщения и попробуй снова."
        )

    await _session_queue.submit(user_id, request, process_batch, on_busy, on_queue_full=on_queue_full)
