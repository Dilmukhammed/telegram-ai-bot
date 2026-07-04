from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from agent.gmail_button_urls import (
    GMAIL_MAX_BUTTONS,
    button_sort_key,
    group_key_for_gmail_url,
    group_key_for_thread,
    label_for_gmail_tool,
    label_for_thread,
)
from agent.tool_links_appendix import LinkSource, select_button_links, select_details_links
from rich_format import strip_gmail_button_urls
from tools.builtins.google.gmail_urls import (
    build_thread_url,
    is_gmail_url,
    iter_gmail_urls_in_text,
    label_for_gmail_url,
    normalize_gmail_url,
    parse_thread_id_from_url,
)

_GMAIL_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((https?://mail\.google\.com/mail[^)]+)\)",
    re.IGNORECASE,
)


@dataclass
class GmailLink:
    url: str
    label: str
    group_key: str
    source: LinkSource = "tool"


@dataclass
class GmailLinkCollector:
    _links: list[GmailLink] = field(default_factory=list)
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
        normalized = normalize_gmail_url(url)
        if not normalized or not is_gmail_url(normalized):
            return

        self._replace_group(group_key)
        if normalized in self._seen_urls:
            return

        if source == "text":
            text_count = sum(1 for link in self._links if link.source == "text")
            if text_count >= GMAIL_MAX_BUTTONS:
                return

        self._seen_urls.add(normalized)
        self._links.append(
            GmailLink(url=normalized, label=label, group_key=group_key, source=source)
        )

    def add_thread(
        self,
        thread_id: str | None,
        *,
        label: str | None = None,
        subject: str | None = None,
        snippet: str | None = None,
        tool_name: str | None = None,
        result: dict[str, Any] | None = None,
        source: LinkSource = "tool",
    ) -> None:
        thread_id = str(thread_id or "").strip()
        if not thread_id:
            return
        url = build_thread_url(thread_id)
        resolved_label = label
        if not resolved_label and tool_name and result is not None:
            resolved_label = label_for_gmail_tool(
                tool_name,
                result,
                subject=subject,
                snippet=snippet,
            )
        self._add(
            url=url,
            label=resolved_label or label_for_thread(subject=subject, snippet=snippet),
            group_key=group_key_for_thread(thread_id),
            source=source,
        )

    def add_url(self, url: str | None, *, label: str | None = None, source: LinkSource = "tool") -> None:
        normalized = normalize_gmail_url(url)
        if not normalized:
            return
        self._add(
            url=normalized,
            label=label or label_for_gmail_url(normalized),
            group_key=group_key_for_gmail_url(normalized),
            source=source,
        )

    def _ingest_thread_record(
        self,
        *,
        tool_name: str,
        result: dict[str, Any],
        thread_id: str | None,
        subject: str | None = None,
        snippet: str | None = None,
    ) -> None:
        self.add_thread(
            thread_id,
            subject=subject,
            snippet=snippet,
            tool_name=tool_name,
            result=result,
        )

    def ingest_tool_result_json(self, result_json: str) -> None:
        try:
            payload = json.loads(result_json)
        except json.JSONDecodeError:
            return
        if not payload.get("ok"):
            return

        tool_name = str(payload.get("tool_name") or "")
        if not tool_name.startswith("google.gmail."):
            return

        result = payload.get("result") or {}
        if not isinstance(result, dict):
            return

        thread_id = result.get("thread_id") or result.get("id")
        if thread_id and tool_name.endswith("get_thread"):
            self._ingest_thread_record(
                tool_name=tool_name,
                result=result,
                thread_id=str(thread_id),
                snippet=result.get("snippet"),
            )

        if thread_id and tool_name in {
            "google.gmail.send_message",
            "google.gmail.reply_to_message",
            "google.gmail.forward_message",
        }:
            self._ingest_thread_record(
                tool_name=tool_name,
                result=result,
                thread_id=str(thread_id),
                subject=result.get("subject"),
                snippet=result.get("snippet"),
            )

        for message in result.get("messages") or []:
            if not isinstance(message, dict):
                continue
            self._ingest_thread_record(
                tool_name=tool_name,
                result=result,
                thread_id=str(message.get("thread_id") or message.get("threadId") or ""),
                subject=message.get("subject"),
                snippet=message.get("snippet"),
            )

        for thread in result.get("threads") or []:
            if not isinstance(thread, dict):
                continue
            self._ingest_thread_record(
                tool_name=tool_name,
                result=result,
                thread_id=str(thread.get("id") or ""),
                snippet=thread.get("snippet"),
            )

        if thread_id and tool_name == "google.gmail.get_message":
            self._ingest_thread_record(
                tool_name=tool_name,
                result=result,
                thread_id=str(thread_id),
                subject=result.get("subject"),
                snippet=result.get("snippet"),
            )

    def ingest_from_text(self, text: str) -> None:
        markdown_labels: dict[str, str] = {}
        for match in _GMAIL_MARKDOWN_LINK_RE.finditer(text):
            label = " ".join(match.group(1).split()).strip()
            url = normalize_gmail_url(match.group(2))
            if url and label:
                markdown_labels[url] = label

        for url in iter_gmail_urls_in_text(text):
            label = markdown_labels.get(url)
            thread_id = parse_thread_id_from_url(url)
            if thread_id:
                self.add_thread(thread_id, label=label, source="text")
            else:
                self.add_url(url, label=label, source="text")

    @property
    def items(self) -> list[GmailLink]:
        return list(self._links)

    def _sort_key(self, link: GmailLink) -> tuple[int, str]:
        return button_sort_key(link.group_key, link.label)

    def buttons(self) -> tuple[tuple[str, str], ...]:
        return select_button_links(
            self._links,
            max_buttons=GMAIL_MAX_BUTTONS,
            sort_key=self._sort_key,
        )

    def details_items(self) -> list[GmailLink]:
        return select_details_links(self._links, sort_key=self._sort_key)


def finalize_gmail_text(reply: str, collector: GmailLinkCollector) -> str:
    if collector.buttons():
        reply = strip_gmail_button_urls(reply)
    return reply.rstrip()
