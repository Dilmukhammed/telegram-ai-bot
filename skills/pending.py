from __future__ import annotations

import contextvars

_pending_skills: contextvars.ContextVar[list[tuple[str, str]]] = contextvars.ContextVar(
    "pending_skills",
    default=[],
)

_pending_skill_unloads: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
    "pending_skill_unloads",
    default=[],
)

_loaded_skill_ids: contextvars.ContextVar[set[str] | None] = contextvars.ContextVar(
    "loaded_skill_ids",
    default=None,
)


def reset_skill_run_state() -> None:
    _pending_skills.set([])
    _pending_skill_unloads.set([])
    _loaded_skill_ids.set(set())


def is_skill_loaded(skill_id: str) -> bool:
    loaded = _loaded_skill_ids.get()
    return loaded is not None and skill_id in loaded


def mark_skill_loaded(skill_id: str) -> None:
    loaded = set(_loaded_skill_ids.get() or ())
    loaded.add(skill_id)
    _loaded_skill_ids.set(loaded)


def unmark_skill_loaded(skill_id: str) -> None:
    loaded = set(_loaded_skill_ids.get() or ())
    loaded.discard(skill_id)
    _loaded_skill_ids.set(loaded)


def push_pending_skill(skill_id: str, content: str) -> None:
    current = list(_pending_skills.get())
    current.append((skill_id, content))
    _pending_skills.set(current)


def take_pending_skills() -> list[tuple[str, str]]:
    pending = list(_pending_skills.get())
    _pending_skills.set([])
    return pending


def push_pending_skill_unload(skill_id: str) -> None:
    current = list(_pending_skill_unloads.get())
    if skill_id not in current:
        current.append(skill_id)
    _pending_skill_unloads.set(current)


def take_pending_skill_unloads() -> list[str]:
    pending = list(_pending_skill_unloads.get())
    _pending_skill_unloads.set([])
    return pending
