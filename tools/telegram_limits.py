from __future__ import annotations

from typing import Literal

from config import format_byte_size

TelegramSendKind = Literal["document", "photo", "audio"]

__all__ = (
    "TelegramSendKind",
    "format_byte_size",
    "resolve_send_kind",
    "telegram_limit_bytes",
    "telegram_limit_error",
)


def resolve_send_kind(as_kind: str | None, mime_type: str | None) -> TelegramSendKind:
    value = (as_kind or "auto").lower().strip()
    if value in {"document", "photo", "audio"}:
        return value  # type: ignore[return-value]
    mime = (mime_type or "").lower()
    if mime.startswith("image/"):
        return "photo"
    if mime.startswith("audio/"):
        return "audio"
    return "document"


def telegram_limit_bytes(kind: TelegramSendKind, *, settings) -> int:
    if kind == "photo":
        return settings.telegram_max_photo_bytes
    if kind == "audio":
        return settings.telegram_max_audio_bytes
    return settings.telegram_max_document_bytes


def telegram_limit_error(
    *,
    size_bytes: int,
    kind: TelegramSendKind,
    limit_bytes: int,
) -> str:
    return (
        f"File is too large to send via Telegram ({format_byte_size(size_bytes)}). "
        f"Limit for {kind} is {format_byte_size(limit_bytes)} ({limit_bytes} bytes)."
    )
