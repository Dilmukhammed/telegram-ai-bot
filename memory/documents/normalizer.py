from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from memory.documents.docx import structure_docx
from memory.documents.models import (
    DOCUMENT_NORMALIZER_NAME,
    DOCUMENT_NORMALIZER_VERSION,
    DOCUMENT_STRUCTURE_VERSION,
    SEGMENT_DOCUMENT_EMBEDDED_IMAGE,
    SEGMENT_DOCUMENT_HEADING,
    SEGMENT_DOCUMENT_PAGE,
    SEGMENT_DOCUMENT_PARAGRAPH,
    SEGMENT_DOCUMENT_ROOT,
    SEGMENT_DOCUMENT_TABLE,
    SEGMENT_DOCUMENT_TABLE_CELL,
    STRUCTURE_DOCUMENT_STAGE,
    DocumentStructureResult,
)
from memory.documents.pdf import structure_pdf
from memory.documents.pointers import build_document_region_pointer
from memory.documents.registration import bytes_sha256, photo_child_source_input
from memory.ids import canonical_json, make_segment_id, pointer_hash
from memory.models import ProcessorContext, ProcessorOutput, SegmentInput
from memory.pointers import POINTER_VERSION, EvidencePointer, pointer_to_mapping

if TYPE_CHECKING:
    from memory.config import MemoryConfig
    from memory.service import MemoryService

logger = logging.getLogger(__name__)


def structure_document_bytes(
    data: bytes,
    *,
    workspace_path: str,
    mime_type: str | None = None,
) -> DocumentStructureResult:
    lower = workspace_path.casefold()
    mime = (mime_type or "").casefold()
    if lower.endswith(".pdf") or "pdf" in mime:
        return structure_pdf(data)
    if lower.endswith(".docx") or "wordprocessingml" in mime or "docx" in mime:
        return structure_docx(data)
    raise ValueError(f"unsupported document format for structure: {workspace_path}")


