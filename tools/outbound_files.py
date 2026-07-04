from __future__ import annotations

import contextvars
from dataclasses import dataclass

from tools.telegram_limits import TelegramSendKind


@dataclass(frozen=True)
class OutboundDelivery:
    data: bytes
    filename: str
    mime_type: str | None
    kind: TelegramSendKind
    caption: str | None = None


class OutboundQueue:
    def __init__(self) -> None:
        self._items: list[OutboundDelivery] = []

    def enqueue(self, item: OutboundDelivery) -> None:
        self._items.append(item)

    def snapshot(self) -> tuple[OutboundDelivery, ...]:
        return tuple(self._items)


_outbound_queue: contextvars.ContextVar[OutboundQueue | None] = contextvars.ContextVar(
    "outbound_queue",
    default=None,
)


def set_outbound_queue(queue: OutboundQueue) -> contextvars.Token[OutboundQueue | None]:
    return _outbound_queue.set(queue)


def reset_outbound_queue(token: contextvars.Token[OutboundQueue | None]) -> None:
    _outbound_queue.reset(token)


def get_outbound_queue() -> OutboundQueue | None:
    return _outbound_queue.get()


def require_outbound_queue() -> OutboundQueue:
    queue = get_outbound_queue()
    if queue is None:
        raise RuntimeError("Outbound queue is not active.")
    return queue
