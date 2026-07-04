from __future__ import annotations

import html
import re
from urllib.parse import unquote, urlparse

_TASKS_URL_RE = re.compile(
    r"https?://tasks\.google\.com[^\s<>\"'\)\]]*",
    re.IGNORECASE,
)
_TASKS_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((https?://tasks\.google\.com[^)]+)\)",
    re.IGNORECASE,
)
_TASKS_HTML_ANCHOR_RE = re.compile(
    r'<a\s+[^>]*href="(https?://tasks\.google\.com[^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def normalize_tasks_url(url: str | None) -> str:
    if not url:
        return ""
    return html.unescape(str(url).strip())


def is_tasks_url(url: str | None) -> bool:
    if not url:
        return False
    return "tasks.google.com" in normalize_tasks_url(url).lower()


def is_tasks_task_url(url: str | None) -> bool:
    normalized = normalize_tasks_url(url)
    if not normalized or not is_tasks_url(normalized):
        return False
    lowered = normalized.lower()
    return "/task/" in lowered or "/tasks/" in lowered


def parse_task_id_from_url(url: str) -> str | None:
    normalized = normalize_tasks_url(url)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    path = parsed.path.strip("/")
    if not path:
        return None
    parts = path.split("/")
    if "task" in parts:
        index = parts.index("task")
        if index + 1 < len(parts):
            task_id = parts[index + 1].split("?", 1)[0].strip()
            return unquote(task_id) if task_id else None
    if "tasks" in parts:
        index = parts.index("tasks")
        if index + 1 < len(parts):
            task_id = parts[index + 1].split("?", 1)[0].strip()
            return unquote(task_id) if task_id else None
    return None


def label_for_tasks_url(url: str) -> str:
    if is_tasks_task_url(url):
        return "Открыть задачу"
    return "Открыть Tasks"


def truncate_tasks_button_label(text: str, *, max_len: int = 40) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return "Открыть задачу"
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def label_for_task(*, title: str | None = None) -> str:
    text = str(title or "").strip()
    if text:
        return truncate_tasks_button_label(text)
    return "Открыть задачу"


def iter_tasks_urls_in_text(text: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (_TASKS_MARKDOWN_LINK_RE, _TASKS_HTML_ANCHOR_RE, _TASKS_URL_RE):
        for match in pattern.finditer(text):
            if pattern is _TASKS_MARKDOWN_LINK_RE:
                url = match.group(2)
            elif pattern is _TASKS_HTML_ANCHOR_RE:
                url = match.group(1)
            else:
                url = match.group(0)
            url = normalize_tasks_url(url)
            if not url or url in seen:
                continue
            seen.add(url)
            found.append(url)
    return found
