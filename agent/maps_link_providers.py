from __future__ import annotations

from tools.builtins.google.maps_urls import (
    google_travel_mode,
    parse_travel_mode_from_url,
    parse_google_directions_endpoints,
)
from tools.builtins.yandex.maps_urls import build_yandex_route_url, is_yandex_maps_url
from tools.builtins.yandex.route_cache import get_cached_yandex_route_url


def resolve_route_button_url(
    google_url: str,
    *,
    origin: str | None = None,
    destination: str | None = None,
    travel_mode: str | None = None,
    transit_link_provider: str = "yandex",
) -> str:
    """Return button URL; swap Google transit links to Yandex when configured."""
    mode = google_travel_mode(travel_mode) or parse_travel_mode_from_url(google_url)
    if mode != "transit" or transit_link_provider != "yandex":
        return google_url

    origin_text = (origin or "").strip()
    destination_text = (destination or "").strip()
    if not origin_text or not destination_text:
        parsed_origin, parsed_destination = parse_google_directions_endpoints(google_url)
        origin_text = origin_text or (parsed_origin or "").strip()
        destination_text = destination_text or (parsed_destination or "").strip()
    if not origin_text or not destination_text:
        return google_url

    try:
        cached = get_cached_yandex_route_url(origin_text, destination_text)
        if cached:
            return cached
        return build_yandex_route_url(origin_text, destination_text)
    except ValueError:
        return google_url


def is_maps_button_url(url: str | None) -> bool:
    from agent.maps_button_urls import is_maps_button_candidate

    return is_maps_button_candidate(url)
