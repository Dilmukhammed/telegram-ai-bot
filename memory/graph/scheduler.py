from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memory.graph.materializer import GraphMaterializer

if TYPE_CHECKING:
    from memory.service import MemoryService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GraphScanResult:
    events_seen: int
    processed: int
    failed: int


class GraphOutboxScheduler:
    """Drain graph_outbox and apply deterministic materialization."""

    def __init__(
        self,
        *,
        service: "MemoryService",
        interval_seconds: float,
        batch_size: int,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("graph interval_seconds must be > 0")
        if batch_size < 1:
            raise ValueError("graph batch_size must be >= 1")
        self._service = service
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._materializer = GraphMaterializer(
            service.db,
            store=service.graph,
            outbox=service.graph_outbox,
            summary_invalidator=getattr(service, "summary_invalidator", None),
            attachment_invalidator=getattr(service, "attachment_invalidator", None),
        )

    @property
    def started(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.started:
            return
        self._stop.clear()
        self._wake.set()
        self._task = asyncio.create_task(self._run(), name="memory-graph-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            await self._task
            self._task = None

    def wake(self) -> None:
        self._wake.set()

    def scan_once(self) -> GraphScanResult:
        results = self._materializer.drain_once(limit=self._batch_size)
        failed = sum(1 for item in results if item.reason and item.skipped and item.edge_id is None and "Error" in (item.reason or ""))
        # Count mark_failed via reason containing exception text is fragile;
        # treat skipped with reason that is not intentional skip labels as failed.
        intentional = {
            "expired",
            "nothing_to_expire",
            "missing_head",
            "insufficient_endpoints",
            "unresolved_endpoint",
        }
        failed = sum(
            1
            for item in results
            if item.skipped and item.reason and item.reason not in intentional
        )
        return GraphScanResult(
            events_seen=len(results),
            processed=len(results) - failed,
            failed=failed,
        )

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.scan_once()
                if result.events_seen:
                    logger.info(
                        "graph outbox drained events=%s processed=%s failed=%s",
                        result.events_seen,
                        result.processed,
                        result.failed,
                    )
            except Exception:
                logger.exception("graph outbox scan failed")
            try:
                await asyncio.wait_for(
                    self._wake.wait(),
                    timeout=self._interval_seconds,
                )
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
