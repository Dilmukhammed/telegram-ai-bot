from __future__ import annotations

import mimetypes
from pathlib import Path

from tools.text_file_encoding import is_probably_text_file

_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})


def guess_mime_type(path: Path) -> str | None:
    mime, _encoding = mimetypes.guess_type(path.name)
    return mime


def is_image_file(path: Path, mime_type: str | None = None) -> bool:
    mime = (mime_type or guess_mime_type(path) or "").lower()
    if mime.startswith("image/"):
        return True
    return path.suffix.lower() in _IMAGE_EXTENSIONS


def file_kind(path: Path, mime_type: str | None = None) -> str:
    mime = mime_type or guess_mime_type(path)
    if is_image_file(path, mime):
        return "image"
    if is_probably_text_file(path.name, mime):
        return "text"
    return "binary"
