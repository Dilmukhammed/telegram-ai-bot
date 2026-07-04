from __future__ import annotations

import time
from typing import Any

from tools.builtins.google.maps_client import (
    GoogleMapsApiError,
    _get_client,
    _log_maps_api_call,
    _maps_settings,
)
from tools.builtins.google.maps_urls import build_directions_url
from tools.builtins.google.maps_serialize import (
    compact_route_matrix_response,
    compact_route_response,
)
from tools.builtins.google.transit_provider import apply_transit_route_overlay

ROUTES_BASE_URL = "https://routes.googleapis.com/directions/v2"

ROUTE_FIELD_MASK_BASE = "routes.duration,routes.staticDuration,routes.distanceMeters,routes.localizedValues"
ROUTE_FIELD_MASK_STEPS = ",routes.legs.steps.navigationInstruction,routes.legs.steps.transitDetails"
ROUTE_FIELD_MASK_POLYLINE = ",routes.polyline.encodedPolyline"
MATRIX_FIELD_MASK = "originIndex,destinationIndex,duration,distanceMeters,status,condition"

TRAVEL_MODES = {"DRIVE", "WALK", "TRANSIT"}


def _language_code(language: str | None = None) -> str:
    _, default_language, _ = _maps_settings()
    return language or default_language


def _normalize_travel_mode(travel_mode: str | None) -> str:
    mode = (travel_mode or "DRIVE").upper()
    if mode not in TRAVEL_MODES:
        raise ValueError("travel_mode must be one of: DRIVE, WALK, TRANSIT")
    return mode


def _waypoint_label(value: str | dict[str, Any]) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if value.get("address"):
            return str(value["address"])
        if "lat" in value and "lng" in value:
            return f"{value['lat']},{value['lng']}"
    raise ValueError("waypoint must be an address string or {lat,lng}")


def _waypoint(value: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("waypoint cannot be empty")
        if "," in stripped:
            left, right = stripped.split(",", 1)
            try:
                lat = float(left.strip())
                lng = float(right.strip())
                return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}
            except ValueError:
                pass
        return {"address": stripped}

    if isinstance(value, dict):
        if value.get("address"):
            return {"address": str(value["address"]).strip()}
        if "lat" in value and "lng" in value:
            return {
                "location": {
                    "latLng": {
                        "latitude": float(value["lat"]),
                        "longitude": float(value["lng"]),
                    }
                }
            }

    raise ValueError("waypoint must be an address string or {lat,lng}")


def _matrix_waypoint(value: str | dict[str, Any]) -> dict[str, Any]:
    return {"waypoint": _waypoint(value)}


def _build_maps_directions_link(origin: str, destination: str, travel_mode: str) -> str:
    return build_directions_url(origin, destination, travel_mode=travel_mode)


def _route_field_mask(*, include_steps: bool, include_polyline: bool) -> str:
    mask = ROUTE_FIELD_MASK_BASE
    if include_steps:
        mask += ROUTE_FIELD_MASK_STEPS
    if include_polyline:
        mask += ROUTE_FIELD_MASK_POLYLINE
    return mask


def _parse_routes_error(payload: dict[str, Any]) -> None:
    error = payload.get("error")
    if not error:
        return
    message = error.get("message") or str(error)
    raise GoogleMapsApiError(message, status=error.get("status"))


