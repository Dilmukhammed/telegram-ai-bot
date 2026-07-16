from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping

from memory.ids import canonical_json
from memory.models import JobRequest, SourceInput
from memory.pointers import POINTER_VERSION, EvidencePointer
from memory.documents.models import (
    DOCUMENT_NORMALIZER_NAME,
    DOCUMENT_NORMALIZER_VERSION,
    STRUCTURE_DOCUMENT_STAGE,
)


def document_content_hash(
    *,
    workspace_path: str,
    sha256: str,
    mime_type: str | None,
    filename: str | None,
) -> str:
    payload = {
        "workspace_path": workspace_path,
        "sha256": sha256,
        "mime_type": mime_type,
        "filename": filename,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def document_source_input(
    *,
    user_id: int,
    workspace_path: str,
    sha256: str,
    mime_type: str | None,
    filename: str | None,
    size_bytes: int,
    telegram_message_id: int | None = None,
    telegram_chat_id: int | None = None,
    telegram_file_id: str | None = None,
    caption: str | None = None,
    occurred_at: datetime | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> SourceInput:
    content_hash = document_content_hash(
        workspace_path=workspace_path,
        sha256=sha256,
        mime_type=mime_type,
        filename=filename,
    )
    pointer = EvidencePointer(
        pointer_version=POINTER_VERSION,
        kind="workspace_file",
        source_version_id="pending",
        location={"workspace_path": workspace_path},
    )
    metadata: dict[str, Any] = {
        "workspace_path": workspace_path,
        "sha256": sha256,
        "filename": filename,
        "size_bytes": size_bytes,
        "mime_type": mime_type,
    }
    if telegram_message_id is not None:
        metadata["telegram_message_id"] = telegram_message_id
    if telegram_chat_id is not None:
        metadata["telegram_chat_id"] = telegram_chat_id
    if telegram_file_id is not None:
        metadata["telegram_file_id"] = telegram_file_id
    if caption:
        metadata["caption"] = caption
    if extra_metadata:
        metadata.update(dict(extra_metadata))
    return SourceInput(
        user_id=user_id,
        source_type="document",
        source_ref=f"workspace_file:{workspace_path}",
        authority_class="user_supplied_document",
        content_hash=content_hash,
        pointer=pointer,
        mime_type=mime_type,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        source_metadata=metadata,
        version_metadata={
            "sha256": sha256,
            "workspace_path": workspace_path,
            "filename": filename,
        },
    )


def document_structure_job_request(*, content_hash: str) -> JobRequest:
    return JobRequest(
        stage=STRUCTURE_DOCUMENT_STAGE,
        processor_name=DOCUMENT_NORMALIZER_NAME,
        processor_version=DOCUMENT_NORMALIZER_VERSION,
        prompt_version=None,
        model_profile=None,
        input_hash=content_hash,
        config_hash="document_structure_v1",
        priority=20,
    )


def photo_child_source_input(
    *,
    user_id: int,
    workspace_path: str,
    sha256: str,
    mime_type: str | None,
    parent_source_ref: str,
    page: int,
    image_index: int,
) -> SourceInput:
    content_hash = document_content_hash(
        workspace_path=workspace_path,
        sha256=sha256,
        mime_type=mime_type,
        filename=workspace_path.rsplit("/", 1)[-1],
    )
    return SourceInput(
        user_id=user_id,
        source_type="photo",
        source_ref=f"workspace_file:{workspace_path}",
        authority_class="user_supplied_document",
        content_hash=content_hash,
        pointer=EvidencePointer(
            pointer_version=POINTER_VERSION,
            kind="workspace_file",
            source_version_id="pending",
            location={"workspace_path": workspace_path},
        ),
        mime_type=mime_type,
        occurred_at=datetime.now(timezone.utc),
        source_metadata={
            "workspace_path": workspace_path,
            "sha256": sha256,
            "parent_document_ref": parent_source_ref,
            "page": page,
            "image_index": image_index,
            "embedded_from_document": True,
        },
        version_metadata={
            "sha256": sha256,
            "workspace_path": workspace_path,
            "embedded_from_document": True,
        },
    )
