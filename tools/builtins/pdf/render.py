from __future__ import annotations

import asyncio
import io
from typing import Any

import pypdfium2 as pdfium
from pypdf import PdfReader

from tools.builtins.pdf.io import (
    _image_to_data_url,
    _save_image_to_file_ref_sync,
    parse_pages_spec,
    resolve_input,
)
from tools.workspace.vision_pending import push_pending_vision

_MAX_RENDER_PAGES = 20


def _get_page_count(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _render_page_png(data: bytes, page_index: int, dpi: int, scale: float | None) -> bytes:
    doc = pdfium.PdfDocument(data)
    page = doc[page_index]
    if scale is not None:
        render_scale = scale
    else:
        render_scale = dpi / 72.0
    bitmap = page.render(scale=render_scale)
    pil_image = bitmap.to_pil()
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return buf.getvalue()


def _render_sync(
    data: bytes,
    pages: list[int] | None,
    dpi: int,
    scale: float | None,
    width: int | None,
    height: int | None,
    output_mode: str,
) -> dict[str, Any]:
    from PIL import Image

    total = _get_page_count(data)
    target_pages = pages if pages is not None else list(range(1, total + 1))
    if len(target_pages) > _MAX_RENDER_PAGES:
        target_pages = target_pages[:_MAX_RENDER_PAGES]

    results: list[dict[str, Any]] = []
    for page_num in target_pages:
        idx = page_num - 1
        if idx < 0 or idx >= total:
            continue
        png = _render_page_png(data, idx, dpi, scale)

        img_w, img_h = 0, 0
        try:
            pil_img = Image.open(io.BytesIO(png))
            img_w, img_h = pil_img.size
        except Exception:
            pass

        if width and img_w > 0:
            ratio = width / img_w
            new_h = int(img_h * ratio)
            try:
                pil_img = pil_img.resize((width, new_h), Image.LANCZOS)
                buf2 = io.BytesIO()
                pil_img.save(buf2, format="PNG")
                png = buf2.getvalue()
                img_w, img_h = width, new_h
            except Exception:
                pass
        elif height and img_h > 0:
            ratio = height / img_h
            new_w = int(img_w * ratio)
            try:
                pil_img = pil_img.resize((new_w, height), Image.LANCZOS)
                buf2 = io.BytesIO()
                pil_img.save(buf2, format="PNG")
                png = buf2.getvalue()
                img_w, img_h = new_w, height
            except Exception:
                pass

        entry: dict[str, Any] = {
            "page": page_num,
            "width": img_w,
            "height": img_h,
            "size_bytes": len(png),
        }

        if output_mode in ("file_ref", "both"):
            filename = f"page_{page_num}.png"
            try:
                saved = _save_image_to_file_ref_sync(png, filename, "image/png")
                entry["file_ref"] = saved["file_ref"]
            except Exception:
                pass

        if output_mode in ("vision", "both"):
            try:
                data_url = _image_to_data_url(png, "image/png")
                label = f"pdf page {page_num}"
                push_pending_vision(label, data_url)
                entry["vision_injected"] = True
            except Exception:
                entry["vision_injected"] = False

        results.append(entry)

    return {
        "ok": True,
        "page_count": total,
        "pages_rendered": len(results),
        "dpi": dpi if scale is None else None,
        "scale": scale,
        "pages": results,
    }


async def _render_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    pages_spec = arguments.get("pages")
    total = _get_page_count(data)
    pages = parse_pages_spec(pages_spec, total) if pages_spec else None
    dpi = int(arguments.get("dpi", 150))
    scale_raw = arguments.get("scale")
    scale = float(scale_raw) if scale_raw is not None else None
    width = arguments.get("width")
    width = int(width) if width else None
    height = arguments.get("height")
    height = int(height) if height else None
    output_mode = str(arguments.get("output", "vision"))
    return await asyncio.to_thread(
        _render_sync, data, pages, dpi, scale, width, height, output_mode
    )
