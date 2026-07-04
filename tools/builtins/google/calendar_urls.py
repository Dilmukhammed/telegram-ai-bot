from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, unquote, urlparse

_CALENDAR_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:calendar\.google\.com|google\.com/calendar)[^\s<>\"'\)\]]*",
    re.IGNORECASE,
)
_CALENDAR_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((https?://(?:www\.)?(?:calendar\.google\.com|google\.com/calendar)[^)]+)\)",
    re.IGNORECASE,
)
_CALENDAR_HTML_ANCHOR_RE = re.compile(
    r'<a\s+[^>]*href="(https?://(?:www\.)?(?:calendar\.google\.com|google\.com/calendar)[^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_EVENT_QUERY_KEYS = ("eid", "tmeid", "eventid")


def normalize_calendar_url(url: str | None) -> str:
    if not url:
        return ""
    return html.unescape(str(url).strip())


def is_calendar_url(url: str | None) -> bool:
    if not url:
        return False
    lowered = normalize_calendar_url(url).lower()
    return "calendar.google.com" in lowered or "google.com/calendar" in lowered


def is_calendar_event_url(url: str | None) -> bool:
    normalized = normalize_calendar_url(url)
    if not normalized or not is_calendar_url(normalized):
        return False
    lowered = normalized.lower()
    if "/event" in lowered or "action=template" in lowered:
        return True
    parsed = urlparse(normalized)
    query = parse_qs(parsed.query)
    return any(query.get(key) for key in _EVENT_QUERY_KEYS)


def parse_event_key_from_url(url: str) -> str | None:
    normalized = normalize_calendar_url(url)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    query = parse_qs(parsed.query)
    for key in _EVENT_QUERY_KEYS:
        values = query.get(key)
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    if "/event/" in normalized.lower():
        tail = normalized.rsplit("/event/", 1)[-1].split("?", 1)[0].strip("/")
        if tail:
            return unquote(tail)
    return None


def label_for_calendar_url(url: str) -> str:
    if is_calendar_event_url(url):
        return "Открыть событие"
    return "Открыть календарь"


def truncate_calendar_button_label(text: str, *, max_len: int = 40) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return "Открыть событие"
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def label_for_calendar_event(*, summary: str | None = None) -> str:
    text = str(summary or "").strip()
    if text:
        return truncate_calendar_button_label(text)
    return "Открыть событие"


def iter_calendar_urls_in_text(text: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (_CALENDAR_MARKDOWN_LINK_RE, _CALENDAR_HTML_ANCHOR_RE, _CALENDAR_URL_RE):
        for match in pattern.finditer(text):
            if pattern is _CALENDAR_MARKDOWN_LINK_RE:
                url = match.group(2)
            elif pattern is _CALENDAR_HTML_ANCHOR_RE:
                url = match.group(1)
            else:
                url = match.group(0)
            url = normalize_calendar_url(url)
            if not url or url in seen:
                continue
            seen.add(url)
            found.append(url)
    return found
