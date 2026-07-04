import html
import re

from rich_table_postprocess import normalize_table_cell
TABLE_ROW_RE = re.compile(r"^\s*\|(.+\|)\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_URL_IN_TEXT_RE = re.compile(
    r"https?://(?:[^\s<>\"'\)\]]|&(?:amp|#\d+|#x[\da-fA-F]+);)+",
    re.IGNORECASE,
)
_MARKDOWN_LINK_URL_RE = re.compile(r"\]\((https?://[^)]+)\)")


def fix_url_amp_entities(text: str) -> str:
    """Decode &amp; inside URLs so Google Maps query strings stay clickable."""

    def _unescape_url(match: re.Match[str]) -> str:
        return html.unescape(match.group(0))

    text = _MARKDOWN_LINK_URL_RE.sub(
        lambda match: f"]({html.unescape(match.group(1))})",
        text,
    )
    return _URL_IN_TEXT_RE.sub(_unescape_url, text)


def telegram_href(url: str) -> str:
    """Telegram Rich Markdown href: literal query string (&), not &amp; entities."""
    cleaned = html.unescape(str(url).strip())
    return cleaned.replace('"', "%22")


_GOOGLE_MAPS_URL_RE = re.compile(
    r"https?://(?:www\.)?google\.com/maps/"
    r"(?:[^\s<>\"'\)\]]|&(?:amp|#\d+|#x[\da-fA-F]+);)+",
    re.IGNORECASE,
)
_GOOGLE_MAPS_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https?://(?:www\.)?google\.com/maps/[^)]+)\)",
    re.IGNORECASE,
)


_DETAILS_BLOCK_RE = re.compile(r"<details>.*?</details>", re.IGNORECASE | re.DOTALL)


def to_telegram_html_link(label: str, url: str) -> str:
    """HTML anchor for <details> appendices — markdown is not parsed there."""
    safe_label = html.escape(label, quote=False)
    return f'<a href="{telegram_href(url)}">{safe_label}</a>'


def _stash_details_blocks(text: str) -> tuple[str, list[str]]:
    blocks: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        blocks.append(match.group(0))
        return f"\x00DETAILS{len(blocks) - 1}\x00"

    return _DETAILS_BLOCK_RE.sub(_stash, text), blocks


def _restore_details_blocks(text: str, blocks: list[str]) -> str:
    for index, block in enumerate(blocks):
        text = text.replace(f"\x00DETAILS{index}\x00", block)
    return text


