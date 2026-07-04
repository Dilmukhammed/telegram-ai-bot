from __future__ import annotations

from pathlib import Path

# Common mime → extension for Telegram/mobile openers.
_MIME_TO_EXTENSION: dict[str, str] = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/markdown": ".md",
    "text/html": ".html",
    "application/json": ".json",
    "application/xml": ".xml",
    "application/zip": ".zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.ms-powerpoint": ".ppt",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "video/mp4": ".mp4",
}

_KNOWN_EXTENSIONS = frozenset(ext.lstrip(".").lower() for ext in _MIME_TO_EXTENSION.values())


def extension_for_mime_type(mime_type: str | None) -> str | None:
    mime = (mime_type or "").lower().split(";", 1)[0].strip()
    if not mime:
        return None
    return _MIME_TO_EXTENSION.get(mime)


def ensure_filename_extension(filename: str, mime_type: str | None) -> str:
    """Ensure outbound filename has an extension matching mime_type (e.g. .pdf)."""
    name = Path(filename or "file").name or "file"
    expected = extension_for_mime_type(mime_type)
    if not expected:
        return name

    lower = name.lower()
    if lower.endswith(expected):
        return name

    suffix = Path(name).suffix.lower()
    if suffix and suffix.lstrip(".") in _KNOWN_EXTENSIONS:
        stem = name[: -len(suffix)] if suffix else name
        return f"{stem}{expected}"

    return f"{name}{expected}"
