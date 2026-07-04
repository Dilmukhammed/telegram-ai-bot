from __future__ import annotations

import json
from typing import Any

from tools.builtins.google.maps_urls import google_travel_mode

_TRANSIT_MAPS_TOOLS = frozenset(
    {
        "google.maps.directions",
        "google.maps.travel_time",
        "google.maps.compute_routes",
        "google.maps.maps_link",
    }
)


def _parse_tool_payload(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def transit_route_satisfied(messages: list[dict[str, Any]]) -> bool:
    """True when a TRANSIT google.maps call already returned a complete route."""
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        payload = _parse_tool_payload(str(message.get("content") or ""))
        if not payload or not payload.get("ok"):
            continue
        tool_name = str(payload.get("tool_name") or "")
        if tool_name not in _TRANSIT_MAPS_TOOLS:
            continue
        result = payload.get("result") or {}
        if google_travel_mode(result.get("travel_mode")) != "transit":
            continue
        if result.get("route_complete") is True:
            return True
        if int(result.get("count") or 0) > 0 and result.get("google_maps_uri"):
            return True
    return False


def skipped_web_search_result(*, query: str) -> str:
    return json.dumps(
        {
            "ok": True,
            "tool_name": "exa.web_search",
            "cached": False,
            "skipped": True,
            "result": {
                "query": query,
                "count": 0,
                "note": (
                    "Web search skipped: public transit route is already available "
                    "from google.maps (map link + inline button). Answer using that result."
                ),
            },
        },
        ensure_ascii=False,
    )
