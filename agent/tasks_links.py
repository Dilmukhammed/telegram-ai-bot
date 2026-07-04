from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from agent.tasks_button_urls import (
    TASKS_MAX_BUTTONS,
    TOOL_INGEST_URL_KEYS,
    button_sort_key,
    group_key_for_task_id,
    group_key_for_tasks_url,
    label_for_tasks_tool,
)
from agent.tool_links_appendix import LinkSource, select_button_links, select_details_links
from rich_format import strip_tasks_button_urls
from tools.builtins.google.tasks_urls import (
    is_tasks_url,
    iter_tasks_urls_in_text,
    label_for_tasks_url,
    normalize_tasks_url,
)

_TASKS_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((https?://tasks\.google\.com[^)]+)\)",
    re.IGNORECASE,
)


@dataclass
class TasksLink:
    url: str
    label: str
    group_key: str
    source: LinkSource = "tool"


@dataclass
class TasksLinkCollector:
    _links: list[TasksLink] = field(default_factory=list)
    _seen_urls: set[str] = field(default_factory=set)

    def _replace_group(self, group_key: str) -> None:
        for existing in self._links:
            if existing.group_key == group_key:
                self._seen_urls.discard(existing.url)
                break
        self._links = [link for link in self._links if link.group_key != group_key]

    def _add(
        self,
        *,
        url: str,
        label: str,
        group_key: str,
        source: LinkSource = "tool",
    ) -> None:
        normalized = normalize_tasks_url(url)
        if not normalized or not is_tasks_url(normalized):
            return

        self._replace_group(group_key)
        if normalized in self._seen_urls:
            return

        if source == "text":
            text_count = sum(1 for link in self._links if link.source == "text")
            if text_count >= TASKS_MAX_BUTTONS:
                return

        self._seen_urls.add(normalized)
        self._links.append(
            TasksLink(url=normalized, label=label, group_key=group_key, source=source)
        )

    def _ingest_record(
        self,
        *,
        tool_name: str,
        result: dict[str, Any],
        url: str | None,
        title: str | None = None,
        task_id: str | None = None,
        label: str | None = None,
    ) -> None:
        normalized = normalize_tasks_url(url)
        if not normalized:
            return
        resolved_label = label or label_for_tasks_tool(
            tool_name,
            result,
            url=normalized,
            title=title,
        )
        group_key = group_key_for_task_id(task_id) if task_id else group_key_for_tasks_url(normalized)
        self._add(url=normalized, label=resolved_label, group_key=group_key)

    def _ingest_task_object(
        self,
        *,
        tool_name: str,
        result: dict[str, Any],
        task: dict[str, Any],
    ) -> None:
        assignment = task.get("assignmentInfo")
        if isinstance(assignment, dict):
            link = assignment.get("linkToTask")
            if link:
                self._ingest_record(
                    tool_name=tool_name,
                    result=result,
                    url=str(link),
                    title=task.get("title"),
                    task_id=str(task.get("id") or ""),
                )
        self._ingest_record(
            tool_name=tool_name,
            result=result,
            url=str(task.get("webViewLink") or ""),
            title=task.get("title"),
            task_id=str(task.get("id") or ""),
        )

    def ingest_tool_result_json(self, result_json: str) -> None:
        try:
            payload = json.loads(result_json)
        except json.JSONDecodeError:
            return
        if not payload.get("ok"):
            return

        tool_name = str(payload.get("tool_name") or "")
        if not tool_name.startswith("google.tasks."):
            return

        result = payload.get("result") or {}
        if not isinstance(result, dict):
            return

        for key in TOOL_INGEST_URL_KEYS:
            if key not in result or not result.get(key):
                continue
            self._ingest_record(
                tool_name=tool_name,
                result=result,
                url=str(result.get(key) or ""),
            )

        task = result.get("task")
        if isinstance(task, dict):
            self._ingest_task_object(tool_name=tool_name, result=result, task=task)

        for item in result.get("tasks") or []:
            if not isinstance(item, dict):
                continue
            self._ingest_task_object(tool_name=tool_name, result=result, task=item)

    def ingest_from_text(self, text: str) -> None:
        markdown_labels: dict[str, str] = {}
        for match in _TASKS_MARKDOWN_LINK_RE.finditer(text):
            label = " ".join(match.group(1).split()).strip()
            url = normalize_tasks_url(match.group(2))
            if url and label:
                markdown_labels[url] = label

        for url in iter_tasks_urls_in_text(text):
            self._add(
                url=url,
                label=markdown_labels.get(url) or label_for_tasks_url(url),
                group_key=group_key_for_tasks_url(url),
                source="text",
            )

    @property
    def items(self) -> list[TasksLink]:
        return list(self._links)

    def _sort_key(self, link: TasksLink) -> tuple[int, str]:
        return button_sort_key(link.group_key, link.label)

    def buttons(self) -> tuple[tuple[str, str], ...]:
        return select_button_links(
            self._links,
            max_buttons=TASKS_MAX_BUTTONS,
            sort_key=self._sort_key,
        )

    def details_items(self) -> list[TasksLink]:
        return select_details_links(self._links, sort_key=self._sort_key)


def finalize_tasks_text(reply: str, collector: TasksLinkCollector) -> str:
    if collector.buttons():
        reply = strip_tasks_button_urls(reply)
    return reply.rstrip()
