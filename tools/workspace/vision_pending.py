from __future__ import annotations

import contextvars

_pending_vision: contextvars.ContextVar[list[tuple[str, str]]] = contextvars.ContextVar(
    "workspace_pending_vision",
    default=[],
)


def push_pending_vision(path: str, data_url: str) -> None:
    current = list(_pending_vision.get())
    current.append((path, data_url))
    _pending_vision.set(current)


def take_pending_vision() -> list[tuple[str, str]]:
    pending = list(_pending_vision.get())
    _pending_vision.set([])
    return pending


def clear_pending_vision() -> None:
    _pending_vision.set([])
