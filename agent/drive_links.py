from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from agent.drive_button_urls import (
    DRIVE_MAX_BUTTONS,
    TOOL_INGEST_URL_KEYS,
    button_sort_key,
    group_key_for_drive_url,
    label_for_drive_file,
    label_for_drive_tool,
)
from agent.tool_links_appendix import LinkSource, select_button_links, select_details_links
from rich_format import strip_drive_button_urls
from tools.builtins.google.drive_urls import (
    is_drive_url,
    iter_drive_urls_in_text,
    normalize_drive_url,
)
from tools.builtins.google.sheets_serialize import SPREADSHEET_MIME

_DRIVE_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((https?://(?:drive|docs|sheets|slides)\.google\.com[^)]+)\)",
    re.IGNORECASE,
)


@dataclass
class DriveLink:
    url: str
    label: str
    group_key: str
    source: LinkSource = "tool"


@dataclass
class DriveLinkCollector:
    _links: list[DriveLink] = field(default_factory=list)
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
        normalized = normalize_drive_url(url)
        if not normalized or not is_drive_url(normalized):
            return

        self._replace_group(group_key)
        if normalized in self._seen_urls:
            return

        if source == "text":
            text_count = sum(1 for link in self._links if link.source == "text")
            if text_count >= DRIVE_MAX_BUTTONS:
                return

        self._seen_urls.add(normalized)
        self._links.append(
            DriveLink(url=normalized, label=label, group_key=group_key, source=source)
        )

    def add(
        self,
        url: str | None,
        *,
        label: str | None = None,
        name: str | None = None,
        mime_type: str | None = None,
        title: str | None = None,
        source: LinkSource = "tool",
    ) -> None:
        normalized = normalize_drive_url(url)
        if not normalized:
            return
        resolved_label = label or label_for_drive_file(
            name=name,
            url=normalized,
            mime_type=mime_type,
            title=title,
        )
        self._add(
            url=normalized,
            label=resolved_label,
            group_key=group_key_for_drive_url(normalized, mime_type=mime_type),
            source=source,
        )

    def _ingest_record(
        self,
        *,
        tool_name: str,
        result: dict[str, Any],
        url: str | None,
        name: str | None = None,
        mime_type: str | None = None,
        title: str | None = None,
        label: str | None = None,
    ) -> None:
        normalized = normalize_drive_url(url)
        if not normalized:
            return
        resolved_label = label or label_for_drive_tool(
            tool_name,
            result,
            url=normalized,
            name=name,
            mime_type=mime_type,
            title=title,
        )
        self._add(
            url=normalized,
            label=resolved_label,
            group_key=group_key_for_drive_url(normalized, mime_type=mime_type),
        )

    def ingest_tool_result_json(self, result_json: str) -> None:
        try:
            payload = json.loads(result_json)
        except json.JSONDecodeError:
            return
        if not payload.get("ok"):
            return

        tool_name = str(payload.get("tool_name") or "")
        if not (tool_name.startswith("google.drive.") or tool_name.startswith("google.sheets.")):
            return

        result = payload.get("result") or {}
        if not isinstance(result, dict):
            return

        spreadsheet = result.get("spreadsheet")
        if isinstance(spreadsheet, dict):
            self._ingest_record(
                tool_name=tool_name,
                result=result,
                url=str(spreadsheet.get("url") or ""),
                title=spreadsheet.get("title"),
                mime_type=SPREADSHEET_MIME,
            )

        for key in TOOL_INGEST_URL_KEYS:
            if key not in result or not result.get(key):
                continue
            self._ingest_record(
                tool_name=tool_name,
                result=result,
                url=str(result.get(key) or ""),
                name=result.get("name"),
                mime_type=result.get("mime_type"),
                title=result.get("title"),
            )

        file_obj = result.get("file")
        if isinstance(file_obj, dict):
            self._ingest_record(
                tool_name=tool_name,
                result=result,
                url=str(file_obj.get("web_view_link") or file_obj.get("url") or ""),
                name=file_obj.get("name"),
                mime_type=file_obj.get("mime_type"),
            )

        for item in result.get("files") or []:
            if not isinstance(item, dict):
                continue
            self._ingest_record(
                tool_name=tool_name,
                result=result,
                url=str(item.get("web_view_link") or item.get("url") or ""),
                name=item.get("name"),
                mime_type=item.get("mime_type"),
            )

    def ingest_from_text(self, text: str) -> None:
        markdown_labels: dict[str, str] = {}
        for match in _DRIVE_MARKDOWN_LINK_RE.finditer(text):
            label = " ".join(match.group(1).split()).strip()
            url = normalize_drive_url(match.group(2))
            if url and label:
                markdown_labels[url] = label

        for url in iter_drive_urls_in_text(text):
            self.add(url, label=markdown_labels.get(url), source="text")

    @property
    def items(self) -> list[DriveLink]:
        return list(self._links)

    def _sort_key(self, link: DriveLink) -> tuple[int, str]:
        return button_sort_key(link.group_key, link.label)

    def buttons(self) -> tuple[tuple[str, str], ...]:
        return select_button_links(
            self._links,
            max_buttons=DRIVE_MAX_BUTTONS,
            sort_key=self._sort_key,
        )

    def details_items(self) -> list[DriveLink]:
        return select_details_links(self._links, sort_key=self._sort_key)


def finalize_drive_text(reply: str, collector: DriveLinkCollector) -> str:
    if collector.buttons():
        reply = strip_drive_button_urls(reply)
    return reply.rstrip()
