from __future__ import annotations

import asyncio
import base64
import io
import logging
from typing import Any

from openai import AsyncOpenAI
from pypdf import PdfReader
import pypdfium2 as pdfium

from tools.builtins.pdf.io import parse_pages_spec, resolve_input

logger = logging.getLogger(__name__)

_OCR_SYSTEM_PROMPT = (
    "You are an OCR engine. Extract ALL text from the provided page image. "
    "Preserve the visual reading order (top-to-bottom, left-to-right). "
    "Keep paragraph breaks. Output ONLY the extracted text, nothing else. "
    "If the page is blank or has no readable text, output an empty string."
)


def _get_page_count(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _render_page_to_png(data: bytes, page_index: int, dpi: int) -> bytes:
    doc = pdfium.PdfDocument(data)
    page = doc[page_index]
    scale = dpi / 72.0
    bitmap = page.render(scale=scale)
    pil_image = bitmap.to_pil()
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return buf.getvalue()


def _image_to_data_url(png_bytes: bytes) -> str:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _get_ocr_client() -> AsyncOpenAI | None:
    from config import get_settings

    settings = get_settings()
    if not settings.ocr_api_key or not settings.ocr_model:
        return None
    return AsyncOpenAI(
        base_url=settings.ocr_base_url or None,
        api_key=settings.ocr_api_key,
    )


async def _ocr_single_page(
    client: AsyncOpenAI, model: str, png_bytes: bytes
) -> str:
    data_url = _image_to_data_url(png_bytes)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _OCR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all text from this page."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        max_tokens=4000,
        temperature=0,
    )
    return (response.choices[0].message.content or "").strip()


async def _ocr_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    from config import get_settings

    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    settings = get_settings()
    pages_spec = arguments.get("pages")
    total = _get_page_count(data)
    pages = parse_pages_spec(pages_spec, total) if pages_spec else None
    lang = str(arguments.get("lang", "auto"))
    dpi = int(arguments.get("dpi", settings.ocr_dpi))
    max_pages = settings.ocr_max_pages

    client = _get_ocr_client()
    if client is None:
        return {
            "ok": False,
            "error": "OCR is not configured. Set OCR_API_KEY and OCR_MODEL in .env",
        }

    target_pages = pages if pages is not None else list(range(1, total + 1))
    if len(target_pages) > max_pages:
        target_pages = target_pages[:max_pages]

    page_results: list[dict[str, Any]] = []
    for page_num in target_pages:
        idx = page_num - 1
        if idx < 0 or idx >= total:
            continue
        png = await asyncio.to_thread(_render_page_to_png, data, idx, dpi)
        try:
            text = await _ocr_single_page(client, settings.ocr_model, png)
        except Exception as exc:
            logger.warning("OCR failed for page %s: %s", page_num, exc)
            text = ""
        page_results.append({"page": page_num, "text": text})

    return {
        "ok": True,
        "page_count": total,
        "pages_ocrd": len(page_results),
        "lang": lang,
        "pages": page_results,
    }


def _is_scanned_sync(data: bytes, pages: list[int] | None) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    target_pages = pages if pages is not None else list(range(1, total + 1))

    page_results: list[dict[str, Any]] = []
    scanned_pages: list[int] = []
    text_chars_total = 0

    for page_num in target_pages:
        idx = page_num - 1
        if idx < 0 or idx >= total:
            continue
        page = reader.pages[idx]
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        char_count = len(text.strip())
        text_chars_total += char_count

        has_images = False
        try:
            has_images = len(page.images) > 0
        except Exception:
            pass

        is_scanned_page = char_count < 10 and has_images
        page_results.append(
            {
                "page": page_num,
                "char_count": char_count,
                "has_images": has_images,
                "scanned": is_scanned_page,
            }
        )
        if is_scanned_page:
            scanned_pages.append(page_num)

    pages_checked = len(page_results)
    text_ratio = text_chars_total / pages_checked if pages_checked > 0 else 0
    is_scanned = len(scanned_pages) > pages_checked / 2 if pages_checked > 0 else False

    return {
        "ok": True,
        "page_count": total,
        "pages_checked": pages_checked,
        "scanned": is_scanned,
        "text_ratio": round(text_ratio, 1),
        "scanned_pages": scanned_pages,
        "pages": page_results,
    }


async def _is_scanned_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    pages_spec = arguments.get("pages")
    total = _get_page_count(data)
    pages = parse_pages_spec(pages_spec, total) if pages_spec else None
    return await asyncio.to_thread(_is_scanned_sync, data, pages)
