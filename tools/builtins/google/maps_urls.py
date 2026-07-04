from __future__ import annotations

import html
from urllib.parse import parse_qs, urlparse, urlencode

MAPS_DIRECTIONS_BASE = "https://www.google.com/maps/dir/?api=1"
MAPS_SEARCH_BASE = "https://www.google.com/maps/search/?api=1"

TRAVEL_MODE_TO_GOOGLE: dict[str, str] = {
    "DRIVE": "driving",
    "WALK": "walking",
    "TRANSIT": "transit",
    "BICYCLE": "bicycling",
}

TRAVEL_MODE_LABELS_RU: dict[str, str] = {
    "driving": "На машине",
    "walking": "Пешком",
    "transit": "На общественном транспорте",
    "bicycling": "На велосипеде",
}

ROUTE_MODE_ORDER: tuple[str, ...] = ("driving", "transit", "walking", "bicycling")

def normalize_travel_mode(travel_mode: str | None) -> str:
    return TRAVEL_MODE_TO_GOOGLE.get((travel_mode or "DRIVE").upper(), "driving")


def build_directions_url(
    origin: str,
    destination: str,
    *,
    travel_mode: str = "DRIVE",
) -> str:
    params = urlencode(
        {
            "origin": origin.strip(),
            "destination": destination.strip(),
            "travelmode": normalize_travel_mode(travel_mode),
        }
    )
    return f"{MAPS_DIRECTIONS_BASE}&{params}"


def build_search_url(query: str) -> str:
    return f"{MAPS_SEARCH_BASE}&{urlencode({'query': query.strip()})}"


def build_place_url(place_id: str, query: str | None = None) -> str:
    params: dict[str, str] = {"query_place_id": place_id.strip()}
    if query and query.strip():
        params["query"] = query.strip()
    return f"{MAPS_SEARCH_BASE}&{urlencode(params)}"


def is_google_maps_url(url: str | None) -> bool:
    if not url:
        return False
    lowered = str(url).strip().lower()
    return lowered.startswith(("http://", "https://")) and "google.com/maps" in lowered


def parse_travel_mode_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(html.unescape(str(url).strip()))
    query = parse_qs(parsed.query)
    for key in ("travelmode", "travel_mode"):
        values = query.get(key)
        if values:
            return str(values[0]).strip().lower()
    return None


def parse_google_directions_endpoints(url: str | None) -> tuple[str | None, str | None]:
    if not url:
        return None, None
    parsed = urlparse(html.unescape(str(url).strip()))
    query = parse_qs(parsed.query)
    origin_values = query.get("origin")
    destination_values = query.get("destination")
    origin = str(origin_values[0]).strip() if origin_values else None
    destination = str(destination_values[0]).strip() if destination_values else None
    return origin or None, destination or None


def google_travel_mode(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    upper = raw.upper()
    if upper in TRAVEL_MODE_TO_GOOGLE:
        return TRAVEL_MODE_TO_GOOGLE[upper]
    lowered = raw.lower()
    if lowered in TRAVEL_MODE_LABELS_RU:
        return lowered
    return None


def label_for_travel_mode(travel_mode: str | None) -> str:
    google_mode = google_travel_mode(travel_mode)
    if google_mode and google_mode in TRAVEL_MODE_LABELS_RU:
        return TRAVEL_MODE_LABELS_RU[google_mode]
    return "Открыть маршрут на карте"


def is_route_maps_url(url: str | None) -> bool:
    if not url:
        return False
    from tools.builtins.yandex.maps_urls import is_yandex_route_url

    url_str = str(url).strip()
    if is_yandex_route_url(url_str):
        return True
    return "/maps/dir/" in url_str


def label_for_maps_url(url: str, *, travel_mode: str | None = None) -> str:
    from tools.builtins.yandex.maps_urls import parse_yandex_route_type

    mode = (
        google_travel_mode(travel_mode)
        or parse_travel_mode_from_url(url)
        or parse_yandex_route_type(url)
    )
    if mode and (is_route_maps_url(url) or google_travel_mode(travel_mode)):
        return label_for_travel_mode(mode)
    if "/maps/search/" in url or "query_place_id" in url:
        return "Открыть на карте"
    return "Открыть на карте"


def normalize_route_endpoint(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(str(value).strip().lower().split())


def group_key_for_route(
    url: str,
    *,
    travel_mode: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
) -> str:
    from tools.builtins.yandex.maps_urls import (
        is_yandex_route_url,
        parse_yandex_route_type,
        parse_yandex_rtext_endpoints,
    )

    normalized_url = html.unescape(str(url).strip())

    if is_yandex_route_url(normalized_url):
        mode = parse_yandex_route_type(normalized_url) or "transit"
        url_origin, url_destination = parse_yandex_rtext_endpoints(normalized_url)
    else:
        mode = google_travel_mode(travel_mode) or parse_travel_mode_from_url(normalized_url)
        url_origin, url_destination = parse_google_directions_endpoints(normalized_url)

    resolved_origin = origin or url_origin
    resolved_destination = destination or url_destination
    if mode and resolved_origin and resolved_destination:
        origin_key = normalize_route_endpoint(resolved_origin)
        destination_key = normalize_route_endpoint(resolved_destination)
        return f"route:{mode}:{origin_key}|{destination_key}"

    if mode:
        return f"route:{mode}:url:{normalized_url}"
    return f"url:{normalized_url}"


def group_key_for_maps_url(url: str) -> str:
    from tools.builtins.yandex.maps_urls import is_yandex_maps_url, is_yandex_route_url

    if is_yandex_route_url(url) or (is_google_maps_url(url) and "/maps/dir/" in url):
        return group_key_for_route(url)
    if is_yandex_maps_url(url):
        return f"url:{html.unescape(str(url).strip())}"
    return f"url:{url.strip()}"