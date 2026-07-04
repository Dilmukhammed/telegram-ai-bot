from __future__ import annotations

import base64
from pathlib import Path

from bot.vision import ImageTooLargeError, image_max_bytes
from tools.workspace.mime import guess_mime_type, is_image_file


def build_image_data_url(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if not is_image_file(path):
        raise ValueError(f"not an image file: {path.name}")

    raw = path.read_bytes()
    max_bytes = image_max_bytes()
    if len(raw) > max_bytes:
        raise ImageTooLargeError(
            f"Image is too large ({len(raw)} bytes, limit {max_bytes})"
        )

    mime_type = guess_mime_type(path) or "image/jpeg"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
