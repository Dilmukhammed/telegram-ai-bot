from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memory.resolution.jobs import resolution_job_request

if TYPE_CHECKING:
    from memory.service import MemoryService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolutionScanResult:
    candidates_seen: int
    jobs_created: int


class ResolutionScheduler:
    """Bounded idempotent scheduler for ready PR4 candidates."""

    def __init__(
        self,
        *,
        service: "MemoryService",
        required_verification_policy: str,
        interval_seconds: float,
        batch_size: int,
        support_profile: str = "extraction",
        adversarial_profile: str = "agent",
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("resolution interval_seconds must be > 0")
        if batch_size < 1:
            raise ValueError("resolution batch_size must be >= 1")
        self._service = service
        self._required_verification_policy = required_verification_policy
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._support_profile = support_profile
        self._adversarial_profile = adversarial_profile
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
        self._task = asyncio.create_task(self._run(), name="memory-resolution-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            await self._task
            self._task = None

    def wake(self) -> None:
        self._wake.set()

    def scan_once(self) -> ResolutionScanResult:
        cfg = self._service.config
        rows = self._service.resolution.list_schedulable(
            required_verification_policy=self._required_verification_policy,
            limit=self._batch_size,
        )
        created = 0
        for row in rows:
            candidate_id = str(row["candidate_id"])
            result = self._service.jobs.enqueue(
                int(row["user_id"]),
                str(row["source_version_id"]),
                resolution_job_request(
                    candidate_id,
                    score_id=str(row["score_id"]),
                    verdict_set_hash=str(row["verdict_set_hash"]),
                    required_verification_policy=self._required_verification_policy,
                    support_profile=self._support_profile,
                    adversarial_profile=self._adversarial_profile,
                    candidate_generation_enabled=cfg.resolution_candidate_generation_enabled,
                    fuzzy_blocking_enabled=cfg.resolution_fuzzy_blocking_enabled,
                    fuzzy_min_trigram=cfg.resolution_fuzzy_min_trigram,
                    cross_language_enabled=cfg.resolution_cross_language_enabled,
                    cluster_critic_enabled=cfg.resolution_cluster_critic_enabled,
                    merge_events_enabled=cfg.resolution_merge_events_enabled,
                    max_candidates=cfg.resolution_max_candidates,
                ),
            )
            if result.created:
                created += 1
        return ResolutionScanResult(candidates_seen=len(rows), jobs_created=created)

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.scan_once()
                if result.jobs_created:
                    logger.info(
                        "resolution scan created %s jobs from %s candidates",
                        result.jobs_created,
                        result.candidates_seen,
                    )
                    self._service.wake_worker()
            except Exception:
                logger.exception("resolution scan failed")
            try:
                await asyncio.wait_for(
                    self._wake.wait(),
                    timeout=self._interval_seconds,
                )
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
