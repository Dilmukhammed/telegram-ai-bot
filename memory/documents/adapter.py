from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from memory.documents.registration import (
    bytes_sha256,
    document_source_input,
    document_structure_job_request,
)
from tools.workspace.inbound import SavedInboundFile

if TYPE_CHECKING:
    from memory.service import MemoryService

logger = logging.getLogger(__name__)


def register_saved_document(
    service: "MemoryService",
    *,
    user_id: int,
    saved: SavedInboundFile,
    telegram_message_id: int | None = None,
    telegram_chat_id: int | None = None,
    telegram_file_id: str | None = None,
    caption: str | None = None,
    occurred_at: datetime | None = None,
):
    """Register a durable document source + structure job after workspace save."""
    from tools.workspace.store import read_workspace_bytes

    _path, data, mime = read_workspace_bytes(user_id, saved.path)
    sha256 = bytes_sha256(data)
    source = document_source_input(
        user_id=user_id,
        workspace_path=saved.path,
        sha256=sha256,
        mime_type=saved.mime_type or mime,
        filename=saved.filename,
        size_bytes=saved.size_bytes,
        telegram_message_id=telegram_message_id,
        telegram_chat_id=telegram_chat_id,
        telegram_file_id=telegram_file_id,
        caption=caption,
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )
    job = document_structure_job_request(content_hash=source.content_hash)
    result = service.register_source(source, initial_jobs=(job,))
    logger.info(
        "memory_document_registered user_id=%s path=%s source_version=%s",
        user_id,
        saved.path,
        result.source_version_id,
    )
    return result
