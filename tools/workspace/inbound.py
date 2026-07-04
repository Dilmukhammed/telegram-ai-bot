from __future__ import annotations

import io
from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import Message

from bot.vision import download_message_photo
from config import format_byte_size, get_settings
from tools.workspace.paths import sanitize_filename, unique_relative_path
from tools.workspace.store import save_bytes


@dataclass(frozen=True)
class SavedInboundFile:
    path: str
    size_bytes: int
    mime_type: str | None
    filename: str


async def save_telegram_document(bot: Bot, user_id: int, message: Message) -> SavedInboundFile:
    document = message.document
    if document is None:
        raise ValueError("message has no document")

    settings = get_settings()
    if document.file_size and document.file_size > settings.workspace_upload_max_bytes:
        raise ValueError(
            f"document too large ({format_byte_size(document.file_size)}; "
            f"max {format_byte_size(settings.workspace_upload_max_bytes)})"
        )

    telegram_file = await bot.get_file(document.file_id)
    buffer = io.BytesIO()
    await bot.download(telegram_file, destination=buffer)
    raw = buffer.getvalue()

    filename = sanitize_filename(document.file_name or f"document_{message.message_id}")
    relative = unique_relative_path(user_id, f"uploads/{message.message_id}_{filename}")
    mime_type = document.mime_type
    saved = save_bytes(user_id, relative=relative, data=raw, mime_type=mime_type)
    return SavedInboundFile(
        path=str(saved["path"]),
        size_bytes=int(saved["size_bytes"]),
        mime_type=mime_type,
        filename=filename,
    )


async def save_telegram_photo(user_id: int, message: Message, *, raw: bytes, mime_type: str) -> SavedInboundFile:
    settings = get_settings()
    if len(raw) > settings.workspace_upload_max_bytes:
        raise ValueError("photo too large for workspace save")

    ext = ".jpg"
    if mime_type == "image/png":
        ext = ".png"
    elif mime_type == "image/webp":
        ext = ".webp"
    elif mime_type == "image/gif":
        ext = ".gif"

    relative = unique_relative_path(user_id, f"uploads/{message.message_id}_photo{ext}")
    saved = save_bytes(user_id, relative=relative, data=raw, mime_type=mime_type)
    return SavedInboundFile(
        path=str(saved["path"]),
        size_bytes=int(saved["size_bytes"]),
        mime_type=mime_type,
        filename=f"photo{ext}",
    )


async def save_telegram_photo_from_message(bot: Bot, user_id: int, message: Message) -> SavedInboundFile:
    image = await download_message_photo(bot, message)
    return await save_telegram_photo(
        user_id,
        message,
        raw=image.raw,
        mime_type=image.mime_type,
    )
