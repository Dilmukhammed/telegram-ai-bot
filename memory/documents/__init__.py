from __future__ import annotations

from memory.documents.adapter import register_saved_document
from memory.documents.dereference import DocumentRegionExcerpt, dereference_document_region
from memory.documents.models import (
    DOCUMENT_SEGMENT_TYPES,
    EXTRACTABLE_DOCUMENT_SEGMENT_TYPES,
    STRUCTURE_DOCUMENT_STAGE,
)
from memory.documents.normalizer import (
    register_document_structure_normalizer,
    structure_document_bytes,
)
from memory.documents.registration import document_source_input

__all__ = [
    "DOCUMENT_SEGMENT_TYPES",
    "EXTRACTABLE_DOCUMENT_SEGMENT_TYPES",
    "STRUCTURE_DOCUMENT_STAGE",
    "DocumentRegionExcerpt",
    "dereference_document_region",
    "document_source_input",
    "register_document_structure_normalizer",
    "register_saved_document",
    "structure_document_bytes",
]
