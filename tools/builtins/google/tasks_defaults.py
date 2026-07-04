from __future__ import annotations

import asyncio
from typing import Any

from tools.builtins.google.auth import get_tasks_service
from tools.builtins.google.tasks_serialize import compact_tasklist

_DEFAULT_LIST_TITLES = frozenset(
    {
        "my tasks",
        "мои задачи",
        "tasks",
        "задачи",
    }
)

_default_tasklist_cache: dict[int, tuple[str, str]] = {}


def clear_default_tasklist_cache(user_id: int | None = None) -> None:
    if user_id is None:
        _default_tasklist_cache.clear()
        return
    _default_tasklist_cache.pop(user_id, None)


def _pick_default_tasklist(tasklists: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not tasklists:
        return None
    for item in tasklists:
        title = str(item.get("title") or "").strip().casefold()
        if title in _DEFAULT_LIST_TITLES:
            return item
    return tasklists[0]


async def fetch_tasklists(user_id: int, *, max_results: int = 100) -> list[dict[str, Any]]:
    def _call(service):
        response = service.tasklists().list(maxResults=max_results).execute()
        return response.get("items") or []

    service = await get_tasks_service(user_id)
    items = await asyncio.to_thread(_call, service)
    return [compact_tasklist(item) for item in items]


async def resolve_default_tasklist(user_id: int) -> tuple[str, str]:
    cached = _default_tasklist_cache.get(user_id)
    if cached:
        return cached

    def _call(service):
        response = service.tasklists().list(maxResults=100).execute()
        return response.get("items") or []

    service = await get_tasks_service(user_id)
    raw_items = await asyncio.to_thread(_call, service)
    picked = _pick_default_tasklist(raw_items)
    if picked is None:
        raise RuntimeError("No Google Tasks lists found for this account")
    tasklist_id = str(picked["id"])
    title = str(picked.get("title") or "")
    _default_tasklist_cache[user_id] = (tasklist_id, title)
    return tasklist_id, title


async def resolve_tasklist_id(user_id: int, arguments: dict[str, Any]) -> tuple[str, str | None]:
    explicit = arguments.get("tasklist_id")
    if explicit and str(explicit).strip():
        return str(explicit).strip(), None
    tasklist_id, title = await resolve_default_tasklist(user_id)
    return tasklist_id, title
