from __future__ import annotations

import asyncio
import io
from typing import Any

from tools.builtins.pdf.io import resolve_input
from tools.builtins.pdf.pages import save_output_sync

_PAGE_SIZES = {
    "A4": (595, 842),
    "Letter": (612, 792),
    "Legal": (612, 1008),
    "A3": (842, 1191),
    "A5": (420, 595),
}


def _get_page_size(page_size: str) -> tuple[float, float]:
    return _PAGE_SIZES.get(page_size, _PAGE_SIZES["A4"])


def _create_sync(
    content: str,
    fmt: str,
    page_size: str,
    font: str,
    font_size: float,
    margin: float,
    title: str | None,
) -> dict[str, Any]:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        PageBreak,
    )
    from reportlab.lib.units import mm

    pw, ph = _get_page_size(page_size)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=(pw, ph),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=title or "",
    )

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName=font,
        fontSize=font_size,
        leading=font_size * 1.4,
        alignment=TA_LEFT,
    )

    story: list[Any] = []

    if fmt == "markdown":
        import re

        heading_style = ParagraphStyle(
            "Heading",
            parent=styles["Heading1"],
            fontName=font + "-Bold" if font == "Helvetica" else font,
            fontSize=font_size + 6,
            leading=(font_size + 6) * 1.4,
        )
        heading2_style = ParagraphStyle(
            "Heading2",
            parent=styles["Heading2"],
            fontName=font + "-Bold" if font == "Helvetica" else font,
            fontSize=font_size + 4,
            leading=(font_size + 4) * 1.4,
        )
        heading3_style = ParagraphStyle(
            "Heading3",
            parent=styles["Heading3"],
            fontName=font + "-Bold" if font == "Helvetica" else font,
            fontSize=font_size + 2,
            leading=(font_size + 2) * 1.4,
        )
        code_style = ParagraphStyle(
            "Code",
            parent=styles["Code"],
            fontName="Courier",
            fontSize=font_size - 1,
            leading=(font_size - 1) * 1.3,
        )

        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            stripped = line.strip()

            if not stripped:
                story.append(Spacer(1, 6))
                i += 1
                continue

            if stripped.startswith("### "):
                story.append(Paragraph(stripped[4:], heading3_style))
            elif stripped.startswith("## "):
                story.append(Paragraph(stripped[3:], heading2_style))
            elif stripped.startswith("# "):
                story.append(Paragraph(stripped[2:], heading_style))
            elif stripped.startswith("---") or stripped.startswith("***"):
                story.append(Spacer(1, 12))
            elif stripped.startswith("- ") or stripped.startswith("* "):
                bullet_text = stripped[2:]
                bullet_text = _md_inline(bullet_text)
                story.append(Paragraph(f"• {_md_inline(bullet_text)}", body_style))
            elif stripped.startswith("> "):
                quote_style = ParagraphStyle(
                    "Quote", parent=body_style, leftIndent=20, textColor="#666666"
                )
                story.append(Paragraph(_md_inline(stripped[2:]), quote_style))
            elif stripped.startswith("```"):
                code_lines: list[str] = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                code_text = "<br/>".join(_escape_xml(l) for l in code_lines)
                story.append(Paragraph(code_text, code_style))
            elif stripped.startswith("|") and stripped.endswith("|"):
                table_lines: list[str] = [stripped]
                i += 1
                while i < len(lines) and lines[i].strip().startswith("|"):
                    table_lines.append(lines[i].strip())
                    i += 1
                rows = _parse_md_table(table_lines)
                if rows:
                    from reportlab.platypus import Table as RLTable
                    from reportlab.lib import colors

                    tbl = RLTable(
                        rows,
                        style=[
                            ("Grid", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("FontName", (0, 0), (-1, -1), font),
                            ("FontSize", (0, 0), (-1, -1), font_size - 1),
                        ],
                    )
                    story.append(tbl)
                continue
            else:
                story.append(Paragraph(_md_inline(stripped), body_style))
            i += 1
    else:
        for line in content.split("\n"):
            if line.strip() == "":
                story.append(Spacer(1, font_size * 1.4))
            elif line.strip() == "---page_break---":
                story.append(PageBreak())
            else:
                story.append(Paragraph(_escape_xml(line), body_style))

    doc.build(story)
    pdf_data = buf.getvalue()
    saved = save_output_sync(pdf_data, "created.pdf")

    return {
        "ok": True,
        "format": fmt,
        "page_size": page_size,
        "title": title or "",
        "size_bytes": len(pdf_data),
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _md_inline(text: str) -> str:
    text = _escape_xml(text)
    text = text.replace("**", "<b>", 1)
    text = text.replace("**", "</b>", 1)
    text = text.replace("*", "<i>", 1)
    text = text.replace("*", "</i>", 1)
    text = text.replace("`", "<font face='Courier'>", 1)
    text = text.replace("`", "</font>", 1)
    return text


def _parse_md_table(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        if line.strip().startswith("|") and set(line.strip().strip("|").strip()) <= set("-: "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append([_md_inline(c) for c in cells])
    return rows


async def _create_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    content = str(arguments.get("content", "")).strip()
    if not content:
        return {"ok": False, "error": "content is required"}
    fmt = str(arguments.get("format", "markdown"))
    page_size = str(arguments.get("page_size", "A4"))
    font = str(arguments.get("font", "Helvetica"))
    font_size = float(arguments.get("font_size", 12))
    margin = float(arguments.get("margin", 36))
    title = arguments.get("title")
    return await asyncio.to_thread(
        _create_sync, content, fmt, page_size, font, font_size, margin, title
    )


def _create_from_images_sync(
    image_data_list: list[tuple[bytes, str]],
    page_size: str,
    fit: str,
) -> dict[str, Any]:
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import SimpleDocTemplate, Image as RLImage, PageBreak

    pw, ph = _get_page_size(page_size)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(pw, ph))

    story: list[Any] = []
    for idx, (img_data, img_name) in enumerate(image_data_list):
        if idx > 0:
            story.append(PageBreak())

        img_reader = ImageReader(io.BytesIO(img_data))
        img_w, img_h = img_reader.getSize()

        if fit == "stretch":
            draw_w, draw_h = pw, ph
        else:
            scale = min(pw / img_w, ph / img_h)
            draw_w = img_w * scale
            draw_h = img_h * scale

        x = (pw - draw_w) / 2
        y = (ph - draw_h) / 2

        from reportlab.platypus import Flowable

        class _ImgFlowable(Flowable):
            def __init__(self, img_reader, x, y, w, h):
                super().__init__()
                self._img_reader = img_reader
                self._x = x
                self._y = y
                self._w = w
                self._h = h

            def draw(self):
                self.canv.drawImage(
                    self._img_reader, self._x, self._y, width=self._w, height=self._h
                )

        story.append(_ImgFlowable(img_reader, x, y, draw_w, draw_h))

    doc.build(story)
    pdf_data = buf.getvalue()
    saved = save_output_sync(pdf_data, "from_images.pdf")

    return {
        "ok": True,
        "images_used": len(image_data_list),
        "page_size": page_size,
        "fit": fit,
        "size_bytes": len(pdf_data),
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _create_from_images_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    from tools.run_files import require_run_file_store

    file_refs = arguments.get("image_file_refs") or []
    if not isinstance(file_refs, list) or not file_refs:
        return {"ok": False, "error": "image_file_refs (array) is required"}

    page_size = str(arguments.get("page_size", "A4"))
    fit = str(arguments.get("fit", "contain"))

    store = require_run_file_store()
    image_data_list: list[tuple[bytes, str]] = []
    for ref in file_refs:
        try:
            stored = store.resolve(str(ref))
            image_data_list.append((stored.path.read_bytes(), stored.filename))
        except Exception as exc:
            return {"ok": False, "error": f"Cannot resolve file_ref {ref}: {exc}"}

    return await asyncio.to_thread(_create_from_images_sync, image_data_list, page_size, fit)


def _create_blank_sync(page_count: int, page_size: str) -> dict[str, Any]:
    from reportlab.pdfgen import canvas

    pw, ph = _get_page_size(page_size)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(pw, ph))
    for _ in range(page_count):
        c.showPage()
    c.save()
    pdf_data = buf.getvalue()
    saved = save_output_sync(pdf_data, "blank.pdf")

    return {
        "ok": True,
        "page_count": page_count,
        "page_size": page_size,
        "size_bytes": len(pdf_data),
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _create_blank_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    page_count = int(arguments.get("pages", 1))
    if page_count < 1:
        page_count = 1
    if page_count > 1000:
        return {"ok": False, "error": "Max 1000 pages"}
    page_size = str(arguments.get("page_size", "A4"))
    return await asyncio.to_thread(_create_blank_sync, page_count, page_size)
