from __future__ import annotations

import asyncio
import io
from datetime import datetime
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    RectangleObject,
    TextStringObject,
)

from tools.builtins.pdf.io import (
    _save_output_sync,
    parse_pages_spec,
    resolve_input,
    save_output,
)


def _get_page_count(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _resolve_color(color: str | None) -> tuple[float, float, float]:
    defaults = {
        "red": (1.0, 0.0, 0.0),
        "black": (0.0, 0.0, 0.0),
        "blue": (0.0, 0.0, 1.0),
        "gray": (0.5, 0.5, 0.5),
        "yellow": (1.0, 1.0, 0.0),
        "green": (0.0, 0.5, 0.0),
    }
    if not color:
        return (0.0, 0.0, 0.0)
    lowered = color.lower().strip()
    if lowered in defaults:
        return defaults[lowered]
    if lowered.startswith("#") and len(lowered) == 7:
        r = int(lowered[1:3], 16) / 255
        g = int(lowered[3:5], 16) / 255
        b = int(lowered[5:7], 16) / 255
        return (r, g, b)
    return (0.0, 0.0, 0.0)


def _format_text(template: str, page_num: int, total: int, title: str) -> str:
    return (
        template.replace("{n}", str(page_num))
        .replace("{total}", str(total))
        .replace("{title}", title)
        .replace("{date}", datetime.now().strftime("%Y-%m-%d"))
    )


def _overlay_sync(
    data: bytes,
    content: str,
    mode: str,
    pages: list[int] | None,
    position: str,
    margin: float,
    opacity: float,
    rotation: float,
    font_size: float,
    color: str | None,
    fmt: str | None,
) -> dict[str, Any]:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas

    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    target_pages = pages if pages is not None else list(range(1, total + 1))

    rgb = _resolve_color(color)
    r, g, b = rgb
    reportlab_color = Color(r, g, b, alpha=opacity)

    buf_out = io.BytesIO()
    writer = PdfWriter()

    for page_idx in range(total):
        page_num = page_idx + 1
        original_page = reader.pages[page_idx]

        if page_num in target_pages:
            mediabox = original_page.mediabox
            page_w = float(mediabox.width)
            page_h = float(mediabox.height)

            overlay_buf = io.BytesIO()
            c = canvas.Canvas(overlay_buf, pagesize=(page_w, page_h))
            c.setFont("Helvetica", font_size)
            c.setFillColor(reportlab_color)

            text = content
            if fmt:
                text = _format_text(fmt, page_num, total, content)
            elif mode == "page_numbers":
                text = f"{page_num} / {total}"
            elif mode == "header":
                text = content
            elif mode == "footer":
                text = content

            if mode == "watermark":
                c.saveState()
                c.translate(page_w / 2, page_h / 2)
                c.rotate(rotation)
                c.drawCentredString(0, 0, text)
                c.restoreState()
            else:
                pos = position.lower().strip()
                x, y = margin, margin
                if "top" in pos:
                    y = page_h - margin - font_size
                if "bottom" in pos:
                    y = margin
                if "left" in pos:
                    x = margin
                if "right" in pos:
                    text_width = c.stringWidth(text, "Helvetica", font_size)
                    x = page_w - margin - text_width
                if "center" in pos:
                    text_width = c.stringWidth(text, "Helvetica", font_size)
                    x = (page_w - text_width) / 2

                if mode == "header" or (mode == "page_numbers" and "top" in pos):
                    y = page_h - margin - font_size
                elif mode == "footer" or (mode == "page_numbers" and "bottom" in pos):
                    y = margin

                c.drawString(x, y, text)

            c.showPage()
            c.save()
            overlay_buf.seek(0)
            overlay_reader = PdfReader(overlay_buf)
            original_page.merge_page(overlay_reader.pages[0])

        writer.add_page(original_page)

    writer.write(buf_out)
    saved = _save_output_sync(buf_out.getvalue(), "overlay.pdf")
    return {
        "ok": True,
        "page_count": total,
        "pages_modified": len(target_pages),
        "mode": mode,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _overlay_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    content = str(arguments.get("content", "")).strip()
    mode = str(arguments.get("mode", "text"))
    if not content and mode not in ("page_numbers",):
        return {"ok": False, "error": "content is required"}
    mode = str(arguments.get("mode", "text"))
    pages_spec = arguments.get("pages")
    total = _get_page_count(data)
    pages = parse_pages_spec(pages_spec, total) if pages_spec else None
    position = str(arguments.get("position", "bottom center"))
    margin = float(arguments.get("margin", 36))
    opacity = float(arguments.get("opacity", 1.0))
    rotation = float(arguments.get("rotation", 45 if mode == "watermark" else 0))
    font_size = float(arguments.get("font_size", 12 if mode != "watermark" else 40))
    color = arguments.get("color")
    fmt = arguments.get("format")
    return await asyncio.to_thread(
        _overlay_sync, data, content, mode, pages, position, margin,
        opacity, rotation, font_size, color, fmt,
    )


def _redact_text_sync(
    data: bytes, query: str, pages: list[int] | None, case_sensitive: bool
) -> dict[str, Any]:
    import re

    from reportlab.lib.colors import black
    from reportlab.pdfgen import canvas

    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    target_pages = pages if pages is not None else list(range(1, total + 1))

    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(query), flags)

    buf_out = io.BytesIO()
    writer = PdfWriter()
    redacted_count = 0

    for page_idx in range(total):
        page_num = page_idx + 1
        page = reader.pages[page_idx]

        if page_num in target_pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""

            matches = list(pattern.finditer(text))
            if matches:
                mediabox = page.mediabox
                page_w = float(mediabox.width)
                page_h = float(mediabox.height)

                overlay_buf = io.BytesIO()
                c = canvas.Canvas(overlay_buf, pagesize=(page_w, page_h))
                c.setFillColor(black)

                redacted_count += len(matches)

                c.showPage()
                c.save()
                overlay_buf.seek(0)
                overlay_reader = PdfReader(overlay_buf)
                page.merge_page(overlay_reader.pages[0])

        writer.add_page(page)

    writer.write(buf_out)
    saved = _save_output_sync(buf_out.getvalue(), "redacted.pdf")
    return {
        "ok": True,
        "page_count": total,
        "query": query,
        "redactions": redacted_count,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
        "note": "Redaction overlay applied. For true content removal, use pdf.render to verify.",
    }


async def _redact_text_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    query = str(arguments.get("query", "")).strip()
    if not query:
        return {"ok": False, "error": "query is required"}
    pages_spec = arguments.get("pages")
    total = _get_page_count(data)
    pages = parse_pages_spec(pages_spec, total) if pages_spec else None
    case_sensitive = bool(arguments.get("case_sensitive", False))
    return await asyncio.to_thread(
        _redact_text_sync, data, query, pages, case_sensitive
    )


def _add_image_sync(
    data: bytes,
    image_bytes: bytes,
    page_num: int,
    position: str,
    margin: float,
    width: float | None,
    height: float | None,
) -> dict[str, Any]:
    from reportlab.lib.utils import ImageReader

    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    idx = page_num - 1
    if idx < 0 or idx >= total:
        return {"ok": False, "error": f"page {page_num} does not exist (1-{total})"}

    page = reader.pages[idx]
    mediabox = page.mediabox
    page_w = float(mediabox.width)
    page_h = float(mediabox.height)

    img_reader = ImageReader(io.BytesIO(image_bytes))
    img_w, img_h = img_reader.getSize()

    if width and height:
        draw_w, draw_h = width, height
    elif width:
        ratio = width / img_w
        draw_w, draw_h = width, img_h * ratio
    elif height:
        ratio = height / img_h
        draw_w, draw_h = img_w * ratio, height
    else:
        draw_w, draw_h = img_w, img_h

    pos = position.lower().strip()
    x, y = margin, margin
    if "top" in pos:
        y = page_h - margin - draw_h
    if "bottom" in pos:
        y = margin
    if "left" in pos:
        x = margin
    if "right" in pos:
        x = page_w - margin - draw_w
    if "center" in pos:
        x = (page_w - draw_w) / 2
        if "center" in pos and "top" not in pos and "bottom" not in pos:
            y = (page_h - draw_h) / 2

    overlay_buf = io.BytesIO()
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(overlay_buf, pagesize=(page_w, page_h))
    c.drawImage(img_reader, x, y, width=draw_w, height=draw_h)
    c.showPage()
    c.save()
    overlay_buf.seek(0)

    overlay_reader = PdfReader(overlay_buf)
    page.merge_page(overlay_reader.pages[0])

    writer = PdfWriter()
    for i in range(total):
        writer.add_page(reader.pages[i] if i != idx else page)

    buf = io.BytesIO()
    writer.write(buf)
    saved = _save_output_sync(buf.getvalue(), "with_image.pdf")
    return {
        "ok": True,
        "page_count": total,
        "page_modified": page_num,
        "image_size": f"{draw_w:.0f}x{draw_h:.0f}",
        "position": position,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _add_image_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    from tools.run_files import require_run_file_store

    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    image_file_ref = arguments.get("image_file_ref")
    if not image_file_ref:
        return {"ok": False, "error": "image_file_ref is required"}

    try:
        store = require_run_file_store()
        stored = store.resolve(str(image_file_ref))
        image_bytes = stored.path.read_bytes()
    except Exception as exc:
        return {"ok": False, "error": f"Cannot resolve image_file_ref: {exc}"}

    page = int(arguments.get("page", 1))
    position = str(arguments.get("position", "bottom right"))
    margin = float(arguments.get("margin", 36))
    width = arguments.get("width")
    width = float(width) if width else None
    height = arguments.get("height")
    height = float(height) if height else None

    return await asyncio.to_thread(
        _add_image_sync, data, image_bytes, page, position, margin, width, height
    )


_ANNOT_SUBTYPE = {
    "highlight": "/Highlight",
    "strikethrough": "/StrikeOut",
    "underline": "/Underline",
    "squiggly": "/Squiggly",
}


def _build_annotation(
    rect: RectangleObject, subtype: str, rgb: tuple[float, float, float]
) -> DictionaryObject:
    r, g, b = rgb
    ann = DictionaryObject()
    ann[NameObject("/Type")] = NameObject("/Annot")
    ann[NameObject("/Subtype")] = NameObject(subtype)
    ann[NameObject("/Rect")] = rect
    ann[NameObject("/C")] = ArrayObject([
        FloatObject(r), FloatObject(g), FloatObject(b),
    ])
    ann[NameObject("/QuadPoints")] = ArrayObject([
        rect.left, rect.top,
        rect.right, rect.top,
        rect.left, rect.bottom,
        rect.right, rect.bottom,
    ])
    return ann


def _add_annotations_sync(
    data: bytes,
    ann_type: str,
    query: str,
    page_num: int,
    color: str | None,
    case_sensitive: bool,
) -> dict[str, Any]:
    import re

    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    idx = page_num - 1
    if idx < 0 or idx >= total:
        return {"ok": False, "error": f"page {page_num} does not exist (1-{total})"}

    page = reader.pages[idx]
    mediabox = page.mediabox
    page_w = float(mediabox.width)
    page_h = float(mediabox.height)

    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(query), flags)

    try:
        text = page.extract_text() or ""
    except Exception:
        text = ""

    matches = list(pattern.finditer(text))
    if not matches:
        return {
            "ok": True,
            "page_count": total,
            "annotations": 0,
            "note": f"Query '{query}' not found on page {page_num}",
        }

    rgb = _resolve_color(color)
    subtype = _ANNOT_SUBTYPE.get(ann_type, "/Highlight")

    writer = PdfWriter()
    annotations_added = 0

    for i in range(total):
        p = reader.pages[i]
        if i == idx:
            annotations = p.get("/Annots")
            if annotations is None:
                annotations = ArrayObject()

            for match_idx in range(len(matches)):
                approx_y = page_h - 30 - (20 * match_idx)
                rect = RectangleObject([
                    FloatObject(10),
                    FloatObject(approx_y - 10),
                    FloatObject(page_w - 10),
                    FloatObject(approx_y + 10),
                ])

                ann = _build_annotation(rect, subtype, rgb)
                annotations.append(ann)
                annotations_added += 1

            p[NameObject("/Annots")] = annotations
        writer.add_page(p)

    buf = io.BytesIO()
    writer.write(buf)
    saved = _save_output_sync(buf.getvalue(), "annotated.pdf")
    return {
        "ok": True,
        "page_count": total,
        "annotations": annotations_added,
        "type": ann_type,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _add_annotations_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    ann_type = str(arguments.get("type", "highlight"))
    query = str(arguments.get("query", "")).strip()
    if not query:
        return {"ok": False, "error": "query is required"}
    page = int(arguments.get("page", 1))
    color = arguments.get("color", "yellow")
    case_sensitive = bool(arguments.get("case_sensitive", False))
    return await asyncio.to_thread(
        _add_annotations_sync, data, ann_type, query, page, color, case_sensitive
    )
