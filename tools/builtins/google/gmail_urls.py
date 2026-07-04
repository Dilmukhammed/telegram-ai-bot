from __future__ import annotations

import html
import re
from urllib.parse import quote, unquote, urlparse

GMAIL_WEB_BASE = "https://mail.google.com/mail/u/0/"

_GMAIL_URL_RE = re.compile(
    r"https?://mail\.google\.com/mail(?:/u/\d+)?[^\s<>\"'\)\]]*",
    re.IGNORECASE,
)
_GMAIL_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((https?://mail\.google\.com/mail[^)]+)\)",
    re.IGNORECASE,
)
_GMAIL_HTML_ANCHOR_RE = re.compile(
    r'<a\s+[^>]*href="(https?://mail\.google\.com/mail[^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_THREAD_HASH_RE = re.compile(
    r"#(?:inbox|all|sent|drafts|starred|important|spam|trash|label/[^/]+|search/[^/]+)/([A-Za-z0-9]+)",
    re.IGNORECASE,
)
_SEARCH_HASH_RE = re.compile(r"#search/([^/]+)(?:/([A-Za-z0-9]+))?", re.IGNORECASE)


def normalize_gmail_url(url: str | None) -> str:
    if not url:
        return ""
    return html.unescape(str(url).strip())


def is_gmail_url(url: str | None) -> bool:
    if not url:
        return False
    return "mail.google.com/mail" in normalize_gmail_url(url).lower()


def build_thread_url(thread_id: str, *, folder: str = "inbox") -> str:
    thread_id = str(thread_id or "").strip()
    if not thread_id:
        return ""
    folder = (folder or "inbox").strip().lower()
    return f"{GMAIL_WEB_BASE}#{folder}/{thread_id}"


def build_search_url(query: str) -> str:
    query = str(query or "").strip()
    if not query:
        return ""
    return f"{GMAIL_WEB_BASE}#search/{quote(query, safe='')}"


def parse_thread_id_from_url(url: str) -> str | None:
    normalized = normalize_gmail_url(url)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    fragment = parsed.fragment or ""
    if not fragment and "#" in normalized:
        fragment = normalized.split("#", 1)[1]
    match = _THREAD_HASH_RE.search(f"#{fragment}")
    if match:
        return match.group(1)
    return None


def parse_search_query_from_url(url: str) -> str | None:
    normalized = normalize_gmail_url(url)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    fragment = parsed.fragment or ""
    if not fragment and "#" in normalized:
        fragment = normalized.split("#", 1)[1]
    match = _SEARCH_HASH_RE.search(f"#{fragment}")
    if not match:
        return None
    raw = match.group(1)
    if not raw:
        return None
    return unquote(raw.replace("+", " "))


def label_for_gmail_url(url: str) -> str:
    query = parse_search_query_from_url(url)
    if query and not parse_thread_id_from_url(url):
        return truncate_gmail_button_label(f"Поиск: {query}")
    return "Открыть в Gmail"


def truncate_gmail_button_label(text: str, *, max_len: int = 40) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return "Открыть в Gmail"
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def iter_gmail_urls_in_text(text: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (_GMAIL_MARKDOWN_LINK_RE, _GMAIL_HTML_ANCHOR_RE, _GMAIL_URL_RE):
        for match in pattern.finditer(text):
            if pattern is _GMAIL_MARKDOWN_LINK_RE:
                url = match.group(2)
            elif pattern is _GMAIL_HTML_ANCHOR_RE:
                url = match.group(1)
            else:
                url = match.group(0)
            url = normalize_gmail_url(url)
            if not url or url in seen:
                continue
            seen.add(url)
            found.append(url)
    return found
