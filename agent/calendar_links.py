from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from agent.calendar_button_urls import (
    CALENDAR_MAX_BUTTONS,
    TOOL_INGEST_URL_KEYS,
    button_sort_key,
    group_key_for_calendar_url,
    label_for_calendar_tool,
)
from agent.tool_links_appendix import LinkSource, select_button_links, select_details_links
from rich_format import strip_calendar_button_urls
from tools.builtins.google.calendar_urls import (
    is_calendar_url,
    iter_calendar_urls_in_text,
    label_for_calendar_url,
    normalize_calendar_url,
)

_CALENDAR_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((https?://(?:www\.)?(?:calendar\.google\.com|google\.com/calendar)[^)]+)\)",
    re.IGNORECASE,
)


@dataclass
class CalendarLink:
    url: str
    label: str
    group_key: str
    source: LinkSource = "tool"


@dataclass
class CalendarLinkCollector:
    _links: list[CalendarLink] = field(default_factory=list)
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
        normalized = normalize_calendar_url(url)
        if not normalized or not is_calendar_url(normalized):
            return

        self._replace_group(group_key)
        if normalized in self._seen_urls:
            return

        if source == "text":
            text_count = sum(1 for link in self._links if link.source == "text")
            if text_count >= CALENDAR_MAX_BUTTONS:
                return

        self._seen_urls.add(normalized)
        self._links.append(
            CalendarLink(url=normalized, label=label, group_key=group_key, source=source)
        )

    def _ingest_record(
        self,
        *,
        tool_name: str,
        result: dict[str, Any],
        url: str | None,
        summary: str | None = None,
        label: str | None = None,
    ) -> None:
        normalized = normalize_calendar_url(url)
        if not normalized:
            return
        resolved_label = label or label_for_calendar_tool(
            tool_name,
            result,
            url=normalized,
            summary=summary,
        )
        self._add(
            url=normalized,
            label=resolved_label,
            group_key=group_key_for_calendar_url(normalized),
        )

    def ingest_tool_result_json(self, result_json: str) -> None:
        try:
            payload = json.loads(result_json)
        except json.JSONDecodeError:
            return
        if not payload.get("ok"):
            return

        tool_name = str(payload.get("tool_name") or "")
        if not tool_name.startswith("google.calendar."):
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

        event = result.get("event")
        if isinstance(event, dict):
            self._ingest_record(
                tool_name=tool_name,
                result=result,
                url=str(event.get("htmlLink") or ""),
                summary=event.get("summary"),
            )

        for item in result.get("events") or []:
            if not isinstance(item, dict):
                continue
            self._ingest_record(
                tool_name=tool_name,
                result=result,
                url=str(item.get("htmlLink") or ""),
                summary=item.get("summary"),
            )

    def ingest_from_text(self, text: str) -> None:
        markdown_labels: dict[str, str] = {}
        for match in _CALENDAR_MARKDOWN_LINK_RE.finditer(text):
            label = " ".join(match.group(1).split()).strip()
            url = normalize_calendar_url(match.group(2))
            if url and label:
                markdown_labels[url] = label

        for url in iter_calendar_urls_in_text(text):
            self._add(
                url=url,
                label=markdown_labels.get(url) or label_for_calendar_url(url),
                group_key=group_key_for_calendar_url(url),
                source="text",
            )

    @property
    def items(self) -> list[CalendarLink]:
        return list(self._links)

    def _sort_key(self, link: CalendarLink) -> tuple[int, str]:
        return button_sort_key(link.group_key, link.label)

    def buttons(self) -> tuple[tuple[str, str], ...]:
        return select_button_links(
            self._links,
            max_buttons=CALENDAR_MAX_BUTTONS,
            sort_key=self._sort_key,
        )

    def details_items(self) -> list[CalendarLink]:
        return select_details_links(self._links, sort_key=self._sort_key)


def finalize_calendar_text(reply: str, collector: CalendarLinkCollector) -> str:
    if collector.buttons():
        reply = strip_calendar_button_urls(reply)
    return reply.rstrip()
