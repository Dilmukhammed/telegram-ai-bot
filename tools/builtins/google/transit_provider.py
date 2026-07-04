from __future__ import annotations

from typing import Any

from config import get_settings
from tools.builtins.google.maps_urls import google_travel_mode
from tools.builtins.yandex.maps_urls import build_yandex_route_url_geocoded


def _transit_route_note(*, google_count: int) -> str:
    if google_count == 0:
        return (
            "Public transit route is ready (count=1). "
            "Turn-by-turn details are on the map link and inline «На общественном транспорте» button. "
            "No further route lookup is needed."
        )
    return (
        "Public transit route is ready. "
        "Use the map link / inline button for full step-by-step directions."
    )


async def apply_transit_route_overlay(result: dict[str, Any]) -> dict[str, Any]:
    """Swap TRANSIT links to Yandex and return a complete-looking route for the model."""
    settings = get_settings()
    if settings.maps_transit_link_provider != "yandex":
        return result

    mode = google_travel_mode(result.get("travel_mode"))
    if mode != "transit":
        return result

    origin = str(result.get("origin") or "").strip()
    destination = str(result.get("destination") or "").strip()
    if not origin or not destination:
        return result

    google_count = int(result.get("count") or 0)
    yandex_url = await build_yandex_route_url_geocoded(
        origin,
        destination,
        language=settings.google_maps_default_language,
        region=settings.google_maps_default_region,
    )
    note = _transit_route_note(google_count=google_count)

    updated = dict(result)
    updated["status"] = "ok"
    updated["route_complete"] = True
    updated["google_transit_count"] = google_count
    updated["count"] = 1 if google_count == 0 else google_count
    updated["google_maps_uri"] = yandex_url
    updated["route_note"] = note
    updated["google_maps_uri_hint"] = note
    updated["route_summary"] = f"{origin} → {destination} (public transit)"

    if not updated.get("steps"):
        updated["steps"] = [
            "Public transit route is available — open the map link or inline button for turn-by-turn directions."
        ]

    if "url" in updated:
        updated["url"] = yandex_url

    return updated
