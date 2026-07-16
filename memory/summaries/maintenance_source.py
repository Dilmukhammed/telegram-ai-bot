from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from memory.models import SourceInput
from memory.pointers import EvidencePointer

if TYPE_CHECKING:
    from memory.service import MemoryService

MAINTENANCE_SOURCE_TYPE = "memory_maintenance"
MAINTENANCE_AUTHORITY = "system_maintenance"


def maintenance_source_ref(*, user_id: int) -> str:
    return f"user:{user_id}:summaries"


def ensure_maintenance_source_version(
    service: "MemoryService",
    *,
    user_id: int,
) -> str:
    source_ref = maintenance_source_ref(user_id=user_id)
    with service.db.connection() as conn:
        row = conn.execute(
            """
            SELECT v.source_version_id
            FROM memory_sources s
            JOIN memory_source_versions v ON v.source_id = s.source_id
            WHERE s.user_id = ? AND s.source_type = ? AND s.source_ref = ?
              AND s.status = 'active' AND v.status = 'active'
            ORDER BY v.ingested_at DESC
            LIMIT 1
            """,
            (user_id, MAINTENANCE_SOURCE_TYPE, source_ref),
        ).fetchone()
        if row is not None:
            return str(row["source_version_id"])
    now = datetime.now(timezone.utc)
    pointer = EvidencePointer(
        pointer_version=1,
        kind="workspace_file",
        source_version_id="pending",
        location={"workspace_path": f".memory/maintenance/{user_id}/summaries"},
    )
    result = service.register_source(
        SourceInput(
            user_id=user_id,
            source_type=MAINTENANCE_SOURCE_TYPE,
            source_ref=source_ref,
            authority_class=MAINTENANCE_AUTHORITY,
            content_hash=f"summaries-maintenance:{user_id}",
            occurred_at=now,
            pointer=pointer,
        )
    )
    return result.source_version_id
