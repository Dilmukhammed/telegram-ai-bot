from __future__ import annotations

from typing import Any

from tools.builtins.google.tasks_urls import (
    is_tasks_task_url,
    label_for_task,
    label_for_tasks_url,
    normalize_tasks_url,
    parse_task_id_from_url,
    truncate_tasks_button_label,
)

TASKS_MAX_BUTTONS = 5

TOOL_INGEST_URL_KEYS: tuple[str, ...] = ("webViewLink",)


def group_key_for_tasks_url(url: str) -> str:
    normalized = normalize_tasks_url(url)
    task_id = parse_task_id_from_url(normalized)
    if task_id:
        return f"task:{task_id}"
    return f"url:{normalized}"


def group_key_for_task_id(task_id: str | None) -> str:
    task_id = str(task_id or "").strip()
    if task_id:
        return f"task:{task_id}"
    return "task:unknown"


def label_for_tasks_tool(
    tool_name: str,
    result: dict[str, Any],
    *,
    url: str = "",
    title: str | None = None,
) -> str:
    if title and str(title).strip():
        return truncate_tasks_button_label(str(title).strip())

    task = result.get("task")
    if isinstance(task, dict):
        task_title = task.get("title")
        if task_title and str(task_title).strip():
            return truncate_tasks_button_label(str(task_title).strip())

    if tool_name in {
        "google.tasks.create_task",
        "google.tasks.quick_add_task",
    }:
        return "Открыть новую задачу"
    if tool_name in {
        "google.tasks.patch_task",
        "google.tasks.update_task",
        "google.tasks.move_task",
        "google.tasks.complete_task",
        "google.tasks.uncomplete_task",
    }:
        return "Открыть задачу"
    if tool_name == "google.tasks.get_task":
        return "Открыть задачу"
    if tool_name in {
        "google.tasks.list_tasks",
        "google.tasks.list_default_tasks",
        "google.tasks.list_today",
        "google.tasks.list_overdue",
        "google.tasks.list_upcoming",
        "google.tasks.search_tasks",
        "google.tasks.list_subtasks",
        "google.tasks.list_all_open_tasks",
    }:
        return label_for_task(title=title)

    if url and is_tasks_task_url(url):
        return label_for_tasks_url(url)
    return "Открыть Tasks"


def button_sort_key(group_key: str, label: str) -> tuple[int, str]:
    kind_order = {"task": 0, "url": 1}
    prefix = group_key.split(":", 1)[0]
    return (kind_order.get(prefix, 9), label.casefold())
