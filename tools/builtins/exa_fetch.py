from typing import Any

from tools.exa_client import get_exa_client
from tools.schema import ToolSpec


def _serialize_content_result(result: Any) -> dict[str, Any]:
    text = getattr(result, "text", None)
    if text and len(text) > 4000:
        text = text[:4000] + "…"

    highlights = getattr(result, "highlights", None) or []
    if isinstance(highlights, str):
        highlights = [highlights]

    return {
        "title": getattr(result, "title", None),
        "url": getattr(result, "url", None),
        "text": text,
        "highlights": highlights,
    }


async def _web_fetch_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    exa = get_exa_client()
    urls = arguments["urls"]
    if isinstance(urls, str):
        urls = [urls]

    response = await exa.get_contents(
        urls,
        text={"max_characters": 4000},
    )

    pages = [_serialize_content_result(item) for item in response.results]
    return {
        "count": len(pages),
        "pages": pages,
    }


EXA_WEB_FETCH = ToolSpec(
    name="exa.web_fetch",
    description=(
        "Fetch readable content of one or more known web pages by URL. "
        "Use after exa.web_search when you need more detail. "
        "Each page is truncated to about 4000 characters."
    ),
    parameters={
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One or more HTTP/HTTPS URLs to fetch (string also accepted).",
            },
        },
        "required": ["urls"],
    },
    handler=_web_fetch_handler,
    tags=("web", "fetch", "url", "read", "internet", "exa"),
    cache_ttl_seconds=3600,
    rate_limit=(400, 60),
    parallel_safe=True,
    examples=(
        "fetch webpage content by url",
        "read full article from link",
        "get page text from search result url",
    ),
)
