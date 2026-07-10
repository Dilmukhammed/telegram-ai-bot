from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from memory.ingestion.dispatcher import IngestionDispatcher
from memory.ingestion.models import IngestionRuntimeStatus, TextIngestionStatus
from memory.ingestion.protocols import ChatEvidenceReader, ToolEvidenceReader
from memory.ingestion.scanner import IngestionScanner

if TYPE_CHECKING:
    from memory.config import MemoryConfig
    from memory.service import MemoryService

logger = logging.getLogger(__name__)


class TextIngestionRuntime:
    """Orchestrates the dispatcher (event-driven) and scanner (periodic).

    Construction is side-effect-free; call ``start()`` to activate.
    Repeated ``start()`` calls are idempotent.

    Shutdown sequence:
    1. Disable the queue (no new events accepted).
    2. Stop the scanner (let it finish current cycle up to grace).
    3. Drain the dispatcher queue (process remaining events up to grace).
    4. Detach lifecycle observers.
    """

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
        self._dispatcher = IngestionDispatcher(
            service=service,
            config=config,
            chat_reader=chat_reader,
            tool_reader=tool_reader,
        )
        self._scanner = IngestionScanner(
            service=service,
            config=config,
            chat_reader=chat_reader,
            tool_reader=tool_reader,
        )
        self._status = TextIngestionStatus.IDLE
        self._lock = asyncio.Lock()
        self._observers: list[ToolResultLifecycleObserver] = []

    @property
    def sink(self) -> IngestionDispatcher:
        return self._dispatcher

    async def start(self) -> None:
        async with self._lock:
            if self._status not in (TextIngestionStatus.IDLE, TextIngestionStatus.STOPPED):
                return
            self._status = TextIngestionStatus.RUNNING
        from memory.processors import register_text_normalizers

        register_text_normalizers(
            self._service.registry,
            chat_reader=self._chat_reader,
            tool_reader=self._tool_reader,
            config=self._config,
        )
        self._dispatcher.set_wake_scanner(self._scanner.wake)
        await self._dispatcher.start()
        await self._scanner.start()
        logger.info(
            "ingestion_runtime_started",
            extra={"event": "ingestion_runtime_started"},
        )

    async def stop(self, *, grace_seconds: float | None = None) -> None:
        async with self._lock:
            if self._status != TextIngestionStatus.RUNNING:
                return
            self._status = TextIngestionStatus.STOPPING

        grace = grace_seconds if grace_seconds is not None else self._config.ingest_shutdown_grace_seconds
        half_grace = grace / 2.0

        self._dispatcher.disable()
        await self._scanner.stop(grace_seconds=half_grace)
        await self._dispatcher.stop(grace_seconds=half_grace)
        self._observers.clear()

        async with self._lock:
            self._status = TextIngestionStatus.STOPPED
        logger.info(
            "ingestion_runtime_stopped",
            extra={"event": "ingestion_runtime_stopped"},
        )

    def wake_scanner(self) -> None:
        self._scanner.wake()

    def status(self) -> IngestionRuntimeStatus:
        return IngestionRuntimeStatus(
            status=self._status,
            queue_size=self._dispatcher.qsize,
            queue_maxsize=self._dispatcher.maxsize,
            streams_seen={},
        )

    def attach_observer(self, observer: "ToolResultLifecycleObserver") -> None:
        self._observers.append(observer)

    def detach_observers(self) -> None:
        self._observers.clear()


# avoid circular import — import here for the type annotation only
from memory.ingestion.protocols import ToolResultLifecycleObserver  # noqa: E402
