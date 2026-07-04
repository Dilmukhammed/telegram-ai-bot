from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from googleapiclient.errors import HttpError

from tools.builtins.google.auth import get_tasks_service
from tools.builtins.google.tasks_datetime import (
    due_bounds_for_day,
    due_max_before_day,
    normalize_task_due,
    today_date,
)
from tools.builtins.google.tasks_defaults import (
    clear_default_tasklist_cache,
    fetch_tasklists,
    resolve_default_tasklist,
    resolve_tasklist_id,
)
from tools.builtins.google.tasks_serialize import (
    build_task_patch_body,
    build_tasklist_patch_body,
    compact_task,
    compact_tasklist,
    merge_task_for_update,
    merge_tasklist_for_update,
)
from tools.builtins.google.tool_hints import GOOGLE_TASKS_OAUTH_HINT
from tools.context import get_run_context
from tools.schema import ToolSpec

_TASK_ID_PARAM = {
    "task_id": {"type": "string", "description": "Google Task ID."},
}


def _require_task_id(arguments: dict[str, Any]) -> str:
    task_id = str(arguments.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("task_id is required")
    return task_id


def _task_matches_query(task: dict[str, Any], query: str) -> bool:
    needle = query.casefold()
    haystack = f"{task.get('title') or ''} {task.get('notes') or ''}".casefold()
    return needle in haystack


async def _fetch_task_raw(user_id: int, tasklist_id: str, task_id: str) -> dict[str, Any]:
    def _call(service):
        return service.tasks().get(tasklist=tasklist_id, task=task_id).execute()

    return await _run_tasks_call(user_id, _call)


async def _fetch_tasklist_raw(user_id: int, tasklist_id: str) -> dict[str, Any]:
    def _call(service):
        return service.tasklists().get(tasklist=tasklist_id).execute()

    return await _run_tasks_call(user_id, _call)


_TASKLIST_ID_PARAM = {
    "tasklist_id": {
        "type": "string",
        "description": "Google Tasks list ID. Omit to use the user's default list (usually My Tasks).",
    }
}

_CONFIRM_PARAM = {
    "confirm": {
        "type": "boolean",
        "description": "Must be true for destructive operations.",
    }
}


def _require_confirm(arguments: dict[str, Any], *, tool_name: str) -> None:
    if not bool(arguments.get("confirm")):
        raise ValueError(f"{tool_name} requires confirm=true")


def _require_tasklist_id_explicit(arguments: dict[str, Any]) -> str:
    tasklist_id = str(arguments.get("tasklist_id") or "").strip()
    if not tasklist_id:
        raise ValueError("tasklist_id is required")
    return tasklist_id


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


async def _run_tasks_call(user_id: int, fn):
    service = await get_tasks_service(user_id)
    return await asyncio.to_thread(fn, service)


def _filter_tasks(
    tasks: list[dict[str, Any]],
    *,
    include_completed: bool = False,
    open_only: bool = False,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for task in tasks:
        if task.get("hidden") or task.get("deleted"):
            continue
        status = task.get("status")
        if open_only and status == "completed":
            continue
        if not include_completed and status == "completed":
            continue
        filtered.append(compact_task(task))
    return filtered


async def _list_tasks_raw(
    user_id: int,
    tasklist_id: str,
    *,
    due_min: str | None = None,
    due_max: str | None = None,
    show_completed: bool = True,
    show_hidden: bool = False,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    def _call(service):
        params: dict[str, Any] = {
            "tasklist": tasklist_id,
            "maxResults": min(max_results, 100),
            "showCompleted": show_completed,
            "showHidden": show_hidden,
            "showDeleted": False,
        }
        if due_min:
            params["dueMin"] = due_min
        if due_max:
            params["dueMax"] = due_max
        response = service.tasks().list(**params).execute()
        return response.get("items") or []

    items = await _run_tasks_call(user_id, _call)
    return items


async def _list_tasklists_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    max_results = min(int(arguments.get("max_results", 100)), 100)
    tasklists = await fetch_tasklists(user_id, max_results=max_results)
    default_tasklist_id = None
    if tasklists:
        try:
            default_tasklist_id, _ = await resolve_default_tasklist(user_id)
        except RuntimeError:
            default_tasklist_id = tasklists[0]["id"]
    return {
        "count": len(tasklists),
        "default_tasklist_id": default_tasklist_id,
        "tasklists": tasklists,
    }


async def _list_tasks_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    include_completed = bool(arguments.get("include_completed", True))
    max_results = min(int(arguments.get("max_results", 50)), 100)

    items = await _list_tasks_raw(
        user_id,
        tasklist_id,
        due_min=arguments.get("due_min"),
        due_max=arguments.get("due_max"),
        show_completed=include_completed,
        show_hidden=bool(arguments.get("show_hidden", False)),
        max_results=max_results,
    )
    tasks = _filter_tasks(items, include_completed=include_completed)
    return {
        "tasklist_id": tasklist_id,
        "count": len(tasks),
        "tasks": tasks[:max_results],
    }


async def _get_task_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    task_id = _require_task_id(arguments)

    task = await _fetch_task_raw(user_id, tasklist_id, task_id)
    return {"tasklist_id": tasklist_id, "task": compact_task(task)}


async def _create_task_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    title = str(arguments["title"]).strip()
    if not title:
        raise ValueError("title is required")

    body: dict[str, Any] = {"title": title, "status": arguments.get("status", "needsAction")}
    if arguments.get("notes") is not None:
        body["notes"] = str(arguments["notes"])
    if arguments.get("due"):
        body["due"] = normalize_task_due(str(arguments["due"]))

    insert_kwargs: dict[str, Any] = {"tasklist": tasklist_id, "body": body}
    if arguments.get("parent"):
        insert_kwargs["parent"] = str(arguments["parent"])
    if arguments.get("previous"):
        insert_kwargs["previous"] = str(arguments["previous"])

    def _call(service):
        return service.tasks().insert(**insert_kwargs).execute()

    task = await _run_tasks_call(user_id, _call)
    compact = compact_task(task)
    return {
        "created": True,
        "tasklist_id": tasklist_id,
        "task": compact,
        "webViewLink": compact.get("webViewLink"),
    }


async def _list_default_tasks_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, tasklist_title = await resolve_default_tasklist(user_id)
    include_completed = bool(arguments.get("include_completed", False))
    max_results = min(int(arguments.get("max_results", 50)), 100)

    items = await _list_tasks_raw(
        user_id,
        tasklist_id,
        show_completed=include_completed,
        max_results=max_results,
    )
    tasks = _filter_tasks(items, include_completed=include_completed, open_only=not include_completed)
    return {
        "tasklist_id": tasklist_id,
        "tasklist_title": tasklist_title,
        "count": len(tasks),
        "tasks": tasks[:max_results],
    }


async def _list_today_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    time_zone = arguments.get("time_zone")
    include_completed = bool(arguments.get("include_completed", False))
    today = today_date(time_zone)
    due_min, due_max = due_bounds_for_day(today, time_zone)

    items = await _list_tasks_raw(
        user_id,
        tasklist_id,
        due_min=due_min,
        due_max=due_max,
        show_completed=include_completed,
        max_results=100,
    )
    tasks = _filter_tasks(items, include_completed=include_completed)
    return {
        "date": today.isoformat(),
        "tasklist_id": tasklist_id,
        "count": len(tasks),
        "tasks": tasks,
    }


async def _list_overdue_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    time_zone = arguments.get("time_zone")
    max_results = min(int(arguments.get("max_results", 50)), 100)
    today = today_date(time_zone)
    due_max = due_max_before_day(today, time_zone)

    items = await _list_tasks_raw(
        user_id,
        tasklist_id,
        due_max=due_max,
        show_completed=False,
        max_results=100,
    )
    tasks = _filter_tasks(items, open_only=True)[:max_results]
    return {
        "tasklist_id": tasklist_id,
        "count": len(tasks),
        "tasks": tasks,
    }


async def _list_upcoming_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    time_zone = arguments.get("time_zone")
    days_ahead = max(int(arguments.get("days_ahead", 7)), 1)
    max_results = min(int(arguments.get("max_results", 50)), 100)
    today = today_date(time_zone)
    start_day = today + timedelta(days=1)
    end_day = today + timedelta(days=days_ahead + 1)
    due_min, _ = due_bounds_for_day(start_day, time_zone)
    _, due_max = due_bounds_for_day(end_day, time_zone)

    items = await _list_tasks_raw(
        user_id,
        tasklist_id,
        due_min=due_min,
        due_max=due_max,
        show_completed=False,
        max_results=100,
    )
    tasks = _filter_tasks(items, open_only=True)[:max_results]
    return {
        "days_ahead": days_ahead,
        "tasklist_id": tasklist_id,
        "count": len(tasks),
        "tasks": tasks,
    }


async def _quick_add_task_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "title": arguments["title"],
        "notes": arguments.get("notes"),
        "due": arguments.get("due"),
    }
    return await _create_task_handler(payload)


async def _complete_task_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    task_id = _require_task_id(arguments)

    def _call(service):
        return (
            service.tasks()
            .patch(tasklist=tasklist_id, task=task_id, body={"status": "completed"})
            .execute()
        )

    task = await _run_tasks_call(user_id, _call)
    compact = compact_task(task)
    return {
        "completed": True,
        "tasklist_id": tasklist_id,
        "task": compact,
        "webViewLink": compact.get("webViewLink"),
    }


async def _get_tasklist_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id = str(arguments.get("tasklist_id") or "").strip()
    if not tasklist_id:
        raise ValueError("tasklist_id is required")
    tasklist = await _fetch_tasklist_raw(user_id, tasklist_id)
    return {"tasklist": compact_tasklist(tasklist)}


async def _update_task_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    task_id = _require_task_id(arguments)
    existing = await _fetch_task_raw(user_id, tasklist_id, task_id)
    body = merge_task_for_update(existing, arguments)

    def _call(service):
        return service.tasks().update(tasklist=tasklist_id, task=task_id, body=body).execute()

    task = await _run_tasks_call(user_id, _call)
    compact = compact_task(task)
    return {
        "updated": True,
        "tasklist_id": tasklist_id,
        "task": compact,
        "webViewLink": compact.get("webViewLink"),
    }


async def _patch_task_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    task_id = _require_task_id(arguments)
    body = build_task_patch_body(arguments)

    def _call(service):
        return service.tasks().patch(tasklist=tasklist_id, task=task_id, body=body).execute()

    task = await _run_tasks_call(user_id, _call)
    compact = compact_task(task)
    return {
        "patched": True,
        "tasklist_id": tasklist_id,
        "task": compact,
        "webViewLink": compact.get("webViewLink"),
    }


async def _delete_task_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    task_id = _require_task_id(arguments)

    def _call(service):
        service.tasks().delete(tasklist=tasklist_id, task=task_id).execute()
        return True

    await _run_tasks_call(user_id, _call)
    return {"deleted": True, "tasklist_id": tasklist_id, "task_id": task_id}


async def _move_task_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    task_id = _require_task_id(arguments)

    move_kwargs: dict[str, Any] = {"tasklist": tasklist_id, "task": task_id}
    if arguments.get("destination_tasklist_id"):
        move_kwargs["destinationTasklist"] = str(arguments["destination_tasklist_id"])
    if arguments.get("parent"):
        move_kwargs["parent"] = str(arguments["parent"])
    if arguments.get("previous"):
        move_kwargs["previous"] = str(arguments["previous"])

    def _call(service):
        return service.tasks().move(**move_kwargs).execute()

    try:
        task = await _run_tasks_call(user_id, _call)
    except HttpError as exc:
        message = str(exc)
        if "recurring" in message.lower() or exc.resp.status == 400:
            raise RuntimeError(
                "Cannot move this task — recurring tasks cannot move between lists, "
                "and assigned tasks have move restrictions."
            ) from exc
        raise

    destination_tasklist_id = str(arguments.get("destination_tasklist_id") or tasklist_id)
    compact = compact_task(task)
    return {
        "moved": True,
        "tasklist_id": tasklist_id,
        "destination_tasklist_id": destination_tasklist_id,
        "task": compact,
        "webViewLink": compact.get("webViewLink"),
    }


async def _search_tasks_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    max_results = min(int(arguments.get("max_results", 20)), 50)

    explicit_tasklist = arguments.get("tasklist_id")
    if explicit_tasklist and str(explicit_tasklist).strip():
        tasklist_id = str(explicit_tasklist).strip()
        tasklists = [compact_tasklist(await _fetch_tasklist_raw(user_id, tasklist_id))]
    else:
        tasklists = await fetch_tasklists(user_id)

    matches: list[dict[str, Any]] = []
    for tasklist in tasklists:
        list_id = str(tasklist["id"])
        items = await _list_tasks_raw(
            user_id,
            list_id,
            show_completed=bool(arguments.get("include_completed", False)),
            max_results=100,
        )
        for item in items:
            if not _task_matches_query(item, query):
                continue
            compact = compact_task(item)
            compact["tasklist_id"] = list_id
            compact["tasklist_title"] = tasklist.get("title")
            matches.append(compact)
            if len(matches) >= max_results:
                break
        if len(matches) >= max_results:
            break

    return {"query": query, "count": len(matches), "tasks": matches}


async def _list_subtasks_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    parent_task_id = str(arguments.get("parent_task_id") or "").strip()
    if not parent_task_id:
        raise ValueError("parent_task_id is required")

    items = await _list_tasks_raw(
        user_id,
        tasklist_id,
        show_completed=bool(arguments.get("include_completed", False)),
        max_results=100,
    )
    subtasks = [
        compact_task(item)
        for item in items
        if str(item.get("parent") or "") == parent_task_id and not item.get("hidden")
    ]
    return {
        "tasklist_id": tasklist_id,
        "parent_task_id": parent_task_id,
        "count": len(subtasks),
        "tasks": subtasks,
    }


async def _list_all_open_tasks_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    max_results_per_list = min(int(arguments.get("max_results_per_list", 30)), 100)
    max_total = min(int(arguments.get("max_total", 50)), 100)
    tasklists = await fetch_tasklists(user_id)

    results: list[dict[str, Any]] = []
    for tasklist in tasklists:
        list_id = str(tasklist["id"])
        items = await _list_tasks_raw(
            user_id,
            list_id,
            show_completed=False,
            max_results=max_results_per_list,
        )
        for item in _filter_tasks(items, open_only=True):
            enriched = dict(item)
            enriched["tasklist_id"] = list_id
            enriched["tasklist_title"] = tasklist.get("title")
            results.append(enriched)
            if len(results) >= max_total:
                break
        if len(results) >= max_total:
            break

    return {"count": len(results), "tasks": results}


async def _uncomplete_task_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)
    task_id = _require_task_id(arguments)

    def _call(service):
        return (
            service.tasks()
            .patch(tasklist=tasklist_id, task=task_id, body={"status": "needsAction"})
            .execute()
        )

    task = await _run_tasks_call(user_id, _call)
    compact = compact_task(task)
    return {
        "completed": False,
        "tasklist_id": tasklist_id,
        "task": compact,
        "webViewLink": compact.get("webViewLink"),
    }


async def _create_tasklist_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    title = str(arguments.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")

    def _call(service):
        return service.tasklists().insert(body={"title": title}).execute()

    tasklist = await _run_tasks_call(user_id, _call)
    clear_default_tasklist_cache(user_id)
    compact = compact_tasklist(tasklist)
    return {"created": True, "tasklist": compact}


async def _update_tasklist_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id = _require_tasklist_id_explicit(arguments)
    existing = await _fetch_tasklist_raw(user_id, tasklist_id)
    body = merge_tasklist_for_update(existing, arguments)

    def _call(service):
        return service.tasklists().update(tasklist=tasklist_id, body=body).execute()

    tasklist = await _run_tasks_call(user_id, _call)
    clear_default_tasklist_cache(user_id)
    return {"updated": True, "tasklist": compact_tasklist(tasklist)}


async def _patch_tasklist_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    tasklist_id = _require_tasklist_id_explicit(arguments)
    body = build_tasklist_patch_body(arguments)

    def _call(service):
        return service.tasklists().patch(tasklist=tasklist_id, body=body).execute()

    tasklist = await _run_tasks_call(user_id, _call)
    clear_default_tasklist_cache(user_id)
    return {"patched": True, "tasklist": compact_tasklist(tasklist)}


async def _delete_tasklist_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    _require_confirm(arguments, tool_name="delete_tasklist")
    tasklist_id = _require_tasklist_id_explicit(arguments)

    open_tasks = await _list_tasks_raw(
        user_id,
        tasklist_id,
        show_completed=False,
        max_results=1,
    )
    had_open_tasks = bool(open_tasks)

    def _call(service):
        service.tasklists().delete(tasklist=tasklist_id).execute()
        return True

    await _run_tasks_call(user_id, _call)
    clear_default_tasklist_cache(user_id)
    result: dict[str, Any] = {"deleted": True, "tasklist_id": tasklist_id}
    if had_open_tasks:
        result["warning"] = "Task list had open tasks; they were deleted with the list."
    return result


async def _clear_completed_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    _require_confirm(arguments, tool_name="clear_completed")
    tasklist_id, _ = await resolve_tasklist_id(user_id, arguments)

    def _call(service):
        service.tasks().clear(tasklist=tasklist_id).execute()
        return True

    await _run_tasks_call(user_id, _call)
    return {"cleared": True, "tasklist_id": tasklist_id}


GOOGLE_TASKS_LIST_TASKLISTS = ToolSpec(
    name="google.tasks.list_tasklists",
    description=(
        GOOGLE_TASKS_OAUTH_HINT
        + "List all Google Tasks lists for the user. Returns default_tasklist_id for the main list."
    ),
    parameters={
        "type": "object",
        "properties": {
            "max_results": {"type": "integer", "default": 100, "description": "Max lists to return (max 100)."},
        },
    },
    handler=_list_tasklists_handler,
    tags=("google", "tasks", "read", "tasklists"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    examples=("my task lists", "google tasks lists", "списки задач"),
)

GOOGLE_TASKS_LIST_TASKS = ToolSpec(
    name="google.tasks.list_tasks",
    description=(
        GOOGLE_TASKS_OAUTH_HINT
        + "List tasks in a Google Tasks list with optional due date filters. "
        "Prefer list_default_tasks, list_today, or list_overdue for common views."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_TASKLIST_ID_PARAM,
            "due_min": {"type": "string", "description": "RFC3339 lower bound for due date."},
            "due_max": {"type": "string", "description": "RFC3339 upper bound for due date."},
            "include_completed": {"type": "boolean", "default": True},
            "show_hidden": {"type": "boolean", "default": False},
            "max_results": {"type": "integer", "default": 50},
        },
    },
    handler=_list_tasks_handler,
    tags=("google", "tasks", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    examples=("list tasks in shopping list", "tasks with due dates"),
)

GOOGLE_TASKS_GET_TASK = ToolSpec(
    name="google.tasks.get_task",
    description=GOOGLE_TASKS_OAUTH_HINT + "Get one Google Task by ID from a task list.",
    parameters={
        "type": "object",
        "properties": {
            **_TASKLIST_ID_PARAM,
            "task_id": {"type": "string", "description": "Google Task ID."},
        },
        "required": ["task_id"],
    },
    handler=_get_task_handler,
    tags=("google", "tasks", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    examples=("get task details", "show task by id"),
)

GOOGLE_TASKS_CREATE_TASK = ToolSpec(
    name="google.tasks.create_task",
    description=(
        GOOGLE_TASKS_OAUTH_HINT
        + "Create a task in a Google Tasks list. Use quick_add_task for a title-only todo on the default list."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_TASKLIST_ID_PARAM,
            "title": {"type": "string", "description": "Task title (required)."},
            "notes": {"type": "string", "description": "Optional notes."},
            "due": {
                "type": "string",
                "description": "Due date as YYYY-MM-DD or ISO datetime (time is ignored by Google Tasks).",
            },
            "status": {
                "type": "string",
                "enum": ["needsAction", "completed"],
                "default": "needsAction",
            },
            "parent": {"type": "string", "description": "Parent task ID to create a subtask."},
            "previous": {"type": "string", "description": "Previous sibling task ID for ordering."},
        },
        "required": ["title"],
    },
    handler=_create_task_handler,
    tags=("google", "tasks", "write"),
    parallel_safe=False,
    examples=("create task buy milk", "add todo with due date"),
)

GOOGLE_TASKS_LIST_DEFAULT_TASKS = ToolSpec(
    name="google.tasks.list_default_tasks",
    description=(
        GOOGLE_TASKS_OAUTH_HINT
        + "List open tasks on the user's default Google Tasks list (usually My Tasks)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "include_completed": {"type": "boolean", "default": False},
            "max_results": {"type": "integer", "default": 50},
        },
    },
    handler=_list_default_tasks_handler,
    tags=("google", "tasks", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    examples=("my todos", "what are my tasks", "мои задачи"),
)

GOOGLE_TASKS_LIST_TODAY = ToolSpec(
    name="google.tasks.list_today",
    description=GOOGLE_TASKS_OAUTH_HINT + "List Google Tasks due today in the user's timezone.",
    parameters={
        "type": "object",
        "properties": {
            **_TASKLIST_ID_PARAM,
            "time_zone": {"type": "string", "description": "IANA timezone; defaults to bot timezone."},
            "include_completed": {"type": "boolean", "default": False},
        },
    },
    handler=_list_today_handler,
    tags=("google", "tasks", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    examples=("tasks due today", "what to do today", "задачи на сегодня"),
)

GOOGLE_TASKS_LIST_OVERDUE = ToolSpec(
    name="google.tasks.list_overdue",
    description=GOOGLE_TASKS_OAUTH_HINT + "List overdue open Google Tasks (due before today).",
    parameters={
        "type": "object",
        "properties": {
            **_TASKLIST_ID_PARAM,
            "time_zone": {"type": "string", "description": "IANA timezone; defaults to bot timezone."},
            "max_results": {"type": "integer", "default": 50},
        },
    },
    handler=_list_overdue_handler,
    tags=("google", "tasks", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    examples=("overdue tasks", "просроченные задачи"),
)

GOOGLE_TASKS_LIST_UPCOMING = ToolSpec(
    name="google.tasks.list_upcoming",
    description=GOOGLE_TASKS_OAUTH_HINT + "List open Google Tasks due in the next N days (default 7).",
    parameters={
        "type": "object",
        "properties": {
            **_TASKLIST_ID_PARAM,
            "days_ahead": {"type": "integer", "default": 7},
            "time_zone": {"type": "string", "description": "IANA timezone; defaults to bot timezone."},
            "max_results": {"type": "integer", "default": 50},
        },
    },
    handler=_list_upcoming_handler,
    tags=("google", "tasks", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    examples=("upcoming tasks this week", "tasks due soon"),
)

GOOGLE_TASKS_QUICK_ADD_TASK = ToolSpec(
    name="google.tasks.quick_add_task",
    description=(
        GOOGLE_TASKS_OAUTH_HINT
        + "Quickly add a task to the default Google Tasks list (title required; optional due date and notes)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Task title."},
            "notes": {"type": "string", "description": "Optional notes."},
            "due": {
                "type": "string",
                "description": "Optional due date YYYY-MM-DD or ISO datetime.",
            },
        },
        "required": ["title"],
    },
    handler=_quick_add_task_handler,
    tags=("google", "tasks", "write"),
    parallel_safe=False,
    examples=("remind me to call mom", "add task buy bread tomorrow", "добавь задачу"),
)

GOOGLE_TASKS_COMPLETE_TASK = ToolSpec(
    name="google.tasks.complete_task",
    description=GOOGLE_TASKS_OAUTH_HINT + "Mark a Google Task as completed.",
    parameters={
        "type": "object",
        "properties": {
            **_TASKLIST_ID_PARAM,
            "task_id": {"type": "string", "description": "Task ID to complete."},
        },
        "required": ["task_id"],
    },
    handler=_complete_task_handler,
    tags=("google", "tasks", "write"),
    parallel_safe=False,
    examples=("mark task done", "complete todo", "отметить задачу выполненной"),
)

GOOGLE_TASKS_GET_TASKLIST = ToolSpec(
    name="google.tasks.get_tasklist",
    description=GOOGLE_TASKS_OAUTH_HINT + "Get metadata for one Google Tasks list by ID.",
    parameters={
        "type": "object",
        "properties": {
            "tasklist_id": {
                "type": "string",
                "description": "Google Tasks list ID.",
            }
        },
        "required": ["tasklist_id"],
    },
    handler=_get_tasklist_handler,
    tags=("google", "tasks", "read", "tasklists"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    examples=("get task list details", "show shopping list metadata"),
)

GOOGLE_TASKS_UPDATE_TASK = ToolSpec(
    name="google.tasks.update_task",
    description=(
        GOOGLE_TASKS_OAUTH_HINT
        + "Fully replace a Google Task (omitted fields are cleared). Prefer patch_task for partial edits."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_TASKLIST_ID_PARAM,
            **_TASK_ID_PARAM,
            "title": {"type": "string"},
            "notes": {"type": "string"},
            "due": {"type": "string", "description": "YYYY-MM-DD or ISO datetime."},
            "status": {"type": "string", "enum": ["needsAction", "completed"]},
        },
        "required": ["task_id"],
    },
    handler=_update_task_handler,
    tags=("google", "tasks", "write"),
    parallel_safe=False,
    examples=("replace task title and notes", "update todo fully"),
)

GOOGLE_TASKS_PATCH_TASK = ToolSpec(
    name="google.tasks.patch_task",
    description=GOOGLE_TASKS_OAUTH_HINT + "Partially update a Google Task (title, notes, due, or status).",
    parameters={
        "type": "object",
        "properties": {
            **_TASKLIST_ID_PARAM,
            **_TASK_ID_PARAM,
            "title": {"type": "string"},
            "notes": {"type": "string"},
            "due": {"type": "string", "description": "YYYY-MM-DD or ISO datetime."},
            "status": {"type": "string", "enum": ["needsAction", "completed"]},
        },
        "required": ["task_id"],
    },
    handler=_patch_task_handler,
    tags=("google", "tasks", "write"),
    parallel_safe=False,
    examples=("rename task", "change due date", "mark task incomplete"),
)

GOOGLE_TASKS_DELETE_TASK = ToolSpec(
    name="google.tasks.delete_task",
    description=GOOGLE_TASKS_OAUTH_HINT + "Delete a Google Task permanently from a task list.",
    parameters={
        "type": "object",
        "properties": {**_TASKLIST_ID_PARAM, **_TASK_ID_PARAM},
        "required": ["task_id"],
    },
    handler=_delete_task_handler,
    tags=("google", "tasks", "write"),
    parallel_safe=False,
    examples=("delete todo", "remove task"),
)

GOOGLE_TASKS_MOVE_TASK = ToolSpec(
    name="google.tasks.move_task",
    description=(
        GOOGLE_TASKS_OAUTH_HINT
        + "Move a task within or between lists; optionally set parent/previous for subtasks and ordering."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_TASKLIST_ID_PARAM,
            **_TASK_ID_PARAM,
            "destination_tasklist_id": {
                "type": "string",
                "description": "Move to another list. Omit to reorder within the current list.",
            },
            "parent": {"type": "string", "description": "Parent task ID to nest as subtask."},
            "previous": {"type": "string", "description": "Previous sibling task ID for ordering."},
        },
        "required": ["task_id"],
    },
    handler=_move_task_handler,
    tags=("google", "tasks", "write", "subtasks"),
    parallel_safe=False,
    examples=("move task to shopping list", "make subtask", "reorder tasks"),
)

GOOGLE_TASKS_SEARCH_TASKS = ToolSpec(
    name="google.tasks.search_tasks",
    description=(
        GOOGLE_TASKS_OAUTH_HINT
        + "Search Google Tasks by title or notes. Searches all lists unless tasklist_id is set."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Case-insensitive substring to match."},
            **_TASKLIST_ID_PARAM,
            "include_completed": {"type": "boolean", "default": False},
            "max_results": {"type": "integer", "default": 20},
        },
        "required": ["query"],
    },
    handler=_search_tasks_handler,
    tags=("google", "tasks", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    examples=("find task milk", "search todos about report"),
)

GOOGLE_TASKS_LIST_SUBTASKS = ToolSpec(
    name="google.tasks.list_subtasks",
    description=GOOGLE_TASKS_OAUTH_HINT + "List subtasks under a parent Google Task.",
    parameters={
        "type": "object",
        "properties": {
            **_TASKLIST_ID_PARAM,
            "parent_task_id": {"type": "string", "description": "Parent task ID."},
            "include_completed": {"type": "boolean", "default": False},
        },
        "required": ["parent_task_id"],
    },
    handler=_list_subtasks_handler,
    tags=("google", "tasks", "read", "subtasks"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    examples=("list subtasks", "show checklist items"),
)

GOOGLE_TASKS_LIST_ALL_OPEN_TASKS = ToolSpec(
    name="google.tasks.list_all_open_tasks",
    description=GOOGLE_TASKS_OAUTH_HINT + "List open tasks across all Google Tasks lists.",
    parameters={
        "type": "object",
        "properties": {
            "max_results_per_list": {"type": "integer", "default": 30},
            "max_total": {"type": "integer", "default": 50},
        },
    },
    handler=_list_all_open_tasks_handler,
    tags=("google", "tasks", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    examples=("all my open todos", "tasks everywhere"),
)

GOOGLE_TASKS_UNCOMPLETE_TASK = ToolSpec(
    name="google.tasks.uncomplete_task",
    description=GOOGLE_TASKS_OAUTH_HINT + "Mark a completed Google Task as needsAction (reopen).",
    parameters={
        "type": "object",
        "properties": {**_TASKLIST_ID_PARAM, **_TASK_ID_PARAM},
        "required": ["task_id"],
    },
    handler=_uncomplete_task_handler,
    tags=("google", "tasks", "write"),
    parallel_safe=False,
    examples=("reopen task", "mark todo not done", "uncomplete task"),
)

GOOGLE_TASKS_CREATE_TASKLIST = ToolSpec(
    name="google.tasks.create_tasklist",
    description=GOOGLE_TASKS_OAUTH_HINT + "Create a new Google Tasks list.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Task list title (required)."},
        },
        "required": ["title"],
    },
    handler=_create_tasklist_handler,
    tags=("google", "tasks", "write", "tasklists"),
    parallel_safe=False,
    examples=("create shopping list", "new tasks list", "создай список покупок"),
)

GOOGLE_TASKS_UPDATE_TASKLIST = ToolSpec(
    name="google.tasks.update_tasklist",
    description=GOOGLE_TASKS_OAUTH_HINT + "Rename a Google Tasks list (full update).",
    parameters={
        "type": "object",
        "properties": {
            "tasklist_id": {
                "type": "string",
                "description": "Google Tasks list ID.",
            },
            "title": {"type": "string", "description": "New list title."},
        },
        "required": ["tasklist_id", "title"],
    },
    handler=_update_tasklist_handler,
    tags=("google", "tasks", "write", "tasklists"),
    parallel_safe=False,
    examples=("rename task list", "update list title"),
)

GOOGLE_TASKS_PATCH_TASKLIST = ToolSpec(
    name="google.tasks.patch_tasklist",
    description=GOOGLE_TASKS_OAUTH_HINT + "Partially update a Google Tasks list (title).",
    parameters={
        "type": "object",
        "properties": {
            "tasklist_id": {
                "type": "string",
                "description": "Google Tasks list ID.",
            },
            "title": {"type": "string", "description": "New list title."},
        },
        "required": ["tasklist_id"],
    },
    handler=_patch_tasklist_handler,
    tags=("google", "tasks", "write", "tasklists"),
    parallel_safe=False,
    examples=("rename tasks list", "patch list title"),
)

GOOGLE_TASKS_DELETE_TASKLIST = ToolSpec(
    name="google.tasks.delete_tasklist",
    description=(
        GOOGLE_TASKS_OAUTH_HINT
        + "Delete a Google Tasks list and all its tasks (requires confirm=true)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "tasklist_id": {
                "type": "string",
                "description": "Google Tasks list ID.",
            },
            **_CONFIRM_PARAM,
        },
        "required": ["tasklist_id", "confirm"],
    },
    handler=_delete_tasklist_handler,
    tags=("google", "tasks", "write", "tasklists"),
    parallel_safe=False,
    examples=("delete task list", "remove shopping list"),
)

