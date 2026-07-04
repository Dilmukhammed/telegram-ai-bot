from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlencode

from config import get_settings
from tools.builtins.google.maps_client import (
    GoogleMapsApiError,
    _get_client,
    _log_maps_api_call,
    _maps_settings,
)
from tools.builtins.google.maps_serialize import (
    compact_elevation_response,
    compact_street_view_metadata_response,
    compact_timezone_response,
)

STATIC_MAP_URL = "https://maps.googleapis.com/maps/api/staticmap"
STREET_VIEW_URL = "https://maps.googleapis.com/maps/api/streetview"
STREET_VIEW_METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
TIMEZONE_URL = "https://maps.googleapis.com/maps/api/timezone/json"
ELEVATION_URL = "https://maps.googleapis.com/maps/api/elevation/json"

MAP_TYPES = {"roadmap", "satellite", "hybrid", "terrain"}
MARKER_COLORS = {
    "black",
    "brown",
    "green",
    "purple",
    "yellow",
    "blue",
    "gray",
    "orange",
    "red",
    "white",
}
SIZE_PATTERN = re.compile(r"^(\d+)x(\d+)$", re.IGNORECASE)
MAX_STATIC_DIMENSION = 640
ELEVATION_MAX_LOCATIONS = 512


def _api_key() -> str:
    api_key, _, _ = _maps_settings()
    return api_key


def _default_center() -> tuple[float, float]:
    settings = get_settings()
    return settings.google_maps_default_lat, settings.google_maps_default_lng


def _parse_lat_lng_pair(value: str | dict[str, Any]) -> tuple[float, float]:
    if isinstance(value, dict):
        if "lat" not in value or "lng" not in value:
            raise ValueError("location must include lat and lng")
        return float(value["lat"]), float(value["lng"])

    stripped = value.strip()
    if not stripped:
        raise ValueError("location cannot be empty")
    if "," in stripped:
        left, right = stripped.split(",", 1)
        try:
            return float(left.strip()), float(right.strip())
        except ValueError:
            pass
    raise ValueError("location must be 'lat,lng' or {lat,lng}")


def _resolve_center(
    *,
    center: str | dict[str, Any] | None,
    lat: float | None,
    lng: float | None,
) -> str:
    if center is not None:
        if isinstance(center, str):
            stripped = center.strip()
            if not stripped:
                raise ValueError("center cannot be empty")
            if "," in stripped:
                left, right = stripped.split(",", 1)
                try:
                    float(left.strip())
                    float(right.strip())
                    return stripped
                except ValueError:
                    pass
            return stripped
        if isinstance(center, dict):
            resolved_lat, resolved_lng = _parse_lat_lng_pair(center)
            return f"{resolved_lat},{resolved_lng}"
        raise ValueError("center must be an address string or {lat,lng}")

    if lat is not None and lng is not None:
        return f"{lat},{lng}"

    default_lat, default_lng = _default_center()
    return f"{default_lat},{default_lng}"


def _validate_size(size: str) -> str:
    match = SIZE_PATTERN.match(size.strip())
    if not match:
        raise ValueError("size must be WIDTHxHEIGHT, e.g. 640x640")
    width = int(match.group(1))
    height = int(match.group(2))
    if width < 1 or height < 1:
        raise ValueError("size dimensions must be positive")
    if width > MAX_STATIC_DIMENSION or height > MAX_STATIC_DIMENSION:
        raise ValueError(f"size max {MAX_STATIC_DIMENSION}x{MAX_STATIC_DIMENSION}")
    return f"{width}x{height}"


def _validate_zoom(zoom: int) -> int:
    if zoom < 1 or zoom > 21:
        raise ValueError("zoom must be between 1 and 21")
    return zoom


def _format_marker(marker: dict[str, Any]) -> str:
    if "lat" not in marker or "lng" not in marker:
        raise ValueError("each marker must include lat and lng")
    parts: list[str] = []
    color = marker.get("color")
    if color is not None:
        color_text = str(color).lower()
        if color_text not in MARKER_COLORS:
            raise ValueError(f"marker color must be one of: {', '.join(sorted(MARKER_COLORS))}")
        parts.append(f"color:{color_text}")
    label = marker.get("label")
    if label is not None:
        label_text = str(label).upper()[:1]
        if not label_text.isalnum():
            raise ValueError("marker label must be a single alphanumeric character")
        parts.append(f"label:{label_text}")
    parts.append(f"{float(marker['lat'])},{float(marker['lng'])}")
    return "|".join(parts)


def _raise_for_legacy_status(status: str, error_message: str | None) -> None:
    if status == "OK":
        return
    if status in {"ZERO_RESULTS", "NOT_FOUND"}:
        return
    if status == "OVER_QUERY_LIMIT":
        raise GoogleMapsApiError("Google Maps quota exceeded", status=status)
    if status == "REQUEST_DENIED":
        detail = error_message or "request denied"
        raise GoogleMapsApiError(f"Google Maps request denied: {detail}", status=status)
    if status == "INVALID_REQUEST":
        raise GoogleMapsApiError(error_message or "invalid request", status=status)
    raise GoogleMapsApiError(error_message or f"maps request failed: {status}", status=status)


