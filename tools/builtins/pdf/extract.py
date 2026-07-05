from __future__ import annotations

import asyncio
import io
from typing import Any

import pdfplumber
from pypdf import PdfReader

from tools.builtins.pdf.io import (
    _image_to_data_url,
    _save_image_to_file_ref_sync,
    parse_pages_spec,
    resolve_input,
)
from tools.workspace.vision_pending import push_pending_vision

_MAX_TEXT_CHARS_PER_PAGE = 8000
_MAX_TABLES = 20
_MAX_IMAGES = 20
_MIN_IMAGE_SIZE = 50


def _get_page_count(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _extract_text_sync(
    data: bytes, pages: list[int] | None, preserve_layout: bool, max_chars: int | None
) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    target_pages = pages if pages is not None else list(range(1, total + 1))
    per_page_cap = max_chars or _MAX_TEXT_CHARS_PER_PAGE
    page_texts: list[dict[str, Any]] = []
    for page_num in target_pages:
        idx = page_num - 1
        if idx < 0 or idx >= total:
            continue
        page = reader.pages[idx]
        try:
            text = page.extract_text(
                extraction_mode="layout" if preserve_layout else "plain"
            )
        except Exception:
            text = ""
        text = (text or "").strip()
        if len(text) > per_page_cap:
            text = text[: per_page_cap - 1] + "…"
        page_texts.append({"page": page_num, "text": text})
    return {
        "ok": True,
        "page_count": total,
        "pages_extracted": len(page_texts),
        "pages": page_texts,
    }


async def _extract_text_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    pages_spec = arguments.get("pages")
    total = _get_page_count(data)
    pages = parse_pages_spec(pages_spec, total) if pages_spec else None
    preserve_layout = bool(arguments.get("preserve_layout", True))
    max_chars = arguments.get("max_chars")
    if isinstance(max_chars, str) and max_chars.strip():
        max_chars = int(max_chars)
    return await asyncio.to_thread(
        _extract_text_sync, data, pages, preserve_layout, max_chars
    )


def _extract_tables_sync(
    data: bytes,
    pages: list[int] | None,
    strategy: str,
    min_rows: int,
    min_cols: int,
) -> dict[str, Any]:
    tables_found: list[dict[str, Any]] = []
    total = 0
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        total = len(pdf.pages)
        target_pages = pages if pages is not None else list(range(1, total + 1))
        for page_num in target_pages:
            idx = page_num - 1
            if idx < 0 or idx >= total:
                continue
            page = pdf.pages[idx]
            try:
                found = page.extract_tables(
                    table_settings={
                        "vertical_strategy": strategy,
                        "horizontal_strategy": strategy,
                    }
                )
            except Exception:
                found = []
            for table_idx, rows in enumerate(found):
                if not rows or len(rows) < min_rows:
                    continue
                clean_rows = []
                for row in rows:
                    clean_row = [
                        (cell or "").strip() if isinstance(cell, str) else str(cell or "")
                        for cell in row
                    ]
                    if any(c for c in clean_row):
                        clean_rows.append(clean_row)
                if len(clean_rows) < min_rows:
                    continue
                cols = max(len(r) for r in clean_rows) if clean_rows else 0
                if cols < min_cols:
                    continue
                tables_found.append(
                    {
                        "page": page_num,
                        "table_index": table_idx,
                        "rows": clean_rows[:100],
                        "row_count": len(clean_rows),
                        "col_count": cols,
                    }
                )
                if len(tables_found) >= _MAX_TABLES:
                    break
            if len(tables_found) >= _MAX_TABLES:
                break
    return {
        "ok": True,
        "page_count": total,
        "tables_found": len(tables_found),
        "tables": tables_found,
    }


async def _extract_tables_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    pages_spec = arguments.get("pages")
    total = _get_page_count(data)
    pages = parse_pages_spec(pages_spec, total) if pages_spec else None
    strategy = str(arguments.get("strategy", "lines"))
    min_rows = int(arguments.get("min_rows", 2))
    min_cols = int(arguments.get("min_cols", 2))
    return await asyncio.to_thread(
        _extract_tables_sync, data, pages, strategy, min_rows, min_cols
    )


def _extract_images_sync(
    data: bytes,
    pages: list[int] | None,
    min_size: int,
    output_mode: str,
) -> dict[str, Any]:
    from PIL import Image

    results: list[dict[str, Any]] = []
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    target_pages = pages if pages is not None else list(range(1, total + 1))
    for page_num in target_pages:
        idx = page_num - 1
        if idx < 0 or idx >= total:
            continue
        page = reader.pages[idx]
        try:
            images = page.images
        except Exception:
            images = []
        for img_idx, img in enumerate(images):
            if len(results) >= _MAX_IMAGES:
                break
            img_data = img.data
            if len(img_data) < min_size:
                continue
            try:
                pil_img = Image.open(io.BytesIO(img_data))
                width, height = pil_img.size
                fmt = (pil_img.format or "UNKNOWN").upper()
            except Exception:
                width, height, fmt = 0, 0, "UNKNOWN"
            entry: dict[str, Any] = {
                "page": page_num,
                "image_index": img_idx,
                "width": width,
                "height": height,
                "format": fmt,
                "size_bytes": len(img_data),
            }
            if output_mode in ("file_ref", "both"):
                ext = fmt.lower() if fmt != "UNKNOWN" else "png"
                filename = f"page{page_num}_img{img_idx}.{ext}"
                mime = f"image/{fmt.lower()}" if fmt != "UNKNOWN" else "image/png"
                try:
                    saved = _save_image_to_file_ref_sync(img_data, filename, mime)
                    entry["file_ref"] = saved["file_ref"]
                except Exception:
                    pass
            if output_mode in ("vision", "both"):
                try:
                    data_url = _image_to_data_url(img_data, "image/png")
                    label = f"pdf page {page_num} image {img_idx}"
                    push_pending_vision(label, data_url)
                    entry["vision_injected"] = True
                except Exception:
                    entry["vision_injected"] = False
            results.append(entry)
        if len(results) >= _MAX_IMAGES:
            break
    return {
        "ok": True,
        "page_count": total,
        "images_found": len(results),
        "images": results,
    }


async def _extract_images_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    pages_spec = arguments.get("pages")
    total = _get_page_count(data)
    pages = parse_pages_spec(pages_spec, total) if pages_spec else None
    min_size = int(arguments.get("min_size", _MIN_IMAGE_SIZE))
    output_mode = str(arguments.get("output", "vision"))
    return await asyncio.to_thread(
        _extract_images_sync, data, pages, min_size, output_mode
    )