async def _routes_post(
    path: str,
    body: dict[str, Any],
    *,
    field_mask: str,
    operation: str,
) -> Any:
    api_key, _, _ = _maps_settings()
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": field_mask,
    }

    started = time.perf_counter()
    try:
        response = await _get_client().post(
            f"{ROUTES_BASE_URL}:{path}",
            json=body,
            headers=headers,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            _parse_routes_error(payload)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_maps_api_call(
            api="routes",
            operation=operation,
            duration_ms=duration_ms,
            ok=False,
            error=str(exc),
        )
        raise

    _log_maps_api_call(api="routes", operation=operation, duration_ms=duration_ms, ok=True)
    return payload


def _apply_route_modifiers(body: dict[str, Any], avoid: list[str] | None) -> None:
    if not avoid:
        return
    modifiers: dict[str, bool] = {}
    mapping = {
        "tolls": "avoidTolls",
        "highways": "avoidHighways",
        "ferries": "avoidFerries",
    }
    for item in avoid:
        key = mapping.get(str(item).lower())
        if key:
            modifiers[key] = True
    if modifiers:
        body["routeModifiers"] = modifiers


async def compute_routes(
    origin: str | dict[str, Any],
    destination: str | dict[str, Any],
    *,
    waypoints: list[str | dict[str, Any]] | None = None,
    travel_mode: str = "DRIVE",
    departure_time: str | None = None,
    avoid: list[str] | None = None,
    language: str | None = None,
    include_steps: bool = False,
    include_polyline: bool = False,
) -> dict[str, Any]:
    mode = _normalize_travel_mode(travel_mode)
    origin_label = _waypoint_label(origin)
    destination_label = _waypoint_label(destination)

    body: dict[str, Any] = {
        "origin": _waypoint(origin),
        "destination": _waypoint(destination),
        "travelMode": mode,
        "languageCode": _language_code(language),
        "units": "METRIC",
    }
    if waypoints:
        if len(waypoints) > 25:
            raise ValueError("compute_routes supports at most 25 waypoints")
        body["intermediates"] = [_waypoint(item) for item in waypoints]

    if mode == "DRIVE":
        body["routingPreference"] = "TRAFFIC_AWARE"
    if departure_time:
        body["departureTime"] = departure_time

    _apply_route_modifiers(body, avoid)

    payload = await _routes_post(
        "computeRoutes",
        body,
        field_mask=_route_field_mask(include_steps=include_steps, include_polyline=include_polyline),
        operation="compute_routes",
    )
    result = compact_route_response(
        payload,
        origin=origin_label,
        destination=destination_label,
        travel_mode=mode,
        include_steps=include_steps,
        include_polyline=include_polyline,
        maps_link=_build_maps_directions_link(origin_label, destination_label, mode),
    )
    return await apply_transit_route_overlay(result)


async def compute_route_matrix(
    origins: list[str | dict[str, Any]],
    destinations: list[str | dict[str, Any]],
    *,
    travel_mode: str = "DRIVE",
    departure_time: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    if not origins or not destinations:
        raise ValueError("origins and destinations are required")
    if len(origins) > 10 or len(destinations) > 10:
        raise ValueError("route matrix supports at most 10 origins and 10 destinations")

    mode = _normalize_travel_mode(travel_mode)
    body: dict[str, Any] = {
        "origins": [_matrix_waypoint(item) for item in origins],
        "destinations": [_matrix_waypoint(item) for item in destinations],
        "travelMode": mode,
        "languageCode": _language_code(language),
        "units": "METRIC",
    }
    if mode == "DRIVE":
        body["routingPreference"] = "TRAFFIC_AWARE"
    if departure_time:
        body["departureTime"] = departure_time

    payload = await _routes_post(
        "computeRouteMatrix",
        body,
        field_mask=MATRIX_FIELD_MASK,
        operation="compute_route_matrix",
    )
    result = compact_route_matrix_response(payload)
    result["travel_mode"] = mode
    result["origins"] = [_waypoint_label(item) for item in origins]
    result["destinations"] = [_waypoint_label(item) for item in destinations]
    return result


async def directions(
    origin: str | dict[str, Any],
    destination: str | dict[str, Any],
    *,
    travel_mode: str = "DRIVE",
    departure_time: str | None = None,
    avoid: list[str] | None = None,
    language: str | None = None,
    waypoints: list[str | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return await compute_routes(
        origin,
        destination,
        waypoints=waypoints,
        travel_mode=travel_mode,
        departure_time=departure_time,
        avoid=avoid,
        language=language,
        include_steps=True,
        include_polyline=False,
    )


async def travel_time(
    origin: str | dict[str, Any],
    destination: str | dict[str, Any],
    *,
    travel_mode: str = "DRIVE",
    departure_time: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    result = await compute_routes(
        origin,
        destination,
        travel_mode=travel_mode,
        departure_time=departure_time,
        language=language,
        include_steps=False,
        include_polyline=False,
    )
    return {
        key: result[key]
        for key in (
            "origin",
            "destination",
            "travel_mode",
            "count",
            "google_transit_count",
            "distance_m",
            "distance_text",
            "duration_s",
            "duration_text",
            "duration_in_traffic_s",
            "static_duration_s",
            "google_maps_uri",
            "google_maps_uri_hint",
            "route_note",
        )
        if key in result
    }
