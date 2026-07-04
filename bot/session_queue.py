import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

from config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")
NotifyBusy = Callable[[], Awaitable[None]]
ProcessBatch = Callable[[list[T]], Awaitable[None]]


class SessionQueueManager(Generic[T]):
    def __init__(self, max_pending: int | None = None) -> None:
        self._max_pending = max_pending
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._pending: dict[int, deque[T]] = defaultdict(deque)
        self._worker_running: dict[int, bool] = defaultdict(bool)
        self._processors: dict[int, ProcessBatch[T]] = {}
        self._last_append_at: dict[int, float] = {}

    def _pending_limit(self) -> int:
        if self._max_pending is not None:
            return self._max_pending
        return get_settings().queue_max_pending

    def _burst_quiet_s(self) -> float:
        return get_settings().message_burst_quiet_ms / 1000.0

    def _burst_max_wait_s(self) -> float:
        settings = get_settings()
        quiet_s = settings.message_burst_quiet_ms / 1000.0
        max_wait_s = settings.message_burst_max_wait_ms / 1000.0
        return max(quiet_s, max_wait_s)

    def reset(self, user_id: int) -> None:
        self._pending[user_id].clear()
        self._last_append_at.pop(user_id, None)

    def pending_count(self, user_id: int) -> int:
        return len(self._pending[user_id])

    async def submit(
        self,
        user_id: int,
        item: T,
        process_batch: ProcessBatch[T],
        on_busy: NotifyBusy,
        *,
        on_queue_full: NotifyBusy | None = None,
    ) -> None:
        start_worker = False
        notify_busy = False
        notify_full = False

        async with self._locks[user_id]:
            already_active = self._worker_running[user_id] or self._pending[user_id]
            if already_active and len(self._pending[user_id]) >= self._pending_limit():
                notify_full = True
            else:
                if already_active:
                    notify_busy = True

                self._pending[user_id].append(item)
                self._last_append_at[user_id] = time.monotonic()
                self._processors[user_id] = process_batch

                if not self._worker_running[user_id]:
                    self._worker_running[user_id] = True
                    start_worker = True

        if notify_full:
            callback = on_queue_full or on_busy
            await callback()
            return

        if notify_busy:
            await on_busy()

        if start_worker:
            asyncio.create_task(self._worker(user_id))

    async def _collect_burst(self, user_id: int) -> list[T]:
        quiet_s = self._burst_quiet_s()
        max_wait_s = self._burst_max_wait_s()
        deadline = time.monotonic() + max_wait_s

        while True:
            await asyncio.sleep(quiet_s)

            async with self._locks[user_id]:
                if not self._pending[user_id]:
                    return []

                last_append = self._last_append_at.get(user_id, 0.0)
                now = time.monotonic()
                quiet_enough = now - last_append >= quiet_s
                timed_out = now >= deadline

                if quiet_enough or timed_out:
                    batch = list(self._pending[user_id])
                    self._pending[user_id].clear()
                    return batch

    async def _drain_immediate(self, user_id: int) -> list[T]:
        async with self._locks[user_id]:
            if not self._pending[user_id]:
                return []
            batch = list(self._pending[user_id])
            self._pending[user_id].clear()
            return batch

    async def _worker(self, user_id: int) -> None:
        try:
            debounce_next = True
            while True:
                if debounce_next:
                    batch = await self._collect_burst(user_id)
                else:
                    batch = await self._drain_immediate(user_id)

                if not batch:
                    async with self._locks[user_id]:
                        if self._pending[user_id]:
                            debounce_next = True
                            continue
                        self._worker_running[user_id] = False
                        self._processors.pop(user_id, None)
                        return

                process_batch = self._processors[user_id]
                debounce_next = False

                try:
                    await process_batch(batch)
                except Exception:
                    logger.exception("Queued chat batch failed for user %s", user_id)
        except Exception:
            logger.exception("Session queue worker crashed for user %s", user_id)
            async with self._locks[user_id]:
                self._worker_running[user_id] = False
                self._processors.pop(user_id, None)
