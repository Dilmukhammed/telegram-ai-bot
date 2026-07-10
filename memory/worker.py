from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Collection
from typing import TYPE_CHECKING

from memory.config import MemoryConfig
from memory.models import MemoryJob
from memory.processors import ProcessorRegistry

if TYPE_CHECKING:
    from memory.service import MemoryService

logger = logging.getLogger(__name__)


class MemoryWorker:
    def __init__(
        self,
        *,
        service: "MemoryService",
        config: MemoryConfig,
        registry: ProcessorRegistry,
        stages: Collection[str] | None = None,
    ) -> None:
        self._service = service
        self._config = config
        self._registry = registry
        self._stages = frozenset(stages) if stages is not None else None
        self._worker_id = f"worker-{uuid.uuid4().hex[:12]}"
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._supervisor_task: asyncio.Task[None] | None = None
        self._active_tasks: set[asyncio.Task[None]] = set()
        self._started = False
        self._active_job_count = 0
        self._started_at_monotonic: float | None = None

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def active_job_count(self) -> int:
        return self._active_job_count

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._started_at_monotonic = time.monotonic()
        self._stop.clear()
        self._supervisor_task = asyncio.create_task(self.run_forever(), name="memory-worker")
        logger.info(
            "memory_worker_started",
            extra={
                "event": "memory_worker_started",
                "worker_id": self._worker_id,
                "status": "running",
                "stages": (
                    sorted(self._stages) if self._stages is not None else None
                ),
            },
        )

    async def stop(self, *, grace_seconds: float = 30.0) -> None:
        if not self._started:
            return
        self._stop.set()
        self._wake.set()
        if self._supervisor_task is not None:
            try:
                await asyncio.wait_for(self._supervisor_task, timeout=grace_seconds)
            except asyncio.TimeoutError:
                self._supervisor_task.cancel()
                try:
                    await self._supervisor_task
                except asyncio.CancelledError:
                    pass
        active = set(self._active_tasks)
        if active:
            _done, pending = await asyncio.wait(active, timeout=grace_seconds)
            if pending:
                released = await asyncio.to_thread(
                    self._service.jobs.release_worker_leases,
                    worker_id=self._worker_id,
                    reason="worker shutdown grace expired",
                )
                for task in pending:
                    task.cancel()
                done_after_cancel, still_pending = await asyncio.wait(
                    pending,
                    timeout=max(0.1, min(1.0, grace_seconds)),
                )
                if done_after_cancel:
                    await asyncio.gather(
                        *done_after_cancel,
                        return_exceptions=True,
                    )
                if still_pending:
                    logger.error(
                        "memory worker processors ignored cancellation",
                        extra={
                            "event": "memory_worker_cancellation_timeout",
                            "worker_id": self._worker_id,
                            "released_jobs": released,
                            "active_jobs": len(still_pending),
                            "status": "stopping",
                        },
                    )
        await asyncio.to_thread(
            self._service.jobs.release_worker_leases,
            worker_id=self._worker_id,
            reason="worker stopped",
        )
        self._supervisor_task = None
        self._started = False
        duration_seconds = (
            max(0.0, time.monotonic() - self._started_at_monotonic)
            if self._started_at_monotonic is not None
            else None
        )
        self._started_at_monotonic = None
        logger.info(
            "memory_worker_stopped",
            extra={
                "event": "memory_worker_stopped",
                "worker_id": self._worker_id,
                "duration_seconds": duration_seconds,
                "active_jobs": self._active_job_count,
                "status": "stopped",
            },
        )

    def wake(self) -> None:
        self._wake.set()

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                await self._poll_once()
            except Exception:
                logger.exception("memory worker poll failed", extra={"worker_id": self._worker_id})
            try:
                await asyncio.wait_for(
                    self._wake.wait(),
                    timeout=self._config.worker_poll_seconds,
                )
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _poll_once(self) -> None:
        if self._stop.is_set():
            return

        free_slots = self._config.worker_concurrency - len(self._active_tasks)
        if free_slots <= 0:
            return
        jobs = await asyncio.to_thread(
            self._service.jobs.claim,
            worker_id=self._worker_id,
            limit=min(self._config.job_claim_batch_size, free_slots),
            lease_seconds=self._config.job_lease_seconds,
            stages=self._stages,
        )
        if self._stop.is_set():
            return
        for job in jobs:
            if self._stop.is_set():
                return
            task = asyncio.create_task(
                self._process_job(job),
                name=f"memory-job-{job.job_id}",
            )
            self._active_tasks.add(task)
            task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._active_tasks.discard(task)
        if not task.cancelled():
            task.exception()
        self._wake.set()

    async def _process_job(self, job: MemoryJob) -> None:
        if job.lease_token is None:
            return
        lease_ok = await asyncio.to_thread(
            self._service.jobs.heartbeat,
            job.job_id,
            worker_id=self._worker_id,
            lease_token=job.lease_token,
            attempt=job.attempts,
            input_hash=job.input_hash,
            lease_seconds=self._config.job_lease_seconds,
        )
        if not lease_ok:
            return
        self._active_job_count += 1
        run_id = None
        lease_lost = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat(job, lease_lost),
            name=f"memory-heartbeat-{job.job_id}",
        )
        try:
            version = await asyncio.to_thread(
                self._service.sources.get_version,
                job.source_version_id,
                user_id=job.user_id,
            )
            if version is None:
                raise RuntimeError("source version missing for job")

            source = await asyncio.to_thread(
                self._service.sources.get_source,
                version.source_id,
                user_id=job.user_id,
            )
            if source is None:
                raise RuntimeError("source missing for job")

            processor = self._registry.resolve(
                job.stage,
                job.processor_name,
                job.processor_version,
            )
            from memory.ids import make_run_id

            run_id = make_run_id()
            await asyncio.to_thread(
                self._service.record_processor_run_start,
                run_id=run_id,
                job=job,
            )
            context = await asyncio.to_thread(
                self._service.build_processor_context,
                job=job,
                source=source,
                source_version=version,
                worker_id=self._worker_id,
            )
            output = await processor.process(context)
            if lease_lost.is_set():
                from memory.jobs import MemoryLeaseError

                raise MemoryLeaseError("job lease was lost during processing")
            committed = await asyncio.to_thread(
                self._service.commit_processor_output,
                run_id=run_id,
                job=job,
                worker_id=self._worker_id,
                output=output,
            )
            if not committed:
                from memory.jobs import MemoryLeaseError

                raise MemoryLeaseError("failed to commit processor output")
        except Exception as exc:
            from memory.jobs import MemoryLeaseError

            retryable = not isinstance(exc, (KeyError, ValueError, MemoryLeaseError))
            if run_id is not None:
                try:
                    await asyncio.to_thread(
                        self._service.record_processor_run_failure,
                        run_id=run_id,
                        job=job,
                        error=exc,
                    )
                except Exception:
                    logger.exception(
                        "memory worker failed to record processor run failure",
                        extra={"job_id": job.job_id, "worker_id": self._worker_id},
                    )
            try:
                await asyncio.to_thread(
                    self._service.jobs.fail,
                    job.job_id,
                    worker_id=self._worker_id,
                    lease_token=job.lease_token,
                    attempt=job.attempts,
                    input_hash=job.input_hash,
                    error=exc,
                    retryable=retryable,
                )
            except Exception:
                logger.exception(
                    "memory worker failed to record job failure",
                    extra={"job_id": job.job_id, "worker_id": self._worker_id},
                )
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            self._active_job_count -= 1

    async def _heartbeat(self, job: MemoryJob, lease_lost: asyncio.Event) -> None:
        if job.lease_token is None:
            lease_lost.set()
            return
        interval = max(0.1, min(30.0, self._config.job_lease_seconds / 3))
        while True:
            await asyncio.sleep(interval)
            try:
                ok = await asyncio.to_thread(
                    self._service.jobs.heartbeat,
                    job.job_id,
                    worker_id=self._worker_id,
                    lease_token=job.lease_token,
                    attempt=job.attempts,
                    input_hash=job.input_hash,
                    lease_seconds=self._config.job_lease_seconds,
                )
            except Exception:
                logger.exception(
                    "memory worker heartbeat failed",
                    extra={
                        "job_id": job.job_id,
                        "worker_id": self._worker_id,
                    },
                )
                lease_lost.set()
                return
            if not ok:
                lease_lost.set()
                return
