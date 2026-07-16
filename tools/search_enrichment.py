from __future__ import annotations

from typing import Any, Literal

from tools.index import HybridToolIndex
from tools.keyword_index import ordered_query_tokens
from tools.schema import ToolSpec
from tools.tags import filter_tools_by_tags

SearchMode = Literal["rank", "catalog"]

MAX_TAG_HINTS = 3
TAG_HINT_TOOLS = 3
CATALOG_MAX_TOOLS = 50


class SearchToolsValidationError(ValueError):
    pass


# Compound tag families surfaced as one hint when all tags appear in the query.
TAG_HINT_PROFILES: tuple[tuple[str, ...], ...] = (
    ("google", "calendar"),
    ("google", "gmail"),
    ("google", "drive"),
    ("google", "drive", "read"),
    ("google", "drive", "write"),
    ("google", "drive", "permissions"),
    ("google", "drive", "comments"),
    ("google", "drive", "revisions"),
    ("google", "drive", "changes"),
    ("google", "drive", "shared_drives"),
    ("google", "drive", "labels"),
    ("google", "drive", "workspace"),
    ("google", "sheets"),
    ("google", "sheets", "read"),
    ("google", "sheets", "write"),
    ("google", "sheets", "values"),
    ("google", "sheets", "structure"),
    ("google", "sheets", "data"),
    ("google", "sheets", "validation"),
    ("google", "sheets", "charts"),
    ("google", "sheets", "filters"),
    ("google", "sheets", "protection"),
    ("google", "sheets", "format"),
    ("google", "maps"),
    ("google", "auth"),
    ("web", "exa"),
    ("web",),
    ("browser",),
    ("browser", "web"),
    ("browser", "login"),
    ("browser", "screenshot"),
    ("browser", "scrape"),
    ("pdf",),
    ("pdf", "read"),
    ("pdf", "write"),
)


def normalize_search_mode(mode: str | None) -> SearchMode:
    value = (mode or "rank").lower().strip()
    if value not in {"rank", "catalog"}:
        raise SearchToolsValidationError("mode must be 'rank' or 'catalog'")
    return value  # type: ignore[return-value]


def matching_tag_profiles(query: str) -> list[tuple[str, ...]]:
    tokens = set(ordered_query_tokens(query))
    if not tokens:
        return []

    matched = [profile for profile in TAG_HINT_PROFILES if all(tag in tokens for tag in profile)]
    matched.sort(key=len, reverse=True)
    return matched[:MAX_TAG_HINTS]


async def build_tag_hints(
    *,
    index: HybridToolIndex,
    all_tools: list[ToolSpec],
    query: str,
    exclude_names: set[str],
) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    seen_names = set(exclude_names)

    for profile in matching_tag_profiles(query):
        tags = list(profile)
        in_scope = filter_tools_by_tags(all_tools, tags)
        if not in_scope:
            continue

        ranked = await index.search(
            query,
            top_k=TAG_HINT_TOOLS + len(seen_names),
            tags=tags,
        )
        deduped = [tool for tool in ranked if tool.name not in seen_names][:TAG_HINT_TOOLS]
        if not deduped:
            continue

        seen_names.update(tool.name for tool in deduped)
        hints.append(
            {
                "tags": tags,
                "total_in_scope": len(in_scope),
                "returned": len(deduped),
                "tools": [tool.to_search_result() for tool in deduped],
            }
        )

    return hints


def _catalog_tools(in_scope: list[ToolSpec]) -> list[ToolSpec]:
    ordered = sorted(in_scope, key=lambda tool: tool.name)
    return ordered[:CATALOG_MAX_TOOLS]


async def build_search_payload(
    *,
    index: HybridToolIndex,
    all_tools: list[ToolSpec],
    query: str,
    top_k: int,
    tags: list[str] | None,
    mode: SearchMode = "rank",
) -> dict[str, Any]:
    if mode == "catalog":
        if not tags:
            raise SearchToolsValidationError("catalog mode requires tags")
        in_scope = filter_tools_by_tags(all_tools, tags)
        catalog = _catalog_tools(in_scope)
        return {
            "mode": "catalog",
            "query": query,
            "tags": tags,
            "count": len(catalog),
            "tools": [tool.to_catalog_result() for tool in catalog],
            "tag_scope": {
                "tags": tags,
                "total_in_scope": len(in_scope),
                "returned": len(catalog),
                "truncated": len(in_scope) > len(catalog),
            },
        }

    if not query.strip():
        raise SearchToolsValidationError("rank mode requires a non-empty query")

    if tags:
        in_scope = filter_tools_by_tags(all_tools, tags)
        tools = await index.search(query, top_k=top_k, tags=tags)
        return {
            "mode": "rank",
            "query": query,
            "tags": tags,
            "count": len(tools),
            "tools": [tool.to_search_result() for tool in tools],
            "tag_scope": {
                "tags": tags,
                "total_in_scope": len(in_scope),
                "returned": len(tools),
            },
        }

    tools = await index.search(query, top_k=top_k, tags=None)
    main_names = {tool.name for tool in tools}
    payload: dict[str, Any] = {
        "mode": "rank",
        "query": query,
        "tags": [],
        "count": len(tools),
        "tools": [tool.to_search_result() for tool in tools],
    }

    tag_hints = await build_tag_hints(
        index=index,
        all_tools=all_tools,
        query=query,
        exclude_names=main_names,
    )
    if tag_hints:
        payload["tag_hints"] = tag_hints
    return payload
