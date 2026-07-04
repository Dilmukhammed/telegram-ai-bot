from __future__ import annotations

UTF8_BOM = b"\xef\xbb\xbf"

_TEXT_EXTENSIONS = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".csv",
        ".json",
        ".xml",
        ".html",
        ".htm",
        ".log",
        ".yaml",
        ".yml",
    }
)


def is_probably_text_file(filename: str, mime_type: str | None) -> bool:
    name = (filename or "").lower()
    if any(name.endswith(ext) for ext in _TEXT_EXTENSIONS):
        return True
    mime = (mime_type or "").lower()
    if mime.startswith("text/"):
        return True
    return mime in {"application/json", "application/xml", "application/csv", "application/x-yaml"}


def ensure_utf8_bom_for_mobile(
    data: bytes,
    *,
    filename: str,
    mime_type: str | None,
) -> bytes:
    """Prepend UTF-8 BOM so Android/iOS text viewers detect Cyrillic correctly."""
    if not is_probably_text_file(filename, mime_type):
        return data
    if data.startswith(UTF8_BOM):
        return data
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    return UTF8_BOM + data
