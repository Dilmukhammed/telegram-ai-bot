from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memory.pointers import EvidencePointer, PointerOwnershipError, verify_pointer_ownership
from tools.workspace.store import read_workspace_bytes


@dataclass(frozen=True, slots=True)
class DocumentRegionExcerpt:
    text: str
    workspace_path: str
    page: int
    region_type: str | None
    bbox: list[float] | None
    metadata: dict[str, Any]


def dereference_document_region(
    pointer: EvidencePointer,
    *,
    user_id: int,
    source_user_id: int,
    source_version_id: str,
    segment_text: str | None = None,
) -> DocumentRegionExcerpt:
    """Exact region dereference with ownership check.

    Uses stored segment text when available (preferred provenance). Falls back to
    re-reading the workspace file and returning page-level text for the page.
    """
    if pointer.kind != "document_region":
        raise ValueError(f"unsupported pointer kind for document dereference: {pointer.kind}")
    verify_pointer_ownership(
        pointer,
        user_id=user_id,
        source_version_id=source_version_id,
        source_user_id=source_user_id,
    )
    location = dict(pointer.location)
    workspace_path = str(location["workspace_path"])
    page = int(location["page"])
    region_type = location.get("region_type")
    bbox = location.get("bbox")
    char_start = location.get("char_start")
    char_end = location.get("char_end")

    text = segment_text or ""
    if not text:
        # Fallback: re-open file and extract page text (PDF) or full text (DOCX).
        _path, data, _mime = read_workspace_bytes(user_id, workspace_path)
        text = _extract_page_text(data, page=page, workspace_path=workspace_path)
    if (
        isinstance(char_start, int)
        and isinstance(char_end, int)
        and 0 <= char_start <= char_end <= len(text)
    ):
        text = text[char_start:char_end]

    return DocumentRegionExcerpt(
        text=text,
        workspace_path=workspace_path,
        page=page,
        region_type=str(region_type) if region_type else None,
        bbox=[float(v) for v in bbox] if isinstance(bbox, list) else None,
        metadata={
            "paragraph_index": location.get("paragraph_index"),
            "table_index": location.get("table_index"),
            "row_index": location.get("row_index"),
            "col_index": location.get("col_index"),
            "image_index": location.get("image_index"),
            "coordinate_system": location.get("coordinate_system"),
        },
    )


def _extract_page_text(data: bytes, *, page: int, workspace_path: str) -> str:
    lower = workspace_path.casefold()
    if lower.endswith(".pdf"):
        from memory.documents.pdf import structure_pdf

        structured = structure_pdf(data)
        for region in structured.regions:
            if region.region_type == "page" and region.page == page:
                return region.text
        return ""
    if lower.endswith(".docx"):
        from memory.documents.docx import structure_docx

        structured = structure_docx(data)
        return "\n\n".join(
            region.text
            for region in structured.regions
            if region.region_type in {"paragraph", "heading", "table"} and region.text
        )
    raise ValueError(f"unsupported document type for dereference: {workspace_path}")
