from __future__ import annotations

from typing import Any

from tools.builtins.google.tasks_datetime import normalize_task_due

MAX_NOTES_CHARS = 2000


def _truncate(text: str | None, *, max_len: int) -> str | None:
    if text is None:
        return None
    cleaned = str(text)
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def compact_tasklist(tasklist: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": tasklist.get("id"),
        "title": tasklist.get("title"),
        "updated": tasklist.get("updated"),
    }


def compact_task(task: dict[str, Any], *, max_notes_chars: int = MAX_NOTES_CHARS) -> dict[str, Any]:
    links = task.get("links") or []
    compact_links = [
        {
            "type": link.get("type"),
            "description": link.get("description"),
            "link": link.get("link"),
        }
        for link in links
        if isinstance(link, dict)
    ]
    assignment = task.get("assignmentInfo")
    compact_assignment = None
    if isinstance(assignment, dict):
        compact_assignment = {
            "linkToTask": assignment.get("linkToTask"),
            "surfaceType": assignment.get("surfaceType"),
        }

    payload: dict[str, Any] = {
        "id": task.get("id"),
        "title": task.get("title"),
        "status": task.get("status"),
        "due": task.get("due"),
        "completed": task.get("completed"),
        "updated": task.get("updated"),
        "parent": task.get("parent"),
        "webViewLink": task.get("webViewLink"),
    }
    notes = _truncate(task.get("notes"), max_len=max_notes_chars)
    if notes:
        payload["notes"] = notes
    if compact_links:
        payload["links"] = compact_links
    if compact_assignment:
        payload["assignmentInfo"] = compact_assignment
    if task.get("deleted"):
        payload["deleted"] = True
    if task.get("hidden"):
        payload["hidden"] = True
    return payload


def build_task_patch_body(arguments: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if arguments.get("title") is not None:
        title = str(arguments["title"]).strip()
        if not title:
            raise ValueError("title cannot be empty")
        body["title"] = title
    if arguments.get("notes") is not None:
        body["notes"] = str(arguments["notes"])
    if arguments.get("due") is not None:
        body["due"] = normalize_task_due(str(arguments["due"]))
    if arguments.get("status") is not None:
        body["status"] = str(arguments["status"])
    if not body:
        raise ValueError("Provide at least one field to patch")
    return body


def merge_task_for_update(existing: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    title = arguments.get("title", existing.get("title"))
    if title is not None:
        title = str(title).strip()
    if not title:
        raise ValueError("title is required for update_task")

    body: dict[str, Any] = {
        "id": existing.get("id"),
        "title": title,
        "status": arguments.get("status", existing.get("status", "needsAction")),
    }
    if arguments.get("notes") is not None:
        body["notes"] = str(arguments["notes"])
    elif existing.get("notes") is not None:
        body["notes"] = existing["notes"]
    if arguments.get("due") is not None:
        body["due"] = normalize_task_due(str(arguments["due"]))
    elif existing.get("due") is not None:
        body["due"] = existing["due"]
    if existing.get("parent"):
        body["parent"] = existing["parent"]
    if existing.get("completed") is not None and body["status"] == "completed":
        body["completed"] = existing["completed"]
    return body


def merge_tasklist_for_update(existing: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    title = arguments.get("title", existing.get("title"))
    title = str(title or "").strip()
    if not title:
        raise ValueError("title is required for update_tasklist")
    return {"id": existing.get("id"), "title": title}


def build_tasklist_patch_body(arguments: dict[str, Any]) -> dict[str, Any]:
    if arguments.get("title") is None:
        raise ValueError("Provide title to patch_tasklist")
    title = str(arguments["title"]).strip()
    if not title:
        raise ValueError("title cannot be empty")
    return {"title": title}
