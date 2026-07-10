from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from memory.ingestion.models import ToolCursor, ToolEvidenceRecord
from tools.tool_results.store import StoredToolResult

if TYPE_CHECKING:
    from memory.ingestion.protocols import TextIngestSink
    from tools.tool_results.store import ToolResultStore

logger = logging.getLogger(__name__)


def stored_to_evidence(record: StoredToolResult) -> ToolEvidenceRecord:
    return ToolEvidenceRecord(
        ref=record.ref,
        display_ref=record.display_ref,
        user_id=record.user_id,
        run_id=record.run_id,
        tool_name=record.tool_name,
        turn=record.turn,
        payload_kind=record.payload_kind,
        payload_json=record.payload_json,
        args_json=record.args_json,
        ok=record.ok,
        cached=record.cached,
        created_at=record.created_at,
        expires_at=record.expires_at,
    )


class ToolEvidenceAdapter:
    def __init__(self, store: ToolResultStore) -> None:
        self._store = store

    def scan_head(self) -> ToolCursor:
        return self._store.scan_head()

    def read_after(self, cursor: ToolCursor, *, limit: int) -> Sequence[ToolEvidenceRecord]:
        records = self._store.read_after(cursor, limit=limit)
        return [stored_to_evidence(record) for record in records]

    def get_by_ref_for_user(self, ref: str, user_id: int) -> ToolEvidenceRecord | None:
        record = self._store.get_by_ref_for_user(ref, user_id=user_id)
        if record is None:
            return None
        return stored_to_evidence(record)

    def existing_refs(self, items: Sequence[tuple[int, str]]) -> set[tuple[int, str]]:
        return self._store.existing_refs(items)


class ToolMemoryLifecycleObserver:
    def __init__(self, sink: TextIngestSink) -> None:
        self._sink = sink

    def inserted(self, *, user_id: int, ref: str) -> None:
        try:
            self._sink.notify_tool_inserted(user_id=user_id, ref=ref)
        except Exception:
            logger.exception(
                "memory_tool_ingest_insert_notify_failed",
                extra={"event": "memory_tool_ingest_insert_notify_failed", "user_id": user_id},
            )

    def deleted(self, *, user_id: int, ref: str, reason: str) -> None:
        try:
            self._sink.notify_tool_deleted(user_id=user_id, ref=ref)
        except Exception:
            logger.exception(
                "memory_tool_ingest_delete_notify_failed",
                extra={"event": "memory_tool_ingest_delete_notify_failed", "user_id": user_id},
            )
