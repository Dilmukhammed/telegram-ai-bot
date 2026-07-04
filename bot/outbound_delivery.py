from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BufferedInputFile

from tools.outbound_files import OutboundDelivery

logger = logging.getLogger(__name__)


async def deliver_outbound_attachments(
    bot: Bot,
    *,
    chat_id: int,
    message_thread_id: int | None,
    items: tuple[OutboundDelivery, ...],
) -> list[str]:
    errors: list[str] = []
    for item in items:
        input_file = BufferedInputFile(item.data, filename=item.filename)
        try:
            if item.kind == "photo":
                await bot.send_photo(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    photo=input_file,
                    caption=item.caption,
                )
            elif item.kind == "audio":
                await bot.send_audio(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    audio=input_file,
                    caption=item.caption,
                )
            else:
                await bot.send_document(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    document=input_file,
                    caption=item.caption,
                )
        except Exception as exc:
            logger.exception(
                "Failed to deliver outbound file chat=%s filename=%s kind=%s",
                chat_id,
                item.filename,
                item.kind,
            )
            errors.append(f"{item.filename}: {exc}")
    return errors
