from __future__ import annotations

from typing import Literal, Protocol, TypeVar

from rich_format import to_telegram_html_link

LinkSource = Literal["tool", "text"]

TOOL_LINKS_DETAILS_MAX = 30


class _ProvenanceLink(Protocol):
    url: str
    label: str
    group_key: str
    source: LinkSource


T = TypeVar("T", bound=_ProvenanceLink)


def select_button_links(
    links: list[T],
    *,
    max_buttons: int,
    sort_key,
) -> tuple[tuple[str, str], ...]:
    text_links = [link for link in links if link.source == "text"]
    ordered = sorted(text_links, key=sort_key)
    return tuple((link.label, link.url) for link in ordered[:max_buttons])


def select_details_links(links: list[T], *, sort_key) -> list[T]:
    button_groups = {link.group_key for link in links if link.source == "text"}
    tool_links = [
        link
        for link in links
        if link.source == "tool" and link.group_key not in button_groups
    ]
    return sorted(tool_links, key=sort_key)


def format_tool_links_appendix(links: list[tuple[str, str]], *, summary: str = "Ссылки") -> str:
    if not links:
        return ""
    lines = [f"<p>• {to_telegram_html_link(label, url)}</p>" for label, url in links]
    body = "\n".join(lines)
    return (
        "\n\n<details>\n"
        f"<summary>{summary}</summary>\n\n"
        f"{body}\n"
        "</details>"
    )


def append_tool_links_appendix(
    reply: str,
    *,
    maps_links,
    gmail_links,
    drive_links,
    calendar_links,
    tasks_links,
) -> str:
    combined: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for collector in (maps_links, gmail_links, drive_links, calendar_links, tasks_links):
        for link in collector.details_items():
            if link.url in seen_urls:
                continue
            seen_urls.add(link.url)
            combined.append((link.label, link.url))
            if len(combined) >= TOOL_LINKS_DETAILS_MAX:
                break
        if len(combined) >= TOOL_LINKS_DETAILS_MAX:
            break

    appendix = format_tool_links_appendix(combined)
    if not appendix:
        return reply
    return f"{reply.rstrip()}{appendix}"
