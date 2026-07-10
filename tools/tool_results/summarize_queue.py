from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from config import Settings
from llm import LLMClient
from tools.tool_results.store import ToolResultStore
from tools.tool_results.summarize import summarize_tool_result

logger = logging.getLogger(__name__)


@dataclass
class SummarizeQueue:
    max_concurrent: int
    _semaphore: asyncio.Semaphore = field(init=False)
    _tasks: set[asyncio.Task[None]] = field(default_factory=set)

    def __post_init__(self) -> None:
        limit = max(1, self.max_concurrent)
        self.max_concurrent = limit
        self._semaphore = asyncio.Semaphore(limit)

    def submit(
        self,
        llm: LLMClient,
        settings: Settings,
        store: ToolResultStore,
        *,
        ref: str,
        tool_name: str,
        args_json: str | None,
        payload_json: str,
        payload_kind: str = "result",
    ) -> asyncio.Task[None]:
        async def _run() -> None:
            async with self._semaphore:
                await summarize_tool_result(
                    llm,
                    settings,
                    store,
                    ref=ref,
                    tool_name=tool_name,
                    args_json=args_json,
                    payload_json=payload_json,
                    payload_kind=payload_kind,
                )

        task = asyncio.create_task(_run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        logger.debug(
            "tool_result_summarize queued ref=%s tool=%s in_flight=%s",
            ref,
            tool_name,
            len(self._tasks),
        )
        return task


_queue: SummarizeQueue | None = None


def get_summarize_queue(settings: Settings) -> SummarizeQueue:
    global _queue
    if _queue is None:
        _queue = SummarizeQueue(max_concurrent=settings.tool_result_summarize_max_concurrent)
    return _queue


def reset_summarize_queue() -> None:
    global _queue
    _queue = None
