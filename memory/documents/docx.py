from __future__ import annotations

import io

from memory.documents.models import DocumentStructureResult, StructuredRegion


def structure_docx(data: bytes) -> DocumentStructureResult:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(io.BytesIO(data))
    regions: list[StructuredRegion] = []
    ordinal = 0
    paragraph_index = 0
    table_index = 0
    page = 1  # DOCX has no native page; synthetic page=1 for pointer contract.

    title = None
    core = getattr(document, "core_properties", None)
    if core is not None and getattr(core, "title", None):
        title = str(core.title).strip() or None

    ordinal += 1
    regions.append(
        StructuredRegion(
            region_type="page",
            page=page,
            text="",
            ordinal=ordinal,
            coordinate_system="docx_flow",
            metadata={"synthetic_page": True},
        )
    )

    for block in document.element.body:
        tag = block.tag.split("}")[-1]
        if tag == "p":
            para = Paragraph(block, document)
            text = (para.text or "").strip()
            if not text:
                continue
            style_name = ""
            try:
                style_name = str(para.style.name or "") if para.style else ""
            except Exception:  # noqa: BLE001
                style_name = ""
            region_type = (
                "heading"
                if style_name.lower().startswith("heading") or _looks_heading(text)
                else "paragraph"
            )
            ordinal += 1
            regions.append(
                StructuredRegion(
                    region_type=region_type,
                    page=page,
                    text=text,
                    ordinal=ordinal,
                    char_start=0,
                    char_end=len(text),
                    paragraph_index=paragraph_index,
                    coordinate_system="docx_flow",
                    metadata={"style": style_name or None},
                )
            )
            paragraph_index += 1
        elif tag == "tbl":
            table = Table(block, document)
            rows: list[list[str]] = []
            for row in table.rows:
                rows.append([(cell.text or "").strip() for cell in row.cells])
            serialized = "\n".join(" | ".join(row) for row in rows)
            ordinal += 1
            regions.append(
                StructuredRegion(
                    region_type="table",
                    page=page,
                    text=serialized,
                    ordinal=ordinal,
                    table_index=table_index,
                    coordinate_system="docx_flow",
                    metadata={"row_count": len(rows)},
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
                            page=page,
                            text=cell,
                            ordinal=ordinal,
                            table_index=table_index,
                            row_index=r_idx,
                            col_index=c_idx,
                            coordinate_system="docx_flow",
                        )
                    )
            table_index += 1

    # Embedded images as placeholders (child source registration happens in normalizer).
    image_index = 0
    for rel in document.part.rels.values():
        if "image" not in str(getattr(rel, "reltype", "")):
            continue
        try:
            blob = rel.target_part.blob
        except Exception:  # noqa: BLE001
            continue
        ordinal += 1
        regions.append(
            StructuredRegion(
                region_type="embedded_image",
                page=page,
                text=f"[embedded image index={image_index}]",
                ordinal=ordinal,
                image_index=image_index,
                coordinate_system="docx_flow",
                image_bytes=blob,
                image_mime="application/octet-stream",
            )
        )
        image_index += 1

    return DocumentStructureResult(
        format="docx",
        title=title,
        page_count=1,
        regions=tuple(regions),
        warnings=(),
    )


def _looks_heading(text: str) -> bool:
    return len(text) <= 80 and (text.isupper() or text.endswith(":"))
