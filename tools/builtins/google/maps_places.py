from __future__ import annotations

import logging
import time
from typing import Any

from config import get_settings
from tools.builtins.google.maps_client import (
    GoogleMapsApiError,
    _get_client,
    _log_maps_api_call,
    _maps_settings,
)
from tools.builtins.google.maps_serialize import (
    compact_autocomplete_response,
    compact_place,
    compact_places_search_response,
    normalize_place_id,
    place_resource_name,
)

logger = logging.getLogger(__name__)

PLACES_BASE_URL = "https://places.googleapis.com/v1"

SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,"
    "places.rating,places.userRatingCount,places.googleMapsUri,places.types,"
    "places.businessStatus,places.currentOpeningHours"
)

DETAIL_FIELD_MASKS = {
    "basic": "id,displayName,formattedAddress,location,googleMapsUri,types,businessStatus",
    "contact": (
        "id,displayName,formattedAddress,location,googleMapsUri,types,businessStatus,"
        "nationalPhoneNumber,websiteUri,regularOpeningHours,currentOpeningHours"
    ),
    "full": (
        "id,displayName,formattedAddress,location,googleMapsUri,types,businessStatus,"
        "nationalPhoneNumber,websiteUri,regularOpeningHours,currentOpeningHours,"
        "rating,userRatingCount,reviews,photos,priceLevel"
    ),
}


def _default_center() -> tuple[float, float]:
    settings = get_settings()
    return settings.google_maps_default_lat, settings.google_maps_default_lng


def _language_code(language: str | None = None) -> str:
    _, default_language, _ = _maps_settings()
    return language or default_language


def _circle(location: dict[str, float], radius_m: float) -> dict[str, Any]:
    return {
        "circle": {
            "center": {
                "latitude": location["lat"],
                "longitude": location["lng"],
            },
            "radius": float(radius_m),
        }
    }


def _parse_places_payload(payload: dict[str, Any]) -> None:
    error = payload.get("error")
    if not error:
        return
    message = error.get("message") or str(error)
    raise GoogleMapsApiError(message, status=error.get("status"))


async def _places_post(
    path: str,
    body: dict[str, Any],
    *,
    field_mask: str | None,
    operation: str,
) -> dict[str, Any]:
    api_key, _, _ = _maps_settings()
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
    }
    if field_mask:
        headers["X-Goog-FieldMask"] = field_mask

    started = time.perf_counter()
    try:
        response = await _get_client().post(f"{PLACES_BASE_URL}/{path}", json=body, headers=headers)
        duration_ms = int((time.perf_counter() - started) * 1000)
        response.raise_for_status()
        payload = response.json()
        _parse_places_payload(payload)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_maps_api_call(
            api="places",
            operation=operation,
            duration_ms=duration_ms,
            ok=False,
            error=str(exc),
        )
        raise
    _log_maps_api_call(api="places", operation=operation, duration_ms=duration_ms, ok=True)
    return payload


