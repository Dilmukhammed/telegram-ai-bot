from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from aiogram.types import InlineKeyboardMarkup

from agent.inline_button_layout import build_url_button_markup
from agent.maps_button_urls import (
    TOOL_INGEST_URL_KEYS,
    button_sort_key,
    group_key_for_button_url,
    is_maps_button_candidate,
    label_for_maps_tool,
    normalize_maps_button_url,
)
from agent.maps_link_providers import resolve_route_button_url
from agent.tool_links_appendix import LinkSource, select_button_links, select_details_links
from config import get_settings
from rich_format import strip_maps_button_urls
from tools.builtins.google.maps_urls import is_google_maps_url
from tools.builtins.yandex.maps_urls import is_yandex_maps_url

_GOOGLE_MAPS_URL_RE = re.compile(
    r"https?://(?:www\.)?google\.com/maps/"
    r"(?:[^\s<>\"'\)\]]|&(?:amp|#\d+|#x[\da-fA-F]+);)+",
    re.IGNORECASE,
)
_GOOGLE_MAPS_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https?://(?:www\.)?google\.com/maps/[^)]+)\)",
    re.IGNORECASE,
)
_YANDEX_MAPS_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https?://(?:[^\s/]+\.)?yandex\.(?:ru|com|uz|by|kz|ua)/maps/[^)]+)\)",
    re.IGNORECASE,
)
_YANDEX_MAPS_ROUTE_URL_RE = re.compile(
    r"https?://(?:[^\s/]+\.)?yandex\.(?:ru|com|uz|by|kz|ua)/maps/\?"
    r"(?:[^\s<>\"'\)\]]|&(?:amp|#\d+|#x[\da-fA-F]+);)*"
    r"rtext=(?:[^\s<>\"'\)\]]|&(?:amp|#\d+|#x[\da-fA-F]+);)+",
    re.IGNORECASE,
)


def build_maps_reply_markup(buttons: tuple[tuple[str, str], ...]) -> InlineKeyboardMarkup | None:
    return build_url_button_markup(buttons[:5])


@dataclass
class MapsLink:
    url: str
    label: str
    group_key: str
    source: LinkSource = "tool"


@dataclass
class MapsLinkCollector:
    _links: list[MapsLink] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)

    def _replace_group(self, group_key: str) -> None:
        for existing in self._links:
            if existing.group_key == group_key:
                self._seen.discard(existing.url)
                break
        self._links = [link for link in self._links if link.group_key != group_key]

    def add(
        self,
        url: str | None,
        *,
        label: str | None = None,
        tool_name: str | None = None,
        travel_mode: str | None = None,
        origin: str | None = None,
        destination: str | None = None,
        source: LinkSource = "tool",
    ) -> None:
        if not url:
            return

        url_str = normalize_maps_button_url(url)
        if not is_maps_button_candidate(url_str):
            return

        settings = get_settings()
        if is_google_maps_url(url_str):
            normalized = normalize_maps_button_url(
                resolve_route_button_url(
                    url_str,
                    origin=origin,
                    destination=destination,
                    travel_mode=travel_mode,
                    transit_link_provider=settings.maps_transit_link_provider,
                )
            )
        elif is_yandex_maps_url(url_str):
            normalized = url_str
        else:
            normalized = url_str

        if not is_maps_button_candidate(normalized):
            return

        resolved_label = label or label_for_maps_tool(
            tool_name or "",
            {},
            url=normalized,
            travel_mode=travel_mode,
        )
        group_key = group_key_for_button_url(
            normalized,
            tool_name=tool_name,
            travel_mode=travel_mode,
            origin=origin,
            destination=destination,
        )

        for existing in self._links:
            if existing.group_key == group_key:
                self._seen.discard(existing.url)
                break
        self._links = [link for link in self._links if link.group_key != group_key]

        if normalized in self._seen:
            if source == "text":
                promoted = False
                for existing in self._links:
                    if existing.url == normalized and existing.source == "tool":
                        self._replace_group(existing.group_key)
                        self._seen.discard(normalized)
                        promoted = True
                        break
                if not promoted:
                    return
            else:
                return

        if source == "text":
            text_count = sum(1 for link in self._links if link.source == "text")
            if text_count >= 5:
                return

        self._seen.add(normalized)
        self._links.append(
            MapsLink(url=normalized, label=resolved_label, group_key=group_key, source=source)
        )

    def ingest_tool_result_json(self, result_json: str) -> None:
        try:
            payload = json.loads(result_json)
        except json.JSONDecodeError:
            return
        if not payload.get("ok"):
            return

        tool_name = str(payload.get("tool_name") or "")
        if not tool_name.startswith("google.maps."):
            return

        result = payload.get("result") or {}
        travel_mode = result.get("travel_mode")
        origin = result.get("origin")
        destination = result.get("destination")
        for key in TOOL_INGEST_URL_KEYS:
            if key not in result:
                continue
            url = str(result.get(key) or "")
            self.add(
                url,
                label=label_for_maps_tool(tool_name, result, url=url, travel_mode=travel_mode),
                tool_name=tool_name,
                travel_mode=travel_mode,
                origin=origin,
                destination=destination,
            )

    def ingest_from_text(self, text: str) -> None:
        markdown_labels: dict[str, str] = {}
        for pattern in (_GOOGLE_MAPS_MARKDOWN_LINK_RE, _YANDEX_MAPS_MARKDOWN_LINK_RE):
            for match in pattern.finditer(text):
                label = " ".join(match.group(1).split()).strip()
                url = normalize_maps_button_url(match.group(2))
                if url and label:
                    markdown_labels[url] = label

        seen_in_text: set[str] = set()
        for pattern in (
            _GOOGLE_MAPS_MARKDOWN_LINK_RE,
            _YANDEX_MAPS_MARKDOWN_LINK_RE,
            _GOOGLE_MAPS_URL_RE,
            _YANDEX_MAPS_ROUTE_URL_RE,
        ):
            for match in pattern.finditer(text):
                if pattern in (_GOOGLE_MAPS_MARKDOWN_LINK_RE, _YANDEX_MAPS_MARKDOWN_LINK_RE):
                    url = normalize_maps_button_url(match.group(2))
                else:
                    url = normalize_maps_button_url(match.group(0))
                if not url or url in seen_in_text:
                    continue
                seen_in_text.add(url)
                self.add(
                    url,
                    label=markdown_labels.get(url),
                    source="text",
                )

    @property
    def items(self) -> list[MapsLink]:
        return list(self._links)

    def _sort_key(self, link: MapsLink) -> tuple[int, str]:
        return button_sort_key(link.group_key, link.label)

    def buttons(self) -> tuple[tuple[str, str], ...]:
        return select_button_links(self._links, max_buttons=5, sort_key=self._sort_key)

    def details_items(self) -> list[MapsLink]:
        return select_details_links(self._links, sort_key=self._sort_key)


def finalize_maps_text(reply: str, collector: MapsLinkCollector) -> str:
    if collector.buttons():
        reply = strip_maps_button_urls(reply)
    return reply.rstrip()
