from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from tools.builtins.pdf.io import resolve_input
from tools.builtins.pdf.pages import save_output_sync

logger = logging.getLogger(__name__)


def _get_page_count(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _optimize_sync(
    data: bytes,
    level: str,
    linearize: bool,
) -> dict[str, Any]:
    old_size = len(data)
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)

    if level == "light":
        writer = PdfWriter(clone_from=reader)
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=False)
    elif level == "aggressive":
        writer = PdfWriter(clone_from=reader)
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
        for page in writer.pages:
            try:
                page.compress_content_streams()
            except Exception:
                pass
        try:
            writer.remove_images()
        except Exception:
            pass
    else:
        writer = PdfWriter(clone_from=reader)
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=False)
        for page in writer.pages:
            try:
                page.compress_content_streams()
            except Exception:
                pass

    buf = io.BytesIO()
    writer.write(buf)
    new_data = buf.getvalue()
    new_size = len(new_data)
    saved = save_output_sync(new_data, "optimized.pdf")

    return {
        "ok": True,
        "page_count": total,
        "level": level,
        "linearize": linearize,
        "old_size": old_size,
        "new_size": new_size,
        "saved_bytes": old_size - new_size,
        "saved_percent": round((1 - new_size / old_size) * 100, 1) if old_size > 0 else 0,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _optimize_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    level = str(arguments.get("level", "medium"))
    if level not in ("light", "medium", "aggressive"):
        level = "medium"
    linearize = bool(arguments.get("linearize", False))
    return await asyncio.to_thread(_optimize_sync, data, level, linearize)


def _repair_sync(data: bytes) -> dict[str, Any]:
    old_size = len(data)
    repairs: list[str] = []

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except PdfReadError as exc:
        repairs.append(f"Strict parse failed: {exc}")
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
        except Exception as exc2:
            return {
                "ok": False,
                "error": f"Cannot repair: {type(exc2).__name__}: {exc2}",
            }
    except Exception as exc:
        repairs.append(f"Standard parse failed: {type(exc).__name__}: {exc}")
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
        except Exception as exc2:
            return {
                "ok": False,
                "error": f"Cannot repair: {type(exc2).__name__}: {exc2}",
            }

    try:
        total = len(reader.pages)
    except Exception as exc:
        repairs.append(f"Page count failed: {exc}")
        total = 0

    if total == 0:
        return {
            "ok": False,
            "error": "Cannot repair: no pages found",
            "repairs": repairs,
        }

    writer = PdfWriter()
    pages_added = 0
    pages_failed = 0

    for idx in range(total):
        try:
            page = reader.pages[idx]
            writer.add_page(page)
            pages_added += 1
        except Exception as exc:
            pages_failed += 1
            repairs.append(f"Page {idx + 1} skipped: {type(exc).__name__}: {exc}")

    try:
        meta = reader.metadata
        if meta:
            writer.add_metadata({k: str(v) for k, v in meta.items() if v is not None})
    except Exception:
        repairs.append("Metadata copy failed")

    buf = io.BytesIO()
    writer.write(buf)
    new_data = buf.getvalue()
    saved = save_output_sync(new_data, "repaired.pdf")

    if pages_added > 0:
        repairs.append(f"Rebuilt PDF with {pages_added} pages")
    if pages_failed > 0:
        repairs.append(f"Skipped {pages_failed} corrupt pages")

    return {
        "ok": True,
        "page_count_original": total,
        "page_count_repaired": pages_added,
        "pages_failed": pages_failed,
        "old_size": old_size,
        "new_size": len(new_data),
        "repairs": repairs,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _repair_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return await asyncio.to_thread(_repair_sync, data)
