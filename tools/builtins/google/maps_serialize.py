from __future__ import annotations

from typing import Any

MAPS_URI_USER_HINT = (
    "Share google_maps_uri with the user as plain text or a markdown link; "
    "keep literal & between query params — never &amp; or HTML escaping."
)


def normalize_place_id(place_id: str | None) -> str | None:
    if not place_id:
        return None
    if place_id.startswith("places/"):
        return place_id.split("/", 1)[1]
    return place_id


def place_resource_name(place_id: str) -> str:
    if place_id.startswith("places/"):
        return place_id
    return f"places/{place_id}"


def _display_name_text(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    return value.get("text")


def compact_place(place: dict[str, Any]) -> dict[str, Any]:
    display_name = place.get("displayName") or {}
    location = place.get("location") or {}
    opening = place.get("currentOpeningHours") or place.get("regularOpeningHours") or {}

    result: dict[str, Any] = {
        "place_id": normalize_place_id(place.get("id")),
        "name": _display_name_text(display_name),
        "address": place.get("formattedAddress"),
        "lat": location.get("latitude"),
        "lng": location.get("longitude"),
        "rating": place.get("rating"),
        "user_rating_count": place.get("userRatingCount"),
        "price_level": place.get("priceLevel"),
        "google_maps_uri": place.get("googleMapsUri"),
        "types": place.get("types") or [],
        "business_status": place.get("businessStatus"),
    }

    if opening:
        result["open_now"] = opening.get("openNow")
        weekday_descriptions = opening.get("weekdayDescriptions") or []
        if weekday_descriptions:
            result["hours_week"] = weekday_descriptions

    phone = place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber")
    if phone:
        result["phone"] = phone
    if place.get("websiteUri"):
        result["website"] = place.get("websiteUri")

    reviews = place.get("reviews") or []
    if reviews:
        first = reviews[0]
        result["review_snippet"] = {
            "rating": first.get("rating"),
            "text": _display_name_text(first.get("text")),
            "author": _display_name_text((first.get("authorAttribution") or {}).get("displayName")),
        }

    photos = place.get("photos") or []
    if photos:
        result["photos"] = [
            {
                "photo_name": photo.get("name"),
                "width_px": photo.get("widthPx"),
                "height_px": photo.get("heightPx"),
            }
            for photo in photos[:3]
        ]

    return {key: value for key, value in result.items() if value is not None}


def compact_places_search_response(payload: dict[str, Any], *, query: str) -> dict[str, Any]:
    places = payload.get("places") or []
    return {
        "query": query,
        "count": len(places),
        "places": [compact_place(place) for place in places],
    }


def compact_autocomplete_response(payload: dict[str, Any], *, input_text: str) -> dict[str, Any]:
    suggestions = payload.get("suggestions") or []
    items: list[dict[str, Any]] = []
    for suggestion in suggestions:
        place_prediction = suggestion.get("placePrediction")
        if not place_prediction:
            continue
        items.append(
            {
                "place_id": normalize_place_id(
                    place_prediction.get("placeId") or place_prediction.get("place")
                ),
                "text": place_prediction.get("text", {}).get("text"),
                "main_text": place_prediction.get("structuredFormat", {})
                .get("mainText", {})
                .get("text"),
                "secondary_text": place_prediction.get("structuredFormat", {})
                .get("secondaryText", {})
                .get("text"),
            }
        )
    return {
        "input": input_text,
        "count": len(items),
        "suggestions": items,
    }


def compact_geocode_result(result: dict[str, Any]) -> dict[str, Any]:
    geometry = result.get("geometry") or {}
    location = geometry.get("location") or {}
    return {
        "formatted_address": result.get("formatted_address"),
        "lat": location.get("lat"),
        "lng": location.get("lng"),
        "place_id": result.get("place_id"),
        "location_type": geometry.get("location_type"),
        "types": result.get("types") or [],
    }


def compact_geocode_response(payload: dict[str, Any], *, query: str) -> dict[str, Any]:
    status = payload.get("status", "UNKNOWN")
    results = payload.get("results") or []
    return {
        "query": query,
        "status": status,
        "count": len(results),
        "results": [compact_geocode_result(item) for item in results],
    }


def parse_duration_seconds(value: str | None) -> int | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("s"):
        text = text[:-1]
    try:
        return int(float(text))
    except ValueError:
        return None


def format_duration(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    if seconds < 60:
        return f"{seconds} sec"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    remaining = minutes % 60
    if remaining:
        return f"{hours} h {remaining} min"
    return f"{hours} h"


def format_distance_meters(distance_m: int | None) -> str | None:
    if distance_m is None:
        return None
    if distance_m >= 1000:
        return f"{distance_m / 1000:.1f} km"
    return f"{distance_m} m"


def _extract_step_instructions(route: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    for leg in route.get("legs") or []:
        for step in leg.get("steps") or []:
            navigation = step.get("navigationInstruction") or {}
            instruction = navigation.get("instructions")
            if instruction:
                steps.append(str(instruction))
                continue
            transit = step.get("transitDetails") or {}
            if transit:
                line = transit.get("transitLine") or {}
                vehicle = line.get("vehicle") or {}
                label = line.get("name") or line.get("nameShort") or vehicle.get("type")
                stop = (transit.get("departureStop") or {}).get("name")
                if label and stop:
                    steps.append(f"Transit {label} from {stop}")
                elif label:
                    steps.append(f"Transit {label}")
    return steps


def compact_route_response(
    payload: dict[str, Any],
    *,
    origin: str,
    destination: str,
    travel_mode: str,
    include_steps: bool,
    include_polyline: bool,
    maps_link: str | None = None,
) -> dict[str, Any]:
    routes = payload.get("routes") or []
    if not routes:
        result: dict[str, Any] = {
            "origin": origin,
            "destination": destination,
            "travel_mode": travel_mode,
            "count": 0,
            "google_maps_uri": maps_link,
        }
        if maps_link:
            result["google_maps_uri_hint"] = MAPS_URI_USER_HINT
        return result

    route = routes[0]
    localized = route.get("localizedValues") or {}
    distance_m = route.get("distanceMeters")
    duration_s = parse_duration_seconds(route.get("duration"))
    static_duration_s = parse_duration_seconds(route.get("staticDuration"))

    result: dict[str, Any] = {
        "origin": origin,
        "destination": destination,
        "travel_mode": travel_mode,
        "count": len(routes),
        "distance_m": distance_m,
        "distance_text": (localized.get("distance") or {}).get("text") or format_distance_meters(distance_m),
        "duration_s": duration_s,
        "duration_text": (localized.get("duration") or {}).get("text") or format_duration(duration_s),
        "static_duration_s": static_duration_s,
        "google_maps_uri": maps_link,
    }

    if duration_s and static_duration_s and duration_s > static_duration_s:
        result["duration_in_traffic_s"] = duration_s

    if include_steps:
        result["steps"] = _extract_step_instructions(route)

    if include_polyline:
        polyline = (route.get("polyline") or {}).get("encodedPolyline")
        if polyline:
            result["polyline"] = polyline

    if maps_link:
        result["google_maps_uri_hint"] = MAPS_URI_USER_HINT

    return {key: value for key, value in result.items() if value is not None}


def compact_route_matrix_response(payload: list[dict[str, Any]] | dict[str, Any]) -> dict[str, Any]:
    items = payload if isinstance(payload, list) else payload.get("elements") or []
    elements: list[dict[str, Any]] = []
    for item in items:
        duration_s = parse_duration_seconds(item.get("duration"))
        distance_m = item.get("distanceMeters")
        elements.append(
            {
                "origin_index": item.get("originIndex"),
                "destination_index": item.get("destinationIndex"),
                "distance_m": distance_m,
                "distance_text": format_distance_meters(distance_m),
                "duration_s": duration_s,
                "duration_text": format_duration(duration_s),
                "status": item.get("status"),
                "condition": item.get("condition"),
            }
        )
    return {"count": len(elements), "elements": elements}


def compact_street_view_metadata_response(
    payload: dict[str, Any],
    *,
    lat: float,
    lng: float,
) -> dict[str, Any]:
    status = payload.get("status", "UNKNOWN")
    available = status == "OK"
    result: dict[str, Any] = {
        "lat": lat,
        "lng": lng,
        "available": available,
        "status": status,
    }
    if available:
        location = payload.get("location") or {}
        result["pano_id"] = payload.get("pano_id")
        result["pano_lat"] = location.get("lat")
        result["pano_lng"] = location.get("lng")
        if payload.get("date"):
            result["capture_date"] = payload["date"]
    return result


def compact_timezone_response(
    payload: dict[str, Any],
    *,
    lat: float,
    lng: float,
    timestamp: int,
) -> dict[str, Any]:
    raw_offset = payload.get("rawOffset")
    dst_offset = payload.get("dstOffset")
    total_offset = None
    if isinstance(raw_offset, (int, float)) and isinstance(dst_offset, (int, float)):
        total_offset = int(raw_offset + dst_offset)

    return {
        "lat": lat,
        "lng": lng,
        "timestamp": timestamp,
        "time_zone_id": payload.get("timeZoneId"),
        "time_zone_name": payload.get("timeZoneName"),
        "raw_offset_s": raw_offset,
        "dst_offset_s": dst_offset,
        "total_offset_s": total_offset,
    }


def compact_elevation_response(payload: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        location = item.get("location") or {}
        results.append(
            {
                "lat": location.get("lat"),
                "lng": location.get("lng"),
                "elevation_m": item.get("elevation"),
                "resolution_m": item.get("resolution"),
            }
        )
    return {"count": len(results), "results": results}
