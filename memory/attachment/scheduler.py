from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memory.attachment.dirty import AttachmentDirtyStore
from memory.attachment.jobs import attach_job_request
from memory.attachment.maintenance_source import ensure_attachment_maintenance_source_version
from memory.attachment.schemas import attachment_config_from_memory_config

if TYPE_CHECKING:
    from memory.service import MemoryService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AttachmentScanResult:
    dirty_seen: int
    jobs_created: int


class AttachmentDirtyScheduler:
    """Claims debounced dirty rows and enqueues attach_analyze jobs."""

    def __init__(
        self,
        *,
        service: "MemoryService",
        dirty: AttachmentDirtyStore | None = None,
    ) -> None:
        self._service = service
        self._dirty = dirty or AttachmentDirtyStore(service.db)
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def started(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.started:
            return
        self._stop.clear()
        self._wake.set()
        self._task = asyncio.create_task(self._run(), name="memory-attachment-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            await self._task
            self._task = None

    def wake(self) -> None:
        self._wake.set()

    def scan_once(self) -> AttachmentScanResult:
        cfg = attachment_config_from_memory_config(self._service.config)
        if not cfg.enabled or not cfg.generation_enabled:
            return AttachmentScanResult(dirty_seen=0, jobs_created=0)
        rows = self._dirty.claim(limit=cfg.scan_batch_size)
        created = 0
        for row in rows:
            try:
                source_version_id = ensure_attachment_maintenance_source_version(
                    self._service,
                    user_id=row.user_id,
                )
                result = self._service.jobs.enqueue(
                    row.user_id,
                    source_version_id,
                    attach_job_request(
                        user_id=row.user_id,
                        belief_id=row.belief_id,
                        generation_enabled=cfg.generation_enabled,
                        verify_enabled=cfg.verify_enabled,
                        model_profile=cfg.model_profile,
                        react_enabled=cfg.react_enabled,
                        react_mode=cfg.react_mode,
                        react_model_profile=cfg.react_model_profile,
                    ),
                )
                self._dirty.clear(row.dirty_id)
                if result.created:
                    created += 1
            except Exception:
                logger.exception(
                    "attachment dirty claim failed dirty_id=%s", row.dirty_id
                )
        return AttachmentScanResult(dirty_seen=len(rows), jobs_created=created)

    async def _run(self) -> None:
        cfg = attachment_config_from_memory_config(self._service.config)
        interval = cfg.scan_interval_seconds
        while not self._stop.is_set():
            try:
                result = self.scan_once()
                if result.jobs_created:
                    logger.info(
                        "attachment scan created %s jobs from %s dirty rows",
                        result.jobs_created,
                        result.dirty_seen,
                    )
                    self._service.wake_worker()
            except Exception:
                logger.exception("attachment scan failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