class DocumentStructureNormalizer:
    name = DOCUMENT_NORMALIZER_NAME
    version = DOCUMENT_NORMALIZER_VERSION
    stages = frozenset({STRUCTURE_DOCUMENT_STAGE})

    def __init__(self, *, service: "MemoryService", config: "MemoryConfig") -> None:
        self._service = service
        self._config = config

    async def process(self, context: ProcessorContext) -> ProcessorOutput:
        source = context.source
        source_version = context.source_version
        if source.source_type != "document":
            return ProcessorOutput(
                output_hash=hashlib.sha256(b"skip").hexdigest(),
                output_json={"reason": "not_document", "skipped": True},
            )
        metadata = dict(source.metadata or {})
        workspace_path = str(
            metadata.get("workspace_path")
            or (source_version.metadata or {}).get("workspace_path")
            or ""
        )
        if not workspace_path:
            raise ValueError("document source missing workspace_path")

        from tools.workspace.paths import unique_relative_path
        from tools.workspace.store import read_workspace_bytes, save_bytes

        _path, data, mime = read_workspace_bytes(source.user_id, workspace_path)
        mime_type = source_version.mime_type or mime
        structured = structure_document_bytes(
            data, workspace_path=workspace_path, mime_type=mime_type
        )

        version_id = source_version.source_version_id
        segments: list[SegmentInput] = []

        root_pointer = EvidencePointer(
            pointer_version=POINTER_VERSION,
            kind="workspace_file",
            source_version_id=version_id,
            location={"workspace_path": workspace_path},
        )
        root_text = structured.title or workspace_path.rsplit("/", 1)[-1]
        root_hash = hashlib.sha256(
            f"root|{structured.format}|{root_text}".encode("utf-8")
        ).hexdigest()
        root_segment_id = _segment_id(
            version_id=version_id,
            segment_type=SEGMENT_DOCUMENT_ROOT,
            ordinal=0,
            pointer=root_pointer,
            normalizer_version=self.version,
        )
        segments.append(
            SegmentInput(
                source_version_id=version_id,
                segment_type=SEGMENT_DOCUMENT_ROOT,
                ordinal=0,
                text=root_text,
                pointer=root_pointer,
                normalizer_name=self.name,
                normalizer_version=self.version,
                input_hash=root_hash,
                parent_segment_id=None,
            )
        )

        parent_by_page: dict[int, str] = {}
        for region in structured.regions:
            segment_type = _segment_type_for(region.region_type)
            pointer = build_document_region_pointer(
                source_version_id=version_id,
                workspace_path=workspace_path,
                region=region,
            )
            input_hash = hashlib.sha256(
                canonical_json(
                    {
                        "type": segment_type,
                        "page": region.page,
                        "text": region.text,
                        "ordinal": region.ordinal,
                        "bbox": region.bbox,
                    }
                ).encode("utf-8")
            ).hexdigest()
            segment_id = _segment_id(
                version_id=version_id,
                segment_type=segment_type,
                ordinal=region.ordinal,
                pointer=pointer,
                normalizer_version=self.version,
            )
            if region.region_type == "page":
                parent_id = root_segment_id
                parent_by_page[region.page] = segment_id
            else:
                parent_id = parent_by_page.get(region.page, root_segment_id)

            if region.region_type == "embedded_image" and region.image_bytes:
                rel = unique_relative_path(
                    source.user_id,
                    f"uploads/embedded/{version_id}_p{region.page}_i{region.image_index or 0}.bin",
                )
                saved = save_bytes(
                    source.user_id,
                    relative=rel,
                    data=region.image_bytes,
                    mime_type=region.image_mime or "application/octet-stream",
                )
                child = photo_child_source_input(
                    user_id=source.user_id,
                    workspace_path=str(saved["path"]),
                    sha256=bytes_sha256(region.image_bytes),
                    mime_type=str(saved.get("mime_type") or region.image_mime),
                    parent_source_ref=source.source_ref,
                    page=region.page,
                    image_index=int(region.image_index or 0),
                )
                self._service.register_source(child)

            segments.append(
                SegmentInput(
                    source_version_id=version_id,
                    segment_type=segment_type,
                    ordinal=region.ordinal,
                    text=region.text or None,
                    pointer=pointer,
                    normalizer_name=self.name,
                    normalizer_version=self.version,
                    input_hash=input_hash,
                    parent_segment_id=parent_id,
                )
            )

        # Parents must precede children for FK checks.
        segments.sort(
            key=lambda item: (
                0
                if item.segment_type == SEGMENT_DOCUMENT_ROOT
                else 1
                if item.segment_type == SEGMENT_DOCUMENT_PAGE
                else 2,
                item.ordinal,
            )
        )

        output_hash = hashlib.sha256(
            canonical_json(
                [
                    {
                        "segment_type": s.segment_type,
                        "ordinal": s.ordinal,
                        "input_hash": s.input_hash,
                    }
                    for s in segments
                ]
            ).encode("utf-8")
        ).hexdigest()

        next_jobs = ()
        if self._config.extraction_enabled and any(
            s.segment_type
            in {
                SEGMENT_DOCUMENT_PARAGRAPH,
                SEGMENT_DOCUMENT_HEADING,
                SEGMENT_DOCUMENT_TABLE,
                SEGMENT_DOCUMENT_TABLE_CELL,
            }
            and s.text
            for s in segments
        ):
            from memory.extraction.pipeline import extraction_job_request

            next_jobs = (
                extraction_job_request(
                    output_hash,
                    model_profile=self._config.extraction_model_profile,
                ),
            )

        return ProcessorOutput(
            output_hash=output_hash,
            output_json={
                "structure_version": DOCUMENT_STRUCTURE_VERSION,
                "format": structured.format,
                "page_count": structured.page_count,
                "region_count": len(structured.regions),
                "segment_count": len(segments),
                "warnings": list(structured.warnings),
            },
            new_segments=tuple(segments),
            next_jobs=next_jobs,
        )


def _segment_id(
    *,
    version_id: str,
    segment_type: str,
    ordinal: int,
    pointer: EvidencePointer,
    normalizer_version: str,
) -> str:
    return make_segment_id(
        source_version_id=version_id,
        segment_type=segment_type,
        ordinal=ordinal,
        pointer_payload_hash=pointer_hash(pointer_to_mapping(pointer)),
        normalizer_version=normalizer_version,
    )


def _segment_type_for(region_type: str) -> str:
    mapping = {
        "page": SEGMENT_DOCUMENT_PAGE,
        "heading": SEGMENT_DOCUMENT_HEADING,
        "paragraph": SEGMENT_DOCUMENT_PARAGRAPH,
        "table": SEGMENT_DOCUMENT_TABLE,
        "table_cell": SEGMENT_DOCUMENT_TABLE_CELL,
        "embedded_image": SEGMENT_DOCUMENT_EMBEDDED_IMAGE,
    }
    return mapping.get(region_type, SEGMENT_DOCUMENT_PARAGRAPH)


def register_document_structure_normalizer(
    registry,
    *,
    service: "MemoryService",
    config: "MemoryConfig",
) -> DocumentStructureNormalizer:
    processor = DocumentStructureNormalizer(service=service, config=config)
    registry.register(processor)
    return processor
