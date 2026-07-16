from __future__ import annotations

from typing import Any

from memory.documents.models import StructuredRegion
from memory.pointers import POINTER_VERSION, EvidencePointer


def build_document_region_pointer(
    *,
    source_version_id: str,
    workspace_path: str,
    region: StructuredRegion,
) -> EvidencePointer:
    location: dict[str, Any] = {
        "workspace_path": workspace_path,
        "page": int(region.page),
        "region_type": region.region_type,
        "coordinate_system": region.coordinate_system,
    }
    if region.bbox is not None:
        location["bbox"] = [float(v) for v in region.bbox]
    if region.char_start is not None and region.char_end is not None:
        location["char_start"] = int(region.char_start)
        location["char_end"] = int(region.char_end)
    if region.paragraph_index is not None:
        location["paragraph_index"] = int(region.paragraph_index)
    if region.table_index is not None:
        location["table_index"] = int(region.table_index)
    if region.row_index is not None:
        location["row_index"] = int(region.row_index)
    if region.col_index is not None:
        location["col_index"] = int(region.col_index)
    if region.image_index is not None:
        location["image_index"] = int(region.image_index)
    if region.page_width is not None:
        location["page_width"] = float(region.page_width)
    if region.page_height is not None:
        location["page_height"] = float(region.page_height)
    return EvidencePointer(
        pointer_version=POINTER_VERSION,
        kind="document_region",
        source_version_id=source_version_id,
        location=location,
    )
