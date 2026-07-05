from __future__ import annotations

import asyncio
import io
import base64
from pathlib import Path
from typing import Any

from tools.context import get_run_context
from tools.run_files import require_run_file_store
from tools.workspace.store import read_workspace_bytes

_PDF_MIME = "application/pdf"


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


def _resolve_input_sync(file_ref: str | None, path: str | None) -> tuple[bytes, str]:
    if file_ref:
        stored = require_run_file_store().resolve(file_ref)
        return stored.path.read_bytes(), stored.filename
    if path:
        user_id = _require_user_id()
        _p, data, _mime = read_workspace_bytes(user_id, path)
        return data, _p.name
    raise ValueError("Either file_ref or path is required")


async def resolve_input(file_ref: str | None, path: str | None) -> tuple[bytes, str]:
    return await asyncio.to_thread(_resolve_input_sync, file_ref, path)


def _save_output_sync(data: bytes, filename: str) -> dict[str, Any]:
    store = require_run_file_store()
    return store.save(data, filename=filename, mime_type=_PDF_MIME)


async def save_output(data: bytes, filename: str = "output.pdf") -> dict[str, Any]:
    return await asyncio.to_thread(_save_output_sync, data, filename)


def _image_to_data_url(image_bytes: bytes, mime_type: str = "image/png") -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _save_image_to_file_ref_sync(
    image_bytes: bytes, filename: str, mime_type: str = "image/png"
) -> dict[str, Any]:
    store = require_run_file_store()
    return store.save(data=image_bytes, filename=filename, mime_type=mime_type)


async def save_image(
    image_bytes: bytes, filename: str, mime_type: str = "image/png"
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _save_image_to_file_ref_sync, image_bytes, filename, mime_type
    )


def parse_pages_spec(pages: str | None, total: int) -> list[int] | None:
    if pages is None or not pages.strip():
        return None
    result: set[int] = set()
    for part in pages.split(","):
        part = part.strip().lower()
        if not part:
            continue
        if part in ("end", "last"):
            result.add(total)
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            left = left.strip()
            right = right.strip()
            start = int(left) if left else 1
            end = int(right) if right else total
            if start < 1:
                start = 1
            if end > total:
                end = total
            for p in range(start, end + 1):
                result.add(p)
        else:
            p = int(part)
            if 1 <= p <= total:
                result.add(p)
    if not result:
        return None
    return sorted(result)
