from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memory.summaries.dirty import SummaryDirtyStore
from memory.summaries.eligibility import eligible_for_summary_type
from memory.summaries.generation.generator import summary_input_hash
from memory.summaries.jobs import summary_job_request
from memory.summaries.loaders import load_belief_snapshots
from memory.summaries.maintenance_source import ensure_maintenance_source_version
from memory.summaries.schemas import SUMMARY_TYPE_COMMUNITY, summary_config_from_memory_config

if TYPE_CHECKING:
    from memory.service import MemoryService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SummaryScanResult:
    dirty_seen: int
    jobs_created: int


class SummaryDirtyScheduler:
    """Claims debounced dirty rows and enqueues summary_generate jobs."""

    def __init__(
        self,
        *,
        service: "MemoryService",
        dirty: SummaryDirtyStore | None = None,
    ) -> None:
        self._service = service
        self._dirty = dirty or SummaryDirtyStore(service.db)
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
        self._task = asyncio.create_task(self._run(), name="memory-summary-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            await self._task
            self._task = None

    def wake(self) -> None:
        self._wake.set()

    def scan_once(self) -> SummaryScanResult:
        cfg = summary_config_from_memory_config(self._service.config)
        if not cfg.summaries_enabled or not cfg.generation_enabled:
            return SummaryScanResult(dirty_seen=0, jobs_created=0)
        rows = self._dirty.claim(limit=cfg.scan_batch_size)
        created = 0
        for row in rows:
            try:
                source_version_id = ensure_maintenance_source_version(
                    self._service,
                    user_id=row.user_id,
                )
                with self._service.db.connection() as conn:
                    beliefs = load_belief_snapshots(conn, user_id=row.user_id)
                    member_ids = None
                    if row.summary_type == SUMMARY_TYPE_COMMUNITY:
                        import json

                        comm = conn.execute(
                            """
                            SELECT member_belief_ids_json
                            FROM graph_communities
                            WHERE community_id = ? AND user_id = ?
                            """,
                            (row.target_id, row.user_id),
                        ).fetchone()
                        if comm is None:
                            self._dirty.clear(row.dirty_id)
                            continue
                        member_ids = frozenset(
                            str(x)
                            for x in json.loads(comm["member_belief_ids_json"] or "[]")
                        )
                eligible = eligible_for_summary_type(
                    beliefs,
                    summary_type=row.summary_type,
                    target_id=row.target_id,
                    member_belief_ids=member_ids,
                )
                if not eligible and row.summary_type != SUMMARY_TYPE_COMMUNITY:
                    self._dirty.clear(row.dirty_id)
                    continue
                belief_hash = summary_input_hash(
                    user_id=row.user_id,
                    summary_type=row.summary_type,
                    target_id=row.target_id,
                    beliefs=eligible,
                )
                result = self._service.jobs.enqueue(
                    row.user_id,
                    source_version_id,
                    summary_job_request(
                        user_id=row.user_id,
                        summary_type=row.summary_type,
                        target_id=row.target_id,
                        input_hash=belief_hash,
                        generation_enabled=cfg.generation_enabled,
                        verify_enabled=cfg.verify_enabled,
                        model_profile=cfg.model_profile,
                        verify_model_profile=cfg.verify_model_profile,
                    ),
                )
                self._dirty.clear(row.dirty_id)
                if result.created:
                    created += 1
            except Exception:
                logger.exception(
                    "summary dirty claim failed dirty_id=%s", row.dirty_id
                )
        return SummaryScanResult(dirty_seen=len(rows), jobs_created=created)

    async def _run(self) -> None:
        cfg = summary_config_from_memory_config(self._service.config)
        interval = cfg.scan_interval_seconds
        while not self._stop.is_set():
            try:
                result = self.scan_once()
                if result.jobs_created:
                    logger.info(
                        "summary scan created %s jobs from %s dirty rows",
                        result.jobs_created,
                        result.dirty_seen,
                    )
                    self._service.wake_worker()
            except Exception:
                logger.exception("summary scan failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