async def _places_get(
    path: str,
    *,
    field_mask: str | None = None,
    operation: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    api_key, _, _ = _maps_settings()
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
    }
    if field_mask:
        headers["X-Goog-FieldMask"] = field_mask

    started = time.perf_counter()
    try:
        response = await _get_client().get(
            f"{PLACES_BASE_URL}/{path}",
            headers=headers,
            params=params or {},
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        response.raise_for_status()
        payload = response.json()
        _parse_places_payload(payload)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_maps_api_call(
            api="places",
            operation=operation,
            duration_ms=duration_ms,
            ok=False,
            error=str(exc),
        )
        raise
    _log_maps_api_call(api="places", operation=operation, duration_ms=duration_ms, ok=True)
    return payload


async def places_text_search(
    text_query: str,
    *,
    language: str | None = None,
    region: str | None = None,
    max_results: int = 10,
    included_type: str | None = None,
    min_rating: float | None = None,
    open_now: bool | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_m: float | None = None,
) -> dict[str, Any]:
    _, _, default_region = _maps_settings()
    page_size = min(max(int(max_results), 1), 20)
    body: dict[str, Any] = {
        "textQuery": text_query,
        "languageCode": _language_code(language),
        "pageSize": page_size,
    }
    if region or default_region:
        body["regionCode"] = region or default_region
    if included_type:
        body["includedType"] = included_type
    if min_rating is not None:
        body["minRating"] = float(min_rating)
    if open_now is not None:
        body["openNow"] = bool(open_now)
    if lat is not None and lng is not None:
        body["locationBias"] = _circle({"lat": lat, "lng": lng}, radius_m or 1500.0)

    payload = await _places_post(
        "places:searchText",
        body,
        field_mask=SEARCH_FIELD_MASK,
        operation="places_text_search",
    )
    return compact_places_search_response(payload, query=text_query)


async def places_nearby_search(
    *,
    lat: float | None = None,
    lng: float | None = None,
    radius_m: float = 1500,
    included_types: list[str] | None = None,
    max_results: int = 10,
    language: str | None = None,
    open_now: bool | None = None,
) -> dict[str, Any]:
    center_lat, center_lng = _default_center()
    if lat is not None:
        center_lat = lat
    if lng is not None:
        center_lng = lng

    radius = min(max(float(radius_m), 1.0), 50000.0)
    max_result_count = min(max(int(max_results), 1), 20)
    body: dict[str, Any] = {
        "languageCode": _language_code(language),
        "maxResultCount": max_result_count,
        "locationRestriction": _circle({"lat": center_lat, "lng": center_lng}, radius),
    }
    if included_types:
        body["includedTypes"] = included_types[:5]
    if open_now is not None:
        body["openNow"] = bool(open_now)

    payload = await _places_post(
        "places:searchNearby",
        body,
        field_mask=SEARCH_FIELD_MASK,
        operation="places_nearby_search",
    )
    query = f"{center_lat},{center_lng} r={radius}"
    return compact_places_search_response(payload, query=query)


async def place_details(
    place_id: str,
    *,
    detail_level: str = "contact",
    language: str | None = None,
) -> dict[str, Any]:
    level = detail_level if detail_level in DETAIL_FIELD_MASKS else "contact"
    resource = place_resource_name(place_id)
    payload = await _places_get(
        resource,
        field_mask=DETAIL_FIELD_MASKS[level],
        operation="place_details",
        params={"languageCode": _language_code(language)},
    )
    return {
        "detail_level": level,
        "place": compact_place(payload),
    }


async def place_photo(
    place_id: str,
    *,
    photo_index: int = 0,
    max_width_px: int = 800,
    max_height_px: int | None = None,
) -> dict[str, Any]:
    details = await place_details(place_id, detail_level="full")
    photos = details["place"].get("photos") or []
    if not photos:
        raise ValueError("Place has no photos")

    index = max(int(photo_index), 0)
    if index >= len(photos):
        raise ValueError(f"photo_index out of range (0..{len(photos) - 1})")

    photo_name = photos[index].get("photo_name")
    if not photo_name:
        raise ValueError("Photo metadata is missing photo_name")

    params: dict[str, Any] = {
        "skipHttpRedirect": "true",
        "maxWidthPx": min(max(int(max_width_px), 1), 4800),
    }
    if max_height_px is not None:
        params["maxHeightPx"] = min(max(int(max_height_px), 1), 4800)

    payload = await _places_get(
        f"{photo_name}/media",
        field_mask=None,
        operation="place_photo",
        params=params,
    )
    return {
        "place_id": normalize_place_id(place_id),
        "photo_index": index,
        "photo_name": photo_name,
        "photo_uri": payload.get("photoUri"),
    }


async def places_autocomplete(
    input_text: str,
    *,
    language: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_m: float | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "input": input_text,
        "languageCode": _language_code(language),
    }
    if lat is not None and lng is not None:
        body["locationBias"] = _circle({"lat": lat, "lng": lng}, radius_m or 1500.0)
    else:
        center_lat, center_lng = _default_center()
        body["locationBias"] = _circle({"lat": center_lat, "lng": center_lng}, radius_m or 5000.0)

    payload = await _places_post(
        "places:autocomplete",
        body,
        field_mask=None,
        operation="places_autocomplete",
    )
    return compact_autocomplete_response(payload, input_text=input_text)
