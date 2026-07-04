from __future__ import annotations

import html
import re
from urllib.parse import urlparse

from tools.builtins.google.drive_serialize import FOLDER_MIME, GOOGLE_APPS_MIME_PREFIX

_DRIVE_HOST_MARKERS = (
    "drive.google.com",
    "docs.google.com",
    "sheets.google.com",
    "slides.google.com",
)

_DRIVE_URL_RE = re.compile(
    r"https?://(?:drive|docs|sheets|slides)\.google\.com[^\s<>\"'\)\]]*",
    re.IGNORECASE,
)
_DRIVE_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((https?://(?:drive|docs|sheets|slides)\.google\.com[^)]+)\)",
    re.IGNORECASE,
)
_DRIVE_HTML_ANCHOR_RE = re.compile(
    r'<a\s+[^>]*href="(https?://(?:drive|docs|sheets|slides)\.google\.com[^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

_FILE_ID_PATTERNS = (
    re.compile(r"/file/d/([a-zA-Z0-9_-]+)", re.IGNORECASE),
    re.compile(r"/folders/([a-zA-Z0-9_-]+)", re.IGNORECASE),
    re.compile(r"/document/d/([a-zA-Z0-9_-]+)", re.IGNORECASE),
    re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", re.IGNORECASE),
    re.compile(r"/presentation/d/([a-zA-Z0-9_-]+)", re.IGNORECASE),
    re.compile(r"/forms/d/([a-zA-Z0-9_-]+)", re.IGNORECASE),
    re.compile(r"[?&]id=([a-zA-Z0-9_-]+)", re.IGNORECASE),
)

_MIME_TO_KIND: dict[str, str] = {
    "application/vnd.google-apps.spreadsheet": "spreadsheet",
    "application/vnd.google-apps.document": "document",
    "application/vnd.google-apps.presentation": "presentation",
    "application/vnd.google-apps.form": "form",
    "application/vnd.google-apps.folder": "folder",
    "application/vnd.google-apps.drawing": "drawing",
    "application/pdf": "pdf",
}

_KIND_DEFAULT_LABELS_RU: dict[str, str] = {
    "spreadsheet": "Открыть таблицу",
    "document": "Открыть документ",
    "presentation": "Открыть презентацию",
    "form": "Открыть форму",
    "folder": "Открыть папку",
    "drawing": "Открыть рисунок",
    "pdf": "Открыть PDF",
    "file": "Открыть файл",
    "drive": "Открыть в Drive",
}


def normalize_drive_url(url: str | None) -> str:
    if not url:
        return ""
    return html.unescape(str(url).strip())


def is_drive_url(url: str | None) -> bool:
    normalized = normalize_drive_url(url)
    if not normalized:
        return False
    host = urlparse(normalized).netloc.lower()
    return any(marker in host for marker in _DRIVE_HOST_MARKERS)


def parse_file_id_from_url(url: str) -> str | None:
    normalized = normalize_drive_url(url)
    if not normalized:
        return None
    for pattern in _FILE_ID_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return match.group(1)
    return None


def drive_url_kind(url: str | None, *, mime_type: str | None = None) -> str:
    if mime_type:
        mapped = _MIME_TO_KIND.get(str(mime_type).strip())
        if mapped:
            return mapped
        if str(mime_type).startswith(GOOGLE_APPS_MIME_PREFIX):
            return "file"

    normalized = normalize_drive_url(url)
    if not normalized:
        return "drive"
    path = urlparse(normalized).path.lower()
    if "/spreadsheets/" in path:
        return "spreadsheet"
    if "/document/" in path:
        return "document"
    if "/presentation/" in path:
        return "presentation"
    if "/forms/" in path:
        return "form"
    if "/folders/" in path:
        return "folder"
    if "/file/d/" in path:
        return "file"
    return "drive"


def default_label_for_drive_kind(kind: str) -> str:
    return _KIND_DEFAULT_LABELS_RU.get(kind, _KIND_DEFAULT_LABELS_RU["drive"])


def truncate_drive_button_label(text: str, *, max_len: int = 40) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return default_label_for_drive_kind("drive")
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def label_for_drive_url(
    url: str,
    *,
    name: str | None = None,
    mime_type: str | None = None,
) -> str:
    if name and str(name).strip():
        return truncate_drive_button_label(str(name).strip())
    kind = drive_url_kind(url, mime_type=mime_type)
    return default_label_for_drive_kind(kind)


def iter_drive_urls_in_text(text: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (_DRIVE_MARKDOWN_LINK_RE, _DRIVE_HTML_ANCHOR_RE, _DRIVE_URL_RE):
        for match in pattern.finditer(text):
            if pattern is _DRIVE_MARKDOWN_LINK_RE:
                url = match.group(2)
            elif pattern is _DRIVE_HTML_ANCHOR_RE:
                url = match.group(1)
            else:
                url = match.group(0)
            url = normalize_drive_url(url)
            if not url or not is_drive_url(url) or url in seen:
                continue
            seen.add(url)
            found.append(url)
    return found
