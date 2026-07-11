from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memory.verification.jobs import verification_job_request

if TYPE_CHECKING:
    from memory.service import MemoryService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VerificationScanResult:
    candidates_seen: int
    jobs_created: int


class VerificationScheduler:
    """Bounded idempotent scheduler for new and historical PR3 candidates."""

    def __init__(
        self,
        *,
        service: "MemoryService",
        support_profile: str,
        adversarial_profile: str,
        policy_version: str,
        interval_seconds: float,
        batch_size: int,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("verification interval_seconds must be > 0")
        if batch_size < 1:
            raise ValueError("verification batch_size must be >= 1")
        self._service = service
        self._support_profile = support_profile
        self._adversarial_profile = adversarial_profile
        self._policy_version = policy_version
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
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
        self._task = asyncio.create_task(self._run(), name="memory-verification-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            await self._task
            self._task = None

    def wake(self) -> None:
        self._wake.set()

    def scan_once(self) -> VerificationScanResult:
        rows = self._service.verification.list_schedulable(
            policy_version=self._policy_version,
            limit=self._batch_size,
        )
        created = 0
        for row in rows:
            candidate_id = str(row["candidate_id"])
            result = self._service.jobs.enqueue(
                int(row["user_id"]),
                str(row["source_version_id"]),
                verification_job_request(
                    candidate_id,
                    model_profile=self._support_profile,
                    adversarial_profile=self._adversarial_profile,
                    policy_version=self._policy_version,
                ),
            )
            created += int(result.created)
        return VerificationScanResult(candidates_seen=len(rows), jobs_created=created)

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = await asyncio.to_thread(self.scan_once)
                if result.jobs_created:
                    logger.info(
                        "memory_verification_jobs_scheduled",
                        extra={
                            "event": "memory_verification_jobs_scheduled",
                            "candidates_seen": result.candidates_seen,
                            "jobs_created": result.jobs_created,
                        },
                    )
            except Exception:
                logger.exception("memory verification scheduler scan failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                pass
