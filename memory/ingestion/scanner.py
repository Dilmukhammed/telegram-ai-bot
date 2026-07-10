from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import TYPE_CHECKING

from memory.ids import canonical_json, make_source_id
from memory.ingestion.builders import (
    UnsupportedRoleError,
    chat_job_request,
    chat_source_input,
    tool_job_request,
    tool_source_input,
)
from memory.ingestion.cursors import (
    STREAM_CHAT_MESSAGES,
    STREAM_TOOL_RECONCILE,
    STREAM_TOOL_RESULTS,
    IngestionCursorStore,
)
from memory.ingestion.failures import IngestionFailureStore
from memory.ingestion.models import ToolCursor
from memory.ingestion.protocols import ChatEvidenceReader, ToolEvidenceReader
from memory.ingestion.telemetry import log_cursor_advanced, log_ingestion_event

if TYPE_CHECKING:
    from memory.config import MemoryConfig
    from memory.service import MemoryService

logger = logging.getLogger(__name__)


class IngestionScanner:
    """Periodic gap-filling scanner."""

    def __init__(
        self,
        *,
        service: "MemoryService",
        config: "MemoryConfig",
        chat_reader: ChatEvidenceReader,
        tool_reader: ToolEvidenceReader,
    ) -> None:
        self._service = service
        self._config = config
        self._chat_reader = chat_reader
        self._tool_reader = tool_reader
        self._cursors = IngestionCursorStore(service.db)
        self._failures = IngestionFailureStore(
            service.db, max_attempts=config.ingest_failure_max_attempts
        )
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._initialize_cursors()
        self._task = asyncio.create_task(self._run_loop(), name="ingestion_scanner")

    async def stop(self, *, grace_seconds: float) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=grace_seconds)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None

    def wake(self) -> None:
        self._wake_event.set()

    async def _initialize_cursors(self) -> None:
        if self._cursors.load(STREAM_CHAT_MESSAGES) is None:
            max_id = await asyncio.to_thread(self._chat_reader.max_message_id)
            self._cursors.initialize(STREAM_CHAT_MESSAGES, {"last_message_id": max_id})
            log_ingestion_event(
                logger,
                "memory_ingest_cursor_initialized",
                stream=STREAM_CHAT_MESSAGES,
                cursor={"last_message_id": max_id},
            )

        if self._cursors.load(STREAM_TOOL_RESULTS) is None:
            head = await asyncio.to_thread(self._tool_reader.scan_head)
            self._cursors.initialize(
                STREAM_TOOL_RESULTS,
                {"created_at": head.created_at, "ref": head.ref},
            )
            log_ingestion_event(
                logger,
                "memory_ingest_cursor_initialized",
                stream=STREAM_TOOL_RESULTS,
                cursor={"created_at": head.created_at, "ref": head.ref},
            )

        if self._cursors.load(STREAM_TOOL_RECONCILE) is None:
            self._cursors.initialize(STREAM_TOOL_RECONCILE, {"last_source_id": ""})

    async def _run_loop(self) -> None:
        interval = self._config.ingest_scan_interval_seconds
        while not self._stop_event.is_set():
            try:
                await self._scan_cycle()
            except Exception:
                logger.exception(
                    "ingestion_scanner_cycle_error",
                    extra={"event": "ingestion_scanner_cycle_error"},
                )
            self._wake_event.clear()
            waiters = [
                asyncio.create_task(self._stop_event.wait()),
                asyncio.create_task(self._wake_event.wait()),
            ]
            try:
                _done, pending = await asyncio.wait(
                    waiters,
                    timeout=interval,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*waiters, return_exceptions=True)
            except asyncio.CancelledError:
                for task in waiters:
                    task.cancel()
                await asyncio.gather(*waiters, return_exceptions=True)
                return

    async def _scan_cycle(self) -> None:
        self._cursors.mark_scan_started(STREAM_CHAT_MESSAGES)
        await self._retry_due_failures(STREAM_CHAT_MESSAGES)
        await self._retry_due_failures(STREAM_TOOL_RESULTS)
        await self._process_chat_batch()
        await self._process_tool_batch()
        await self._process_reconcile_batch()

    async def _retry_due_failures(self, stream: str) -> None:
        due = await asyncio.to_thread(
            lambda: self._failures.load_due(stream, limit=self._config.ingest_scan_batch_size)
        )
        for entry in due:
            item_key: str = entry["item_key"]
            try:
                if stream == STREAM_CHAT_MESSAGES:
                    await self._retry_chat_item(item_key)
                elif stream == STREAM_TOOL_RESULTS:
                    await self._retry_tool_item(item_key)
            except Exception:
                logger.debug(
                    "ingestion_retry_failed",
                    extra={"event": "ingestion_retry_failed", "stream": stream, "item_key": item_key},
                )

    async def _retry_chat_item(self, item_key: str) -> None:
        parts = item_key.split(":", 1)
        if len(parts) != 2:
            return
        try:
            user_id = int(parts[0])
            message_id = int(parts[1])
        except ValueError:
            return
        record = await asyncio.to_thread(
            self._chat_reader.get_message_for_user, message_id, user_id
        )
        if record is None:
            return
        config_hash = self._config_hash()
        source_in = chat_source_input(record)
        job_req = chat_job_request(source_in.content_hash, config_hash=config_hash)
        await asyncio.to_thread(
            lambda: self._service.register_source(source_in, initial_jobs=[job_req])
        )
        await asyncio.to_thread(self._failures.resolve, STREAM_CHAT_MESSAGES, item_key)

    async def _retry_tool_item(self, item_key: str) -> None:
        parts = item_key.split(":", 1)
        if len(parts) != 2:
            return
        try:
            user_id = int(parts[0])
        except ValueError:
            return
        ref = parts[1]
        record = await asyncio.to_thread(
            self._tool_reader.get_by_ref_for_user, ref, user_id
        )
        if record is None:
            return
        config_hash = self._config_hash()
        source_in = tool_source_input(record)
        job_req = tool_job_request(source_in.content_hash, config_hash=config_hash)
        await asyncio.to_thread(
            lambda: self._service.register_source(source_in, initial_jobs=[job_req])
        )
        await asyncio.to_thread(self._failures.resolve, STREAM_TOOL_RESULTS, item_key)

    async def _process_chat_batch(self) -> None:
        cursor_data = self._cursors.load(STREAM_CHAT_MESSAGES)
        if cursor_data is None:
            return
        last_id = int(cursor_data.get("last_message_id", 0))
        batch_size = self._config.ingest_scan_batch_size

        records = await asyncio.to_thread(
            lambda: self._chat_reader.read_messages_after_id(last_id, limit=batch_size)
        )
        if not records:
            return

        config_hash = self._config_hash()
        new_last_id = last_id
        registered = duplicate = failed = seen = 0

        for record in records:
            seen += 1
            item_key = f"{record.user_id}:{record.message_id}"
            try:
                source_in = chat_source_input(record)
                job_req = chat_job_request(source_in.content_hash, config_hash=config_hash)
                result = await asyncio.to_thread(
                    lambda s=source_in, j=job_req: self._service.register_source(
                        s, initial_jobs=[j]
                    )
                )
                if result.version_created:
                    registered += 1
                else:
                    duplicate += 1
                new_last_id = max(new_last_id, record.message_id)
                await asyncio.to_thread(
                    self._failures.resolve, STREAM_CHAT_MESSAGES, item_key
                )
            except UnsupportedRoleError as exc:
                logger.debug(
                    "ingestion_chat_skipped",
                    extra={
                        "event": "ingestion_chat_skipped",
                        "message_id": record.message_id,
                        "reason": str(exc),
                    },
                )
                new_last_id = max(new_last_id, record.message_id)
            except Exception as exc:
                logger.warning(
                    "memory_ingest_failed",
                    extra={"event": "memory_ingest_failed", "message_id": record.message_id},
                    exc_info=True,
                )
                try:
                    existing = await asyncio.to_thread(
                        lambda: self._failures.load_due(STREAM_CHAT_MESSAGES, limit=100)
                    )
                    prior_attempts = next(
                        (e["attempts"] for e in existing if e["item_key"] == item_key), 0
                    )
                    not_before = self._failures.compute_not_before(
                        prior_attempts + 1,
                        base_seconds=self._config.ingest_retry_base_seconds,
                        max_seconds=self._config.ingest_retry_max_seconds,
                    )
                    await asyncio.to_thread(
                        lambda: self._failures.record_failure(
                            STREAM_CHAT_MESSAGES,
                            item_key,
                            {"last_message_id": last_id},
                            user_id=record.user_id,
                            error=exc,
                            not_before=not_before,
                        )
                    )
                    failed += 1
                except Exception:
                    logger.exception("ingestion_failure_persist_error")
                    return
                new_last_id = max(new_last_id, record.message_id)

        new_cursor = {"last_message_id": new_last_id}
        self._cursors.advance(
            STREAM_CHAT_MESSAGES,
            new_cursor,
            records_seen_delta=seen,
            registered_delta=registered,
            duplicate_delta=duplicate,
            failed_delta=failed,
        )
        log_cursor_advanced(
            logger,
            stream=STREAM_CHAT_MESSAGES,
            cursor=new_cursor,
            registered=registered,
            duplicate=duplicate,
            failed=failed,
        )

    async def _process_tool_batch(self) -> None:
        cursor_data = self._cursors.load(STREAM_TOOL_RESULTS)
        if cursor_data is None:
            return
        cursor = ToolCursor(
            created_at=str(cursor_data.get("created_at", "")),
            ref=str(cursor_data.get("ref", "")),
        )
        batch_size = self._config.ingest_scan_batch_size

        records = await asyncio.to_thread(
            lambda: self._tool_reader.read_after(cursor, limit=batch_size)
        )
        if not records:
            return

        config_hash = self._config_hash()
        new_cursor = cursor
        registered = duplicate = failed = seen = 0

        for record in records:
            seen += 1
            item_key = f"{record.user_id}:{record.ref}"
            try:
                source_in = tool_source_input(record)
                job_req = tool_job_request(source_in.content_hash, config_hash=config_hash)
                result = await asyncio.to_thread(
                    lambda s=source_in, j=job_req: self._service.register_source(
                        s, initial_jobs=[j]
                    )
                )
                if result.version_created:
                    registered += 1
                else:
                    duplicate += 1
                new_cursor = ToolCursor(
                    created_at=record.created_at.isoformat(),
                    ref=record.ref,
                )
                await asyncio.to_thread(
                    self._failures.resolve, STREAM_TOOL_RESULTS, item_key
                )
            except Exception as exc:
                logger.warning(
                    "memory_ingest_failed",
                    extra={"event": "memory_ingest_failed", "ref": record.ref},
                    exc_info=True,
                )
                try:
                    existing = await asyncio.to_thread(
                        lambda: self._failures.load_due(STREAM_TOOL_RESULTS, limit=100)
                    )
                    prior_attempts = next(
                        (e["attempts"] for e in existing if e["item_key"] == item_key), 0
                    )
                    not_before = self._failures.compute_not_before(
                        prior_attempts + 1,
                        base_seconds=self._config.ingest_retry_base_seconds,
                        max_seconds=self._config.ingest_retry_max_seconds,
                    )
                    await asyncio.to_thread(
                        lambda: self._failures.record_failure(
                            STREAM_TOOL_RESULTS,
                            item_key,
                            {"created_at": cursor.created_at, "ref": cursor.ref},
                            user_id=record.user_id,
                            error=exc,
                            not_before=not_before,
                        )
                    )
                    failed += 1
                except Exception:
                    logger.exception("ingestion_failure_persist_error")
                    return
                new_cursor = ToolCursor(
                    created_at=record.created_at.isoformat(),
                    ref=record.ref,
                )

        new_cursor_json = {"created_at": new_cursor.created_at, "ref": new_cursor.ref}
        self._cursors.advance(
            STREAM_TOOL_RESULTS,
            new_cursor_json,
            records_seen_delta=seen,
            registered_delta=registered,
            duplicate_delta=duplicate,
            failed_delta=failed,
        )
        log_cursor_advanced(
            logger,
            stream=STREAM_TOOL_RESULTS,
            cursor=new_cursor_json,
            registered=registered,
            duplicate=duplicate,
            failed=failed,
        )

    async def _process_reconcile_batch(self) -> None:
        cursor_data = self._cursors.load(STREAM_TOOL_RECONCILE)
        if cursor_data is None:
            return
        last_source_id = str(cursor_data.get("last_source_id", ""))
        batch_size = self._config.tool_reconcile_batch_size

        sources = await asyncio.to_thread(
            lambda: self._service.sources.list_active_tool_result_after(
                last_source_id, limit=batch_size
            )
        )

        if not sources:
            self._cursors.advance(STREAM_TOOL_RECONCILE, {"last_source_id": ""}, scan_completed=True)
            return

        items = [(s.user_id, _extract_tr_ref(s.source_ref)) for s in sources]
        existing = await asyncio.to_thread(self._tool_reader.existing_refs, items)

        for source in sources:
            tr_ref = _extract_tr_ref(source.source_ref)
            if (source.user_id, tr_ref) not in existing:
                try:
                    await asyncio.to_thread(
                        lambda sid=source.source_id, uid=source.user_id: self._service.sources.invalidate(
                            sid,
                            user_id=uid,
                            reason="canonical_tool_payload_missing",
                        )
                    )
                    log_ingestion_event(
                        logger,
                        "memory_tool_source_invalidated",
                        user_id=source.user_id,
                        source_id=source.source_id,
                    )
                except Exception:
                    logger.exception(
                        "ingestion_reconcile_invalidation_error",
                        extra={
                            "event": "ingestion_reconcile_invalidation_error",
                            "source_id": source.source_id,
                        },
                    )

        new_last_source_id = sources[-1].source_id
        sweep_done = len(sources) < batch_size
        self._cursors.advance(
            STREAM_TOOL_RECONCILE,
            {"last_source_id": new_last_source_id},
            scan_completed=sweep_done,
        )

    def _config_hash(self) -> str:
        payload = canonical_json({
            "chunk_size": self._config.text_segment_chars,
            "overlap": self._config.text_segment_overlap,
            "normalizer_version": "1",
        })
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _extract_tr_ref(source_ref: str) -> str:
    parts = source_ref.split(":", 2)
    return parts[2] if len(parts) == 3 else source_ref
