from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from memory.ids import canonical_json, make_source_id
from memory.ingestion.builders import (
    UnsupportedRoleError,
    chat_job_request,
    chat_source_input,
    tool_job_request,
    tool_source_input,
)
from memory.ingestion.failures import IngestionFailureStore
from memory.ingestion.models import QueueEvent, QueueEventKind
from memory.ingestion.protocols import ChatEvidenceReader, ToolEvidenceReader
from memory.ingestion.telemetry import log_ingestion_event, log_ingestion_skipped

if TYPE_CHECKING:
    from memory.config import MemoryConfig
    from memory.service import MemoryService

logger = logging.getLogger(__name__)

_STREAM_CHAT = "chat_messages"
_STREAM_TOOL = "tool_results"


class IngestionDispatcher:
    """Bounded asyncio.Queue dispatcher implementing TextIngestSink."""

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
        self._queue: asyncio.Queue[QueueEvent] = asyncio.Queue(
            maxsize=config.ingest_queue_maxsize
        )
        self._seen: set[tuple[str, str]] = set()
        self._enabled = True
        self._wake_scanner: Callable[[], None] | None = None
        self._failures = IngestionFailureStore(
            service.db, max_attempts=config.ingest_failure_max_attempts
        )
        self._task: asyncio.Task | None = None

    def set_wake_scanner(self, callback: Callable[[], None] | None) -> None:
        self._wake_scanner = callback

    def notify_chat_messages(self, *, user_id: int, message_ids: Sequence[int]) -> bool:
        if not self._enabled:
            return False
        ok = True
        for mid in message_ids:
            event = QueueEvent(
                stream=_STREAM_CHAT,
                item_key=f"{user_id}:{mid}",
                user_id=user_id,
                event_kind=QueueEventKind.CHAT_MESSAGES,
            )
            if not self._put(event):
                ok = False
        return ok

    def notify_tool_inserted(self, *, user_id: int, ref: str) -> bool:
        if not self._enabled:
            return False
        event = QueueEvent(
            stream=_STREAM_TOOL,
            item_key=f"{user_id}:{ref}",
            user_id=user_id,
            event_kind=QueueEventKind.TOOL_INSERTED,
        )
        return self._put(event)

    def notify_tool_deleted(self, *, user_id: int, ref: str) -> bool:
        if not self._enabled:
            return False
        event = QueueEvent(
            stream=_STREAM_TOOL,
            item_key=f"del:{user_id}:{ref}",
            user_id=user_id,
            event_kind=QueueEventKind.TOOL_DELETED,
        )
        return self._put(event)

    def wake_scanner(self) -> None:
        if self._wake_scanner is not None:
            self._wake_scanner()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_worker(), name="ingestion_dispatcher")

    def disable(self) -> None:
        self._enabled = False

    async def stop(self, *, grace_seconds: float = 5.0) -> None:
        self._enabled = False
        if self._task is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=grace_seconds)
            except asyncio.TimeoutError:
                pass
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def _put(self, event: QueueEvent) -> bool:
        key = (event.stream, event.item_key)
        if key in self._seen:
            return True
        try:
            self._queue.put_nowait(event)
            self._seen.add(key)
            return True
        except asyncio.QueueFull:
            log_ingestion_event(
                logger,
                "memory_ingest_queue_full",
                level=30,
                stream=event.stream,
            )
            return False

    async def _run_worker(self) -> None:
        while True:
            try:
                event = await self._queue.get()
            except asyncio.CancelledError:
                return
            key = (event.stream, event.item_key)
            try:
                await self._handle_event(event)
            except Exception:
                logger.exception(
                    "ingestion_dispatcher_unhandled",
                    extra={
                        "event": "ingestion_dispatcher_unhandled",
                        "stream": event.stream,
                        "item_key": event.item_key,
                    },
                )
            finally:
                self._seen.discard(key)
                self._queue.task_done()

    async def _handle_event(self, event: QueueEvent) -> None:
        config_hash = self._config_hash()
        if event.event_kind == QueueEventKind.CHAT_MESSAGES:
            await self._handle_chat(event, config_hash)
        elif event.event_kind == QueueEventKind.TOOL_INSERTED:
            await self._handle_tool_inserted(event, config_hash)
        elif event.event_kind == QueueEventKind.TOOL_DELETED:
            await self._handle_tool_deleted(event)

    async def _handle_chat(self, event: QueueEvent, config_hash: str) -> None:
        parts = event.item_key.split(":", 1)
        if len(parts) != 2:
            return
        try:
            message_id = int(parts[1])
        except ValueError:
            return
        try:
            record = await asyncio.to_thread(
                self._chat_reader.get_message_for_user, message_id, event.user_id
            )
            if record is None:
                return
            source_in = chat_source_input(record)
            job_req = chat_job_request(source_in.content_hash, config_hash=config_hash)
            result = await asyncio.to_thread(
                lambda: self._service.register_source(source_in, initial_jobs=[job_req])
            )
            await asyncio.to_thread(self._failures.resolve, event.stream, event.item_key)
            log_ingestion_event(
                logger,
                "memory_ingest_registered",
                user_id=event.user_id,
                source_id=result.source_id,
                version_created=result.version_created,
            )
        except UnsupportedRoleError as exc:
            log_ingestion_skipped(
                logger, stream=event.stream, item_key=event.item_key, reason=str(exc)
            )
        except Exception as exc:
            self._record_failure(event, exc)
            raise

    async def _handle_tool_inserted(self, event: QueueEvent, config_hash: str) -> None:
        parts = event.item_key.split(":", 1)
        if len(parts) != 2:
            return
        ref = parts[1]
        try:
            record = await asyncio.to_thread(
                self._tool_reader.get_by_ref_for_user, ref, event.user_id
            )
            if record is None:
                return
            source_in = tool_source_input(record)
            job_req = tool_job_request(source_in.content_hash, config_hash=config_hash)
            result = await asyncio.to_thread(
                lambda: self._service.register_source(source_in, initial_jobs=[job_req])
            )
            await asyncio.to_thread(self._failures.resolve, event.stream, event.item_key)
            log_ingestion_event(
                logger,
                "memory_ingest_registered",
                user_id=event.user_id,
                ref=ref,
                source_id=result.source_id,
                version_created=result.version_created,
            )
        except Exception as exc:
            self._record_failure(event, exc)
            raise

    async def _handle_tool_deleted(self, event: QueueEvent) -> None:
        parts = event.item_key.split(":", 2)
        if len(parts) != 3:
            return
        ref = parts[2]
        source_ref = f"tool_result_ref:{event.user_id}:{ref}"
        source_id = make_source_id(
            user_id=event.user_id,
            source_type="tool_result",
            source_ref=source_ref,
        )
        try:
            source = await asyncio.to_thread(
                lambda: self._service.sources.get_source(source_id, user_id=event.user_id)
            )
            if source is None:
                return
            await asyncio.to_thread(
                lambda: self._service.sources.invalidate(
                    source_id,
                    user_id=event.user_id,
                    reason="tool_result_deleted",
                )
            )
            await asyncio.to_thread(self._failures.resolve, event.stream, event.item_key)
            log_ingestion_event(
                logger,
                "memory_tool_source_invalidated",
                user_id=event.user_id,
                ref=ref,
                source_id=source_id,
            )
        except Exception as exc:
            self._record_failure(event, exc)
            raise

    def _record_failure(self, event: QueueEvent, exc: Exception) -> None:
        try:
            not_before = self._failures.compute_not_before(
                1,
                base_seconds=self._config.ingest_retry_base_seconds,
                max_seconds=self._config.ingest_retry_max_seconds,
            )
            self._failures.record_failure(
                event.stream,
                event.item_key,
                {"stream": event.stream, "item_key": event.item_key},
                user_id=event.user_id,
                error=exc,
                not_before=not_before,
            )
        except Exception:
            logger.exception("ingestion_failure_persist_error")

    def _config_hash(self) -> str:
        payload = canonical_json({
            "chunk_size": self._config.text_segment_chars,
            "overlap": self._config.text_segment_overlap,
            "normalizer_version": "1",
        })
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def maxsize(self) -> int:
        return self._queue.maxsize
