from __future__ import annotations

import io
from typing import Any

from memory.documents.models import DocumentStructureResult, StructuredRegion


def structure_pdf(data: bytes, *, max_pages: int = 200) -> DocumentStructureResult:
    import pdfplumber

    warnings: list[str] = []
    regions: list[StructuredRegion] = []
    ordinal = 0
    title = None
    page_count = 0

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page_count = len(pdf.pages)
        if page_count > max_pages:
            warnings.append(f"truncated_to_{max_pages}_pages")
        meta = pdf.metadata or {}
        title = str(meta.get("Title") or "").strip() or None

        for page_idx, page in enumerate(pdf.pages[:max_pages], start=1):
            width = float(page.width or 0.0) or None
            height = float(page.height or 0.0) or None
            page_text = (page.extract_text() or "").strip()
            ordinal += 1
            regions.append(
                StructuredRegion(
                    region_type="page",
                    page=page_idx,
                    text=page_text,
                    ordinal=ordinal,
                    bbox=(0.0, 0.0, float(width or 0.0), float(height or 0.0))
                    if width and height
                    else None,
                    page_width=width,
                    page_height=height,
                    coordinate_system="pdf_points",
                )
            )

            words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
            paragraphs = _cluster_words_to_paragraphs(words)
            for p_idx, para in enumerate(paragraphs):
                text = str(para["text"]).strip()
                if not text:
                    continue
                ordinal += 1
                region_type = "heading" if _looks_like_heading(text, para) else "paragraph"
                regions.append(
                    StructuredRegion(
                        region_type=region_type,
                        page=page_idx,
                        text=text,
                        ordinal=ordinal,
                        bbox=tuple(para["bbox"]),  # type: ignore[arg-type]
                        char_start=0,
                        char_end=len(text),
                        paragraph_index=p_idx,
                        page_width=width,
                        page_height=height,
                        coordinate_system="pdf_points",
                    )
                )

            tables = page.extract_tables() or []
            for t_idx, table in enumerate(tables):
                rows = [[(cell or "").strip() for cell in row] for row in (table or [])]
                if not rows:
                    continue
                serialized = _serialize_table(rows)
                ordinal += 1
                regions.append(
                    StructuredRegion(
                        region_type="table",
                        page=page_idx,
                        text=serialized,
                        ordinal=ordinal,
                        table_index=t_idx,
                        page_width=width,
                        page_height=height,
                        coordinate_system="pdf_points",
                        metadata={"row_count": len(rows), "col_count": max((len(r) for r in rows), default=0)},
                    )
                )
                for r_idx, row in enumerate(rows):
                    for c_idx, cell in enumerate(row):
                        if not cell:
                            continue
                        ordinal += 1
                        regions.append(
                            StructuredRegion(
                                region_type="table_cell",
                                page=page_idx,
                                text=cell,
                                ordinal=ordinal,
                                table_index=t_idx,
                                row_index=r_idx,
                                col_index=c_idx,
                                page_width=width,
                                page_height=height,
                                coordinate_system="pdf_points",
                            )
                        )

            # Embedded images via pdfplumber page images metadata (bytes optional).
            for i_idx, image in enumerate(page.images or []):
                bbox = (
                    float(image.get("x0", 0.0)),
                    float(image.get("top", 0.0)),
                    float(image.get("x1", 0.0)),
                    float(image.get("bottom", 0.0)),
                )
                ordinal += 1
                regions.append(
                    StructuredRegion(
                        region_type="embedded_image",
                        page=page_idx,
                        text=f"[embedded image page={page_idx} index={i_idx}]",
                        ordinal=ordinal,
                        bbox=bbox,
                        image_index=i_idx,
                        page_width=width,
                        page_height=height,
                        coordinate_system="pdf_points",
                        metadata={"width": image.get("width"), "height": image.get("height")},
                    )
                )

    return DocumentStructureResult(
        format="pdf",
        title=title,
        page_count=page_count,
        regions=tuple(regions),
        warnings=tuple(warnings),
    )


def _cluster_words_to_paragraphs(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not words:
        return []
    # Sort reading order.
    ordered = sorted(
        words,
        key=lambda w: (round(float(w.get("top", 0.0)), 1), float(w.get("x0", 0.0))),
    )
    paragraphs: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    last_bottom: float | None = None
    for word in ordered:
        top = float(word.get("top", 0.0))
        bottom = float(word.get("bottom", top))
        if current and last_bottom is not None and (top - last_bottom) > 8.0:
            paragraphs.append(_flush_words(current))
            current = []
        current.append(word)
        last_bottom = bottom
    if current:
        paragraphs.append(_flush_words(current))
    return paragraphs


def _flush_words(words: list[dict[str, Any]]) -> dict[str, Any]:
    text = " ".join(str(w.get("text") or "") for w in words).strip()
    x0 = min(float(w.get("x0", 0.0)) for w in words)
    top = min(float(w.get("top", 0.0)) for w in words)
    x1 = max(float(w.get("x1", 0.0)) for w in words)
    bottom = max(float(w.get("bottom", 0.0)) for w in words)
    avg_size = sum(float(w.get("size", 0.0) or 0.0) for w in words) / max(1, len(words))
    return {"text": text, "bbox": (x0, top, x1, bottom), "avg_size": avg_size}


def _looks_like_heading(text: str, para: dict[str, Any]) -> bool:
    if len(text) > 120:
        return False
    if text.isupper() and len(text.split()) <= 12:
        return True
    return float(para.get("avg_size") or 0.0) >= 14.0 and len(text.split()) <= 14


def _serialize_table(rows: list[list[str]]) -> str:
    lines = [" | ".join(row) for row in rows]
    return "\n".join(lines)
