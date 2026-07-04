import json
from dataclasses import dataclass, field

from rich_format import to_telegram_html_link

@dataclass
class WebSource:
    url: str
    title: str | None = None


@dataclass
class SourceCollector:
    _sources: dict[str, WebSource] = field(default_factory=dict)

    def add(self, url: str | None, title: str | None = None) -> None:
        if not url or not str(url).startswith(("http://", "https://")):
            return
        normalized = str(url).strip()
        clean_title = (title or "").strip() or None
        existing = self._sources.get(normalized)
        if existing is None:
            self._sources[normalized] = WebSource(url=normalized, title=clean_title)
            return
        if clean_title and not existing.title:
            self._sources[normalized] = WebSource(url=normalized, title=clean_title)

    def ingest_tool_result_json(self, result_json: str) -> None:
        try:
            payload = json.loads(result_json)
        except json.JSONDecodeError:
            return
        if not payload.get("ok"):
            return

        tool_name = payload.get("tool_name")
        result = payload.get("result") or {}
        if tool_name == "exa.web_search":
            for item in result.get("results") or []:
                self.add(item.get("url"), item.get("title"))
        elif tool_name == "exa.web_fetch":
            for page in result.get("pages") or []:
                self.add(page.get("url"), page.get("title"))

    @property
    def items(self) -> list[WebSource]:
        return list(self._sources.values())

    def format_appendix(self) -> str:
        if not self._sources:
            return ""

        lines: list[str] = []
        for source in self._sources.values():
            label = source.title or source.url
            lines.append(f"<p>• {to_telegram_html_link(label, source.url)}</p>")
        body = "\n".join(lines)
        return (
            "\n\n<details>\n"
            "<summary>Источники</summary>\n\n"
            f"{body}\n"
            "</details>"
        )


def append_sources(reply: str, collector: SourceCollector) -> str:
    appendix = collector.format_appendix()
    if not appendix:
        return reply
    return f"{reply.rstrip()}{appendix}"
