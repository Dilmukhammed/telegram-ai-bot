from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


DOCUMENT_STRUCTURE_VERSION = "1"
DOCUMENT_NORMALIZER_NAME = "document_structure_normalizer"
DOCUMENT_NORMALIZER_VERSION = "1"
STRUCTURE_DOCUMENT_STAGE = "structure_document"

SEGMENT_DOCUMENT_ROOT = "document_root"
SEGMENT_DOCUMENT_PAGE = "document_page"
SEGMENT_DOCUMENT_HEADING = "document_heading"
SEGMENT_DOCUMENT_PARAGRAPH = "document_paragraph"
SEGMENT_DOCUMENT_TABLE = "document_table"
SEGMENT_DOCUMENT_TABLE_CELL = "document_table_cell"
SEGMENT_DOCUMENT_EMBEDDED_IMAGE = "document_embedded_image"

DOCUMENT_SEGMENT_TYPES = frozenset(
    {
        SEGMENT_DOCUMENT_ROOT,
        SEGMENT_DOCUMENT_PAGE,
        SEGMENT_DOCUMENT_HEADING,
        SEGMENT_DOCUMENT_PARAGRAPH,
        SEGMENT_DOCUMENT_TABLE,
        SEGMENT_DOCUMENT_TABLE_CELL,
        SEGMENT_DOCUMENT_EMBEDDED_IMAGE,
    }
)

EXTRACTABLE_DOCUMENT_SEGMENT_TYPES = frozenset(
    {
        SEGMENT_DOCUMENT_PARAGRAPH,
        SEGMENT_DOCUMENT_HEADING,
        SEGMENT_DOCUMENT_TABLE,
        SEGMENT_DOCUMENT_TABLE_CELL,
    }
)


@dataclass(frozen=True, slots=True)
class StructuredRegion:
    region_type: str
    page: int
    text: str
    ordinal: int
    bbox: tuple[float, float, float, float] | None = None
    char_start: int | None = None
    char_end: int | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    col_index: int | None = None
    image_index: int | None = None
    page_width: float | None = None
    page_height: float | None = None
    coordinate_system: str = "pdf_points"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    image_bytes: bytes | None = None
    image_mime: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentStructureResult:
    format: str  # pdf | docx
    title: str | None
    page_count: int
    regions: tuple[StructuredRegion, ...]
    warnings: tuple[str, ...] = ()
