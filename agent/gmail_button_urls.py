from __future__ import annotations

from typing import Any

from tools.builtins.google.gmail_urls import (
    label_for_gmail_url,
    normalize_gmail_url,
    truncate_gmail_button_label,
)

GMAIL_MAX_BUTTONS = 5
MAX_COMBINED_INLINE_BUTTONS = 5


def group_key_for_gmail_url(url: str) -> str:
    normalized = normalize_gmail_url(url)
    return f"url:{normalized}"


def group_key_for_thread(thread_id: str) -> str:
    return f"thread:{str(thread_id).strip()}"


def label_for_thread(*, subject: str | None = None, snippet: str | None = None) -> str:
    text = (subject or snippet or "").strip()
    if text:
        return truncate_gmail_button_label(text)
    return label_for_gmail_url("")


def label_for_gmail_tool(
    tool_name: str,
    result: dict[str, Any],
    *,
    subject: str | None = None,
    snippet: str | None = None,
) -> str:
    if subject and str(subject).strip():
        return truncate_gmail_button_label(str(subject).strip())
    if snippet and str(snippet).strip():
        return truncate_gmail_button_label(str(snippet).strip())

    if tool_name == "google.gmail.search_messages":
        return "Результаты поиска Gmail"
    if tool_name == "google.gmail.list_threads":
        return "Открыть переписку"
    if "draft" in tool_name:
        draft_subject = result.get("subject")
        if draft_subject and str(draft_subject).strip():
            return truncate_gmail_button_label(f"Черновик: {draft_subject}")
        return "Открыть черновик"
    if tool_name in {"google.gmail.send_message", "google.gmail.reply_to_message", "google.gmail.forward_message"}:
        return "Открыть отправленное"
    if tool_name == "google.gmail.get_thread":
        return "Открыть переписку"
    return label_for_gmail_url("")


def button_sort_key(group_key: str, label: str) -> tuple[int, str]:
    kind_order = {"thread": 0, "search": 1, "url": 2}
    prefix = group_key.split(":", 1)[0]
    return (kind_order.get(prefix, 9), label.casefold())