async def _fetch_legacy_json(
    url: str,
    *,
    api: str,
    operation: str,
    params: dict[str, str],
) -> dict[str, Any]:
    api_key = _api_key()
    request_params = {"key": api_key, **params}
    full_url = f"{url}?{urlencode(request_params)}"

    started = time.perf_counter()
    response = await _get_client().get(full_url)
    duration_ms = int((time.perf_counter() - started) * 1000)
    response.raise_for_status()
    payload = response.json()

    status = payload.get("status", "UNKNOWN")
    error_message = payload.get("error_message")
    ok = status in {"OK", "ZERO_RESULTS", "NOT_FOUND"}
    _log_maps_api_call(
        api=api,
        operation=operation,
        duration_ms=duration_ms,
        ok=ok,
        error=None if ok else str(error_message or status),
    )
    _raise_for_legacy_status(status, error_message)
    return payload


def static_map(
    *,
    center: str | dict[str, Any] | None = None,
    lat: float | None = None,
    lng: float | None = None,
    zoom: int = 14,
    size: str = "640x640",
    map_type: str = "roadmap",
    markers: list[dict[str, Any]] | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    center_value = _resolve_center(center=center, lat=lat, lng=lng)
    zoom_value = _validate_zoom(int(zoom))
    size_value = _validate_size(size)
    map_type_value = str(map_type or "roadmap").lower()
    if map_type_value not in MAP_TYPES:
        raise ValueError("map_type must be one of: roadmap, satellite, hybrid, terrain")

    params: list[tuple[str, str]] = [
        ("center", center_value),
        ("zoom", str(zoom_value)),
        ("size", size_value),
        ("maptype", map_type_value),
        ("key", _api_key()),
    ]
    for marker in markers or []:
        params.append(("markers", _format_marker(marker)))
    if path:
        encoded = str(path).strip()
        if encoded.lower().startswith("enc:"):
            path_value = encoded
        else:
            path_value = f"enc:{encoded}"
        params.append(("path", path_value))

    map_url = f"{STATIC_MAP_URL}?{urlencode(params)}"
    return {
        "center": center_value,
        "zoom": zoom_value,
        "size": size_value,
        "map_type": map_type_value,
        "marker_count": len(markers or []),
        "has_path": bool(path),
        "map_url": map_url,
    }


async def street_view_metadata(
    lat: float,
    lng: float,
) -> dict[str, Any]:
    payload = await _fetch_legacy_json(
        STREET_VIEW_METADATA_URL,
        api="street_view",
        operation="metadata",
        params={"location": f"{lat},{lng}"},
    )
    return compact_street_view_metadata_response(payload, lat=lat, lng=lng)


def street_view_image(
    lat: float,
    lng: float,
    *,
    size: str = "640x640",
    heading: int = 0,
    pitch: int = 0,
    fov: int = 90,
) -> dict[str, Any]:
    size_value = _validate_size(size)
    heading_value = int(heading) % 360
    pitch_value = max(-90, min(90, int(pitch)))
    fov_value = max(10, min(120, int(fov)))

    params = {
        "location": f"{lat},{lng}",
        "size": size_value,
        "heading": str(heading_value),
        "pitch": str(pitch_value),
        "fov": str(fov_value),
        "key": _api_key(),
    }
    image_url = f"{STREET_VIEW_URL}?{urlencode(params)}"
    return {
        "lat": lat,
        "lng": lng,
        "size": size_value,
        "heading": heading_value,
        "pitch": pitch_value,
        "fov": fov_value,
        "image_url": image_url,
    }


async def timezone(
    lat: float,
    lng: float,
    *,
    timestamp: int | None = None,
) -> dict[str, Any]:
    ts = int(timestamp) if timestamp is not None else int(time.time())
    payload = await _fetch_legacy_json(
        TIMEZONE_URL,
        api="timezone",
        operation="timezone",
        params={"location": f"{lat},{lng}", "timestamp": str(ts)},
    )
    return compact_timezone_response(payload, lat=lat, lng=lng, timestamp=ts)


async def elevation(
    *,
    lat: float | None = None,
    lng: float | None = None,
    locations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    points: list[tuple[float, float]] = []
    if locations:
        for item in locations:
            points.append(_parse_lat_lng_pair(item))
    elif lat is not None and lng is not None:
        points.append((float(lat), float(lng)))
    else:
        raise ValueError("provide lat/lng or locations array")

    if not points:
        raise ValueError("at least one location is required")
    if len(points) > ELEVATION_MAX_LOCATIONS:
        raise ValueError(f"elevation supports at most {ELEVATION_MAX_LOCATIONS} locations")

    location_param = "|".join(f"{point_lat},{point_lng}" for point_lat, point_lng in points)
    payload = await _fetch_legacy_json(
        ELEVATION_URL,
        api="elevation",
        operation="elevation",
        params={"locations": location_param},
    )
    return compact_elevation_response(payload)