_GOOGLE_MAPS_HTML_ANCHOR_RE = re.compile(
    r'<a\s+[^>]*href="((?:https?://)?(?:www\.)?google\.com/maps/[^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

_YANDEX_MAPS_HOST = r"(?:[^\s/]+\.)?yandex\.(?:ru|com|uz|by|kz|ua)"
_YANDEX_MAPS_ROUTE_URL_RE = re.compile(
    rf"https?://{_YANDEX_MAPS_HOST}/maps/\?"
    r"(?:[^\s<>\"'\)\]]|&(?:amp|#\d+|#x[\da-fA-F]+);)*"
    r"rtext=(?:[^\s<>\"'\)\]]|&(?:amp|#\d+|#x[\da-fA-F]+);)+",
    re.IGNORECASE,
)
_YANDEX_MAPS_ROUTE_MARKDOWN_LINK_RE = re.compile(
    rf"\[([^\]]*)\]\((https?://{_YANDEX_MAPS_HOST}/maps/[^)]*rtext=[^)]+)\)",
    re.IGNORECASE,
)
_YANDEX_MAPS_ROUTE_HTML_ANCHOR_RE = re.compile(
    rf'<a\s+[^>]*href="((?:https?://)?{_YANDEX_MAPS_HOST}/maps/[^"]*rtext=[^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

_GOOGLE_MAPS_API_URL_RE = re.compile(
    r"https?://maps\.googleapis\.com/maps/api/"
    r"(?:staticmap|streetview)"
    r"(?:[^\s<>\"'\)\]]|&(?:amp|#\d+|#x[\da-fA-F]+);)+",
    re.IGNORECASE,
)
_GOOGLE_MAPS_API_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((https?://maps\.googleapis\.com/maps/api/(?:staticmap|streetview)[^)]+)\)",
    re.IGNORECASE,
)
_GOOGLE_MAPS_API_HTML_ANCHOR_RE = re.compile(
    r'<a\s+[^>]*href="((?:https?://)?maps\.googleapis\.com/maps/api/(?:staticmap|streetview)[^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

_GOOGLE_PLACE_PHOTO_URL_RE = re.compile(
    r"https?://(?:[^\s<>\"'\)\]]+\.)?"
    r"(?:googleusercontent\.com|ggpht\.com)"
    r"(?:[^\s<>\"'\)\]]|&(?:amp|#\d+|#x[\da-fA-F]+);)+",
    re.IGNORECASE,
)
_GOOGLE_PLACE_PHOTO_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((https?://(?:[^\)]+\.)?(?:googleusercontent\.com|ggpht\.com)[^)]+)\)",
    re.IGNORECASE,
)


def to_telegram_markdown_link(label: str, url: str) -> str:
    """GFM link for Telegram Rich Markdown — literal & in URL, not &amp;."""
    safe_label = label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return f"[{safe_label}]({telegram_href(url)})"


def fix_google_maps_html_anchors(text: str) -> str:
    """Model sometimes emits <a href=\"...&amp;...\"> — convert to GFM links."""

    def _replace(match: re.Match[str]) -> str:
        label = html.unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip() or "Google Maps"
        return to_telegram_markdown_link(label, match.group(1))

    return _GOOGLE_MAPS_HTML_ANCHOR_RE.sub(_replace, text)


def _cleanup_stripped_link_text(text: str) -> str:
    text = re.sub(r"[ \t]+(\n|$)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?m)^[\-*•]\s*$", "", text)
    return text.strip()


def _cleanup_stripped_maps_text(text: str) -> str:
    return _cleanup_stripped_link_text(text)


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


def strip_gmail_button_urls(text: str) -> str:
    """Remove Gmail web URLs from model text when inline buttons add them."""
    text = _GMAIL_HTML_ANCHOR_RE.sub("", text)
    text = _GMAIL_MARKDOWN_LINK_RE.sub("", text)
    text = _GMAIL_URL_RE.sub("", text)
    return _cleanup_stripped_link_text(text)


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


def strip_drive_button_urls(text: str) -> str:
    """Remove Drive/Docs URLs from model text when inline buttons add them."""
    text = _DRIVE_HTML_ANCHOR_RE.sub("", text)
    text = _DRIVE_MARKDOWN_LINK_RE.sub("", text)
    text = _DRIVE_URL_RE.sub("", text)
    return _cleanup_stripped_link_text(text)


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


def strip_calendar_button_urls(text: str) -> str:
    """Remove Google Calendar URLs from model text when inline buttons add them."""
    text = _CALENDAR_HTML_ANCHOR_RE.sub("", text)
    text = _CALENDAR_MARKDOWN_LINK_RE.sub("", text)
    text = _CALENDAR_URL_RE.sub("", text)
    return _cleanup_stripped_link_text(text)


_TASKS_URL_RE = re.compile(
    r"https?://tasks\.google\.com[^\s<>\"'\)\]]*",
    re.IGNORECASE,
)
_TASKS_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((https?://tasks\.google\.com[^)]+)\)",
    re.IGNORECASE,
)
_TASKS_HTML_ANCHOR_RE = re.compile(
    r'<a\s+[^>]*href="(https?://tasks\.google\.com[^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def strip_tasks_button_urls(text: str) -> str:
    """Remove Google Tasks URLs from model text when inline buttons add them."""
    text = _TASKS_HTML_ANCHOR_RE.sub("", text)
    text = _TASKS_MARKDOWN_LINK_RE.sub("", text)
    text = _TASKS_URL_RE.sub("", text)
    return _cleanup_stripped_link_text(text)


def strip_maps_button_urls(text: str) -> str:
    """Remove map/media URLs from model text when inline buttons add them."""
    text = fix_google_maps_html_anchors(text)
    text = _YANDEX_MAPS_ROUTE_HTML_ANCHOR_RE.sub("", text)
    text = _GOOGLE_MAPS_API_HTML_ANCHOR_RE.sub("", text)
    text = _GOOGLE_MAPS_MARKDOWN_LINK_RE.sub("", text)
    text = _YANDEX_MAPS_ROUTE_MARKDOWN_LINK_RE.sub("", text)
    text = _GOOGLE_MAPS_API_MARKDOWN_LINK_RE.sub("", text)
    text = _GOOGLE_PLACE_PHOTO_MARKDOWN_LINK_RE.sub("", text)
    text = _GOOGLE_MAPS_URL_RE.sub("", text)
    text = _YANDEX_MAPS_ROUTE_URL_RE.sub("", text)
    text = _GOOGLE_MAPS_API_URL_RE.sub("", text)
    text = _GOOGLE_PLACE_PHOTO_URL_RE.sub("", text)
    return _cleanup_stripped_maps_text(text)


def strip_maps_route_urls(text: str) -> str:
    """Backward-compatible alias."""
    return strip_maps_button_urls(text)


def strip_google_maps_urls(text: str) -> str:
    """Backward-compatible alias."""
    return strip_maps_button_urls(text)


def _inside_html_table_cell(text: str, pos: int) -> bool:
    before = text[:pos].lower()
    open_tag = max(before.rfind("<td"), before.rfind("<th"))
    if open_tag < 0:
        return False
    close_tag = before.rfind(">")
    if close_tag < open_tag:
        return False
    return open_tag > before.rfind("</td") and open_tag > before.rfind("</th")


def linkify_google_maps_urls(text: str) -> str:
    """Normalize Google Maps links to GFM [label](url) — Telegram decodes & correctly there."""

    def _markdown_link(match: re.Match[str]) -> str:
        return to_telegram_markdown_link(match.group(1), match.group(2))

    def _bare_link(match: re.Match[str]) -> str:
        url = match.group(0)
        if _inside_html_table_cell(text, match.start()):
            href = telegram_href(url)
            return f'<a href="{href}">Открыть в Google Maps</a>'
        return to_telegram_markdown_link("Открыть в Google Maps", url)

    text = fix_google_maps_html_anchors(text)
    text = _GOOGLE_MAPS_MARKDOWN_LINK_RE.sub(_markdown_link, text)

    parts: list[str] = []
    last = 0
    for match in _GOOGLE_MAPS_URL_RE.finditer(text):
        start, end = match.span()
        if start >= 2 and text[start - 2 : start] == "](":
            continue
        parts.append(text[last:start])
        parts.append(_bare_link(match))
        last = end
    parts.append(text[last:])
    return "".join(parts)


def _inline_markdown_to_html(text: str) -> str:
    urls: list[str] = []

    def _stash_url(match: re.Match[str]) -> str:
        urls.append(match.group(0))
        return f"\x00URL{len(urls) - 1}\x00"

    text = _URL_IN_TEXT_RE.sub(_stash_url, text)
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    for index, url in enumerate(urls):
        escaped = escaped.replace(f"\x00URL{index}\x00", url)
    return escaped


def _parse_alignments(separator_line: str) -> list[str]:
    cells = [cell.strip() for cell in separator_line.strip().strip("|").split("|")]
    aligns: list[str] = []
    for cell in cells:
        if cell.startswith(":") and cell.endswith(":"):
            aligns.append("center")
        elif cell.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("left")
    return aligns


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table_header_cell_html(value: str) -> str:
    inner = _inline_markdown_to_html(normalize_table_cell(value))
    if inner.startswith("<b>") and inner.endswith("</b>"):
        return inner
    return f"<b>{inner}</b>"


def _render_table(header: list[str], aligns: list[str], rows: list[list[str]]) -> str:
    column_count = len(header)

    def render_cell(tag: str, value: str, index: int) -> str:
        align = aligns[index] if index < len(aligns) else "left"
        if tag == "th":
            content = _table_header_cell_html(value)
        else:
            content = _inline_markdown_to_html(normalize_table_cell(value))
        return f'<{tag} align="{align}">{content}</{tag}>'

    head = "<tr>" + "".join(render_cell("th", header[i], i) for i in range(column_count)) + "</tr>"
    body = ""
    for row in rows:
        padded = row + [""] * max(0, column_count - len(row))
        body += "<tr>" + "".join(render_cell("td", padded[i], i) for i in range(column_count)) + "</tr>"
    return f"<table bordered striped>{head}{body}</table>"


def convert_gfm_tables_to_html(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    index = 0

    while index < len(lines):
        if (
            index + 1 < len(lines)
            and TABLE_ROW_RE.match(lines[index])
            and TABLE_SEP_RE.match(lines[index + 1])
        ):
            header = _split_table_row(lines[index])
            aligns = _parse_alignments(lines[index + 1])
            rows: list[list[str]] = []
            index += 2
            while index < len(lines) and TABLE_ROW_RE.match(lines[index]):
                rows.append(_split_table_row(lines[index]))
                index += 1
            output.append(_render_table(header, aligns, rows))
            continue

        output.append(lines[index])
        index += 1

    return "\n".join(output)


def prepare_telegram_rich_markdown(text: str) -> str:
    """Telegram Rich Markdown accepts embedded HTML blocks such as <table>."""
    normalized = fix_url_amp_entities(text.strip())
    stashed, details_blocks = _stash_details_blocks(normalized)
    stashed = fix_google_maps_html_anchors(stashed)
    converted = convert_gfm_tables_to_html(stashed)
    processed = linkify_google_maps_urls(fix_url_amp_entities(converted))
    return _restore_details_blocks(processed, details_blocks)