GOOGLE_TASKS_CLEAR_COMPLETED = ToolSpec(
    name="google.tasks.clear_completed",
    description=(
        GOOGLE_TASKS_OAUTH_HINT
        + "Hide all completed tasks in a list (requires confirm=true). Does not delete active tasks."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_TASKLIST_ID_PARAM,
            **_CONFIRM_PARAM,
        },
        "required": ["confirm"],
    },
    handler=_clear_completed_handler,
    tags=("google", "tasks", "write"),
    parallel_safe=False,
    examples=("clear completed tasks", "hide done todos"),
)

GOOGLE_TASKS_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_TASKS_LIST_TASKLISTS,
    GOOGLE_TASKS_GET_TASKLIST,
    GOOGLE_TASKS_CREATE_TASKLIST,
    GOOGLE_TASKS_UPDATE_TASKLIST,
    GOOGLE_TASKS_PATCH_TASKLIST,
    GOOGLE_TASKS_DELETE_TASKLIST,
    GOOGLE_TASKS_LIST_TASKS,
    GOOGLE_TASKS_GET_TASK,
    GOOGLE_TASKS_CREATE_TASK,
    GOOGLE_TASKS_UPDATE_TASK,
    GOOGLE_TASKS_PATCH_TASK,
    GOOGLE_TASKS_DELETE_TASK,
    GOOGLE_TASKS_MOVE_TASK,
    GOOGLE_TASKS_CLEAR_COMPLETED,
    GOOGLE_TASKS_LIST_DEFAULT_TASKS,
    GOOGLE_TASKS_LIST_TODAY,
    GOOGLE_TASKS_LIST_OVERDUE,
    GOOGLE_TASKS_LIST_UPCOMING,
    GOOGLE_TASKS_SEARCH_TASKS,
    GOOGLE_TASKS_LIST_SUBTASKS,
    GOOGLE_TASKS_LIST_ALL_OPEN_TASKS,
    GOOGLE_TASKS_QUICK_ADD_TASK,
    GOOGLE_TASKS_COMPLETE_TASK,
    GOOGLE_TASKS_UNCOMPLETE_TASK,
)
