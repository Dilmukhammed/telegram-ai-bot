from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from agent.transit_guard import skipped_web_search_result, transit_route_satisfied


def _overlay(**kwargs):
    from tools.builtins.google.transit_provider import apply_transit_route_overlay

    async def _run() -> dict:
        with patch(
            "tools.builtins.google.maps_client.geocode",
            new=AsyncMock(
                side_effect=[
                    {"results": [{"lat": 41.1, "lng": 69.1}]},
                    {"results": [{"lat": 41.2, "lng": 69.2}]},
                ]
            ),
        ):
            return await apply_transit_route_overlay(kwargs)

    return asyncio.run(_run())


def test_transit_overlay_complete_shape() -> None:
    result = _overlay(
        origin="Южный вокзал",
        destination="Тинчлик",
        travel_mode="TRANSIT",
        count=0,
        google_maps_uri="https://www.google.com/maps/dir/?api=1&origin=a&destination=b&travelmode=transit",
    )
    assert result["route_complete"] is True
    assert result["count"] == 1
    assert result["steps"]
    assert "yandex.ru/maps" in result["google_maps_uri"]


def test_transit_guard_detects_completed_route() -> None:
    tool_result = json.dumps(
        {
            "ok": True,
            "tool_name": "google.maps.directions",
            "result": _overlay(
                origin="A",
                destination="B",
                travel_mode="TRANSIT",
                count=0,
            ),
        },
        ensure_ascii=False,
    )
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": tool_result},
    ]
    assert transit_route_satisfied(messages) is True


def test_transit_guard_skips_web_search_payload() -> None:
    payload = json.loads(skipped_web_search_result(query="bus 80 tashkent"))
    assert payload["skipped"] is True
    assert payload["result"]["count"] == 0
