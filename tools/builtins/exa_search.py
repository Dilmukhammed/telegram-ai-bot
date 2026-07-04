from typing import Any

from tools.exa_client import get_exa_client
from tools.schema import ToolSpec


def _serialize_search_result(result: Any) -> dict[str, Any]:
    highlights = getattr(result, "highlights", None) or []
    if isinstance(highlights, str):
        highlights = [highlights]

    return {
        "title": getattr(result, "title", None),
        "url": getattr(result, "url", None),
        "published_date": getattr(result, "published_date", None),
        "author": getattr(result, "author", None),
        "highlights": highlights,
    }


async def _web_search_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    exa = get_exa_client()
    query = arguments["query"]
    num_results = int(arguments.get("num_results", 5))
    search_type = arguments.get("type", "instant")

    response = await exa.search(
        query,
        type=search_type,
        num_results=num_results,
        contents={"highlights": True},
    )

    results = [_serialize_search_result(item) for item in response.results]
    return {
        "query": query,
        "count": len(results),
        "results": results,
    }


EXA_WEB_SEARCH = ToolSpec(
    name="exa.web_search",
    description=(
        "Search the live web for current information, news, facts, documentation, "
        "prices, events, and any topic that may change over time. Returns titles, "
        "URLs, and short highlights only — not full page text. "
        "Use exa.web_fetch on result URLs when you need the full article."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query.",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (1-10).",
                "default": 5,
            },
            "type": {
                "type": "string",
                "enum": ["instant", "fast", "auto"],
                "description": "Search mode: instant (default, chat), fast, or auto.",
                "default": "instant",
            },
        },
        "required": ["query"],
    },
    handler=_web_search_handler,
    tags=("web", "search", "news", "internet", "exa"),
    cache_ttl_seconds=300,
    rate_limit=(10, 60),
    parallel_safe=True,
    examples=(
        "search the web for latest news",
        "find current bitcoin price",
        "look up recent AI announcements",
        "what happened today in tech",
    ),
)
