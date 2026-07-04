from __future__ import annotations

import html

from tools.builtins.google.maps_urls import (
    ROUTE_MODE_ORDER,
    group_key_for_route,
    is_google_maps_url,
    is_route_maps_url,
    label_for_maps_url,
    label_for_travel_mode,
)
from tools.builtins.yandex.maps_urls import is_yandex_maps_url

TOOL_INGEST_URL_KEYS: tuple[str, ...] = (
    "google_maps_uri",
    "url",
    "map_url",
    "image_url",
    "photo_uri",
)

MEDIA_GROUP_ORDER: tuple[str, ...] = ("place_photo", "street_view", "static_map")
MAPS_GROUP_ORDER: tuple[str, ...] = ("maps",)
BUTTON_KIND_ORDER: tuple[str, ...] = MEDIA_GROUP_ORDER + MAPS_GROUP_ORDER + ("route",)


def normalize_maps_button_url(url: str | None) -> str:
    if not url:
        return ""
    return html.unescape(str(url).strip())


def is_google_static_map_url(url: str | None) -> bool:
    if not url:
        return False
    return "maps.googleapis.com/maps/api/staticmap" in str(url).lower()


def is_google_street_view_url(url: str | None) -> bool:
    if not url:
        return False
    return "maps.googleapis.com/maps/api/streetview" in str(url).lower()


def is_google_place_photo_url(url: str | None) -> bool:
    if not url:
        return False
    lowered = str(url).lower()
    return any(
        host in lowered
        for host in (
            "googleusercontent.com",
            "ggpht.com",
            "maps.googleapis.com/maps/api/place",
        )
    )


def is_maps_button_candidate(url: str | None) -> bool:
    if not url:
        return False
    normalized = normalize_maps_button_url(url)
    return (
        is_google_maps_url(normalized)
        or is_yandex_maps_url(normalized)
        or is_google_static_map_url(normalized)
        or is_google_street_view_url(normalized)
        or is_google_place_photo_url(normalized)
    )


def group_key_for_button_url(
    url: str,
    *,
    tool_name: str | None = None,
    travel_mode: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
) -> str:
    if tool_name == "google.maps.static_map" or is_google_static_map_url(url):
        return "media:static_map"
    if tool_name == "google.maps.street_view_image" or is_google_street_view_url(url):
        return "media:street_view"
    if tool_name == "google.maps.place_photo" or is_google_place_photo_url(url):
        return "media:place_photo"
    if is_route_maps_url(url) or (is_google_maps_url(url) and "/maps/dir/" in url):
        return group_key_for_route(
            url,
            travel_mode=travel_mode,
            origin=origin,
            destination=destination,
        )
    if is_google_maps_url(url) or is_yandex_maps_url(url):
        return "maps:open"
    return f"url:{normalize_maps_button_url(url)}"


def label_for_maps_tool(
    tool_name: str,
    result: dict,
    *,
    url: str = "",
    travel_mode: str | None = None,
) -> str:
    if tool_name == "google.maps.static_map":
        return "Снимок карты"
    if tool_name == "google.maps.street_view_image":
        return "Панорама"
    if tool_name == "google.maps.place_photo":
        return "Фото места"
    if tool_name in {"google.maps.directions", "google.maps.travel_time", "google.maps.compute_routes"}:
        return label_for_maps_url(url, travel_mode=travel_mode or result.get("travel_mode"))
    if tool_name == "google.maps.maps_link":
        link_type = str(result.get("link_type") or "").lower()
        if link_type == "directions" or is_route_maps_url(url):
            return label_for_maps_url(url, travel_mode=travel_mode or result.get("travel_mode"))
        return "Открыть на карте"
    if is_route_maps_url(url):
        return label_for_maps_url(url, travel_mode=travel_mode)
    if is_google_static_map_url(url):
        return "Снимок карты"
    if is_google_street_view_url(url):
        return "Панорама"
    if is_google_place_photo_url(url):
        return "Фото места"
    if is_google_maps_url(url) or is_yandex_maps_url(url):
        return label_for_maps_url(url, travel_mode=travel_mode)
    return "Открыть на карте"


def button_sort_key(group_key: str, label: str) -> tuple[int, int, str]:
    if group_key.startswith("route:"):
        mode = group_key.removeprefix("route:")
        try:
            return (BUTTON_KIND_ORDER.index("route"), ROUTE_MODE_ORDER.index(mode), label)
        except ValueError:
            return (BUTTON_KIND_ORDER.index("route"), len(ROUTE_MODE_ORDER), label)
    if group_key.startswith("media:"):
        kind = group_key.removeprefix("media:")
        try:
            return (MEDIA_GROUP_ORDER.index(kind), 0, label)
        except ValueError:
            return (0, 0, label)
    if group_key.startswith("maps:"):
        return (len(MEDIA_GROUP_ORDER), 0, label)
    return (len(BUTTON_KIND_ORDER), 0, label)
