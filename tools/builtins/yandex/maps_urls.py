from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

YANDEX_MAPS_WEB_BASE = "https://yandex.ru/maps/"

# Yandex route types: auto, mt (masstransit), pd (pedestrian), bc (bicycle)
YANDEX_ROUTE_TYPE_TRANSIT = "mt"

YANDEX_ROUTE_TYPE_TO_GOOGLE: dict[str, str] = {
    "auto": "driving",
    "mt": "transit",
    "pd": "walking",
    "bc": "bicycling",
}

_LATLNG_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$"
)


def is_yandex_maps_url(url: str | None) -> bool:
    if not url:
        return False
    lowered = str(url).strip().lower()
    return lowered.startswith(("http://", "https://")) and "yandex." in lowered and "/maps" in lowered


def parse_latlng_text(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    match = _LATLNG_RE.match(str(value).strip())
    if not match:
        return None
    lat = float(match.group(1))
    lng = float(match.group(2))
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return None
    return lat, lng


def format_yandex_rtext_point(lat: float, lng: float) -> str:
    """Yandex rtext points are latitude,longitude."""
    return f"{lat},{lng}"


def parse_yandex_route_type(url: str | None) -> str | None:
    if not is_yandex_maps_url(url):
        return None
    parsed = urlparse(str(url).strip())
    query = parse_qs(parsed.query)
    rtt_values = query.get("rtt")
    if not rtt_values:
        return "transit" if query.get("rtext") else None
    return YANDEX_ROUTE_TYPE_TO_GOOGLE.get(str(rtt_values[0]).strip().lower())


def is_yandex_route_url(url: str | None) -> bool:
    if not is_yandex_maps_url(url):
        return False
    parsed = urlparse(str(url).strip())
    return "rtext" in parse_qs(parsed.query)


def parse_yandex_rtext_endpoints(url: str | None) -> tuple[str | None, str | None]:
    if not is_yandex_route_url(url):
        return None, None
    parsed = urlparse(str(url).strip())
    query = parse_qs(parsed.query)
    rtext_values = query.get("rtext")
    if not rtext_values:
        return None, None
    parts = [part.strip() for part in str(rtext_values[0]).split("~") if part.strip()]
    if len(parts) < 2:
        return None, None
    return parts[0], parts[-1]


def build_yandex_route_url(
    origin: str,
    destination: str,
    *,
    origin_lat: float | None = None,
    origin_lng: float | None = None,
    dest_lat: float | None = None,
    dest_lng: float | None = None,
    route_type: str = YANDEX_ROUTE_TYPE_TRANSIT,
) -> str:
    origin_text = str(origin).strip()
    destination_text = str(destination).strip()
    if not origin_text or not destination_text:
        raise ValueError("origin and destination are required for Yandex route URL")

    if all(value is not None for value in (origin_lat, origin_lng, dest_lat, dest_lng)):
        rtext = (
            f"{format_yandex_rtext_point(origin_lat, origin_lng)}"
            f"~{format_yandex_rtext_point(dest_lat, dest_lng)}"
        )
    else:
        origin_coords = parse_latlng_text(origin_text)
        dest_coords = parse_latlng_text(destination_text)
        if origin_coords and dest_coords:
            rtext = (
                f"{format_yandex_rtext_point(*origin_coords)}"
                f"~{format_yandex_rtext_point(*dest_coords)}"
            )
        else:
            # Text addresses are unreliable for Yandex rtext — prefer geocoded URLs.
            rtext = f"{origin_text}~{destination_text}"

    return f"{YANDEX_MAPS_WEB_BASE}?{urlencode({'rtext': rtext, 'rtt': route_type})}"


def _first_geocode_point(payload: dict[str, Any]) -> tuple[float, float] | None:
    results = payload.get("results") or []
    if not results:
        return None
    lat = results[0].get("lat")
    lng = results[0].get("lng")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


async def build_yandex_route_url_geocoded(
    origin: str,
    destination: str,
    *,
    route_type: str = YANDEX_ROUTE_TYPE_TRANSIT,
    language: str | None = None,
    region: str | None = None,
) -> str:
    from tools.builtins.google.maps_client import geocode
    from tools.builtins.yandex.route_cache import cache_yandex_route_url, get_cached_yandex_route_url

    origin_text = str(origin).strip()
    destination_text = str(destination).strip()
    cached = get_cached_yandex_route_url(origin_text, destination_text)
    if cached:
        return cached

    origin_coords = parse_latlng_text(origin_text)
    dest_coords = parse_latlng_text(destination_text)
    if origin_coords and dest_coords:
        url = build_yandex_route_url(
            origin_text,
            destination_text,
            origin_lat=origin_coords[0],
            origin_lng=origin_coords[1],
            dest_lat=dest_coords[0],
            dest_lng=dest_coords[1],
            route_type=route_type,
        )
        cache_yandex_route_url(origin_text, destination_text, url)
        return url

    geocode_kwargs: dict[str, Any] = {}
    if language:
        geocode_kwargs["language"] = language
    if region:
        geocode_kwargs["region"] = region

    origin_payload = await geocode(origin_text, **geocode_kwargs)
    dest_payload = await geocode(destination_text, **geocode_kwargs)
    origin_point = _first_geocode_point(origin_payload)
    dest_point = _first_geocode_point(dest_payload)
    if origin_point and dest_point:
        url = build_yandex_route_url(
            origin_text,
            destination_text,
            origin_lat=origin_point[0],
            origin_lng=origin_point[1],
            dest_lat=dest_point[0],
            dest_lng=dest_point[1],
            route_type=route_type,
        )
    else:
        url = build_yandex_route_url(origin_text, destination_text, route_type=route_type)

    cache_yandex_route_url(origin_text, destination_text, url)
    return url
