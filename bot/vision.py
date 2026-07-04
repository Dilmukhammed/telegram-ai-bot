import base64
import io
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.types import Message, PhotoSize

from config import get_settings


class ImageTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class DownloadedImage:
    data_url: str
    mime_type: str
    size_bytes: int
    raw: bytes


def image_max_bytes() -> int:
    return get_settings().image_max_bytes


def build_user_message_content(text: str, image_data_urls: list[str]) -> str | list[dict[str, Any]]:
    if not image_data_urls:
        return text

    parts: list[dict[str, Any]] = []
    if text.strip():
        parts.append({"type": "text", "text": text})
    elif image_data_urls:
        parts.append(
            {
                "type": "text",
                "text": "[image attached] Describe or answer about the image.",
            }
        )
    for data_url in image_data_urls:
        parts.append({"type": "image_url", "image_url": {"url": data_url}})

    if not parts:
        return text
    return parts


def history_text_for_image_turn(text: str) -> str:
    body = text.strip()
    if body:
        return f"[image]\n{body}"
    return "[image]"


async def download_largest_photo(bot: Bot, photos: list[PhotoSize]) -> DownloadedImage:
    if not photos:
        raise ValueError("No photo sizes in message")

    telegram_file = await bot.get_file(photos[-1].file_id)
    buffer = io.BytesIO()
    await bot.download(telegram_file, destination=buffer)
    raw = buffer.getvalue()

    max_bytes = image_max_bytes()
    if len(raw) > max_bytes:
        raise ImageTooLargeError(
            f"Image is too large ({len(raw)} bytes, limit {max_bytes})"
        )

    mime_type = _mime_type_for_path(telegram_file.file_path)
    encoded = base64.b64encode(raw).decode("ascii")
    return DownloadedImage(
        data_url=f"data:{mime_type};base64,{encoded}",
        mime_type=mime_type,
        size_bytes=len(raw),
        raw=raw,
    )


async def download_message_photo(bot: Bot, message: Message) -> DownloadedImage:
    if not message.photo:
        raise ValueError("Message has no photo")
    return await download_largest_photo(bot, message.photo)


def _mime_type_for_path(file_path: str | None) -> str:
    if not file_path:
        return "image/jpeg"
    lowered = file_path.lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"
