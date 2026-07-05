from __future__ import annotations

from typing import Any

from tools.builtins.google.maps_urls import (
    build_directions_url,
    build_place_url,
    build_search_url,
    normalize_travel_mode,
)
from tools.builtins.google.transit_provider import apply_transit_route_overlay

from tools.builtins.google.maps_client import geocode, geocode_batch, reverse_geocode
from tools.builtins.google.maps_places import (
    place_details,
    place_photo,
    places_autocomplete,
    places_nearby_search,
    places_text_search,
)
from tools.builtins.google.maps_misc import (
    elevation,
    static_map,
    street_view_image,
    street_view_metadata,
    timezone,
)
from tools.builtins.google.maps_routes import (
    compute_route_matrix,
    compute_routes,
    directions,
    travel_time,
)
from tools.builtins.google.maps_serialize import MAPS_URI_USER_HINT
from tools.schema import ToolSpec

_MAPS_URI_TOOL_HINT = (
    " Returns google_maps_uri — share with the user verbatim; "
    "literal & in query string, never &amp;."
)
_MAPS_URL_TOOL_HINT = (
    " Returns url — share with the user verbatim; literal & in query string, never &amp;."
)
_MEDIA_URL_TOOL_HINT = (
    " Returns image/map URL — share with the user verbatim; "
    "literal & in query string, never &amp;."
)

_LANGUAGE_PARAM = {
    "language": {
        "type": "string",
        "description": "Response language (ISO 639-1). Default from bot config (ru).",
    }
}
_REGION_PARAM = {
    "region": {
        "type": "string",
        "description": "Region bias (ISO 3166-1 alpha-2). Default from bot config (uz).",
    }
}


def _build_maps_link(arguments: dict[str, Any]) -> dict[str, Any]:
    link_type = str(arguments.get("link_type", "search")).lower()

    if link_type == "search":
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("query is required for search links")
        url = build_search_url(query)
        return {
            "link_type": "search",
            "query": query,
            "url": url,
            "url_hint": MAPS_URI_USER_HINT,
        }

    if link_type == "directions":
        origin = str(arguments.get("origin", "")).strip()
        destination = str(arguments.get("destination", "")).strip()
        if not origin or not destination:
            raise ValueError("origin and destination are required for directions links")
        travel_mode = str(arguments.get("travel_mode", "DRIVE")).upper()
        url = build_directions_url(origin, destination, travel_mode=travel_mode)
        return {
            "link_type": "directions",
            "origin": origin,
            "destination": destination,
            "travel_mode": travel_mode,
            "count": 0,
            "url": url,
            "google_maps_uri": url,
            "url_hint": MAPS_URI_USER_HINT,
        }

    if link_type == "place":
        place_id = str(arguments.get("place_id", "")).strip()
        if not place_id:
            raise ValueError("place_id is required for place links")
        query = str(arguments.get("query", "")).strip()
        url = build_place_url(place_id, query or None)
        return {
            "link_type": "place",
            "place_id": place_id,
            "query": query or None,
            "url": url,
            "url_hint": MAPS_URI_USER_HINT,
        }

    raise ValueError("link_type must be one of: search, directions, place")


async def _maps_link_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    result = _build_maps_link(arguments)
    return await apply_transit_route_overlay(result)


async def _geocode_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await geocode(
        str(arguments["address"]),
        language=arguments.get("language"),
        region=arguments.get("region"),
    )


async def _reverse_geocode_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await reverse_geocode(
        float(arguments["lat"]),
        float(arguments["lng"]),
        language=arguments.get("language"),
        region=arguments.get("region"),
    )


async def _geocode_batch_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_addresses = arguments.get("addresses") or []
    if not isinstance(raw_addresses, list):
        raise ValueError("addresses must be an array of strings")
    return await geocode_batch(
        [str(address) for address in raw_addresses],
        language=arguments.get("language"),
        region=arguments.get("region"),
    )


GOOGLE_MAPS_GEOCODE = ToolSpec(
    name="google.maps.geocode",
    description="Convert an address or place name to coordinates and formatted address.",
    parameters={
        "type": "object",
        "properties": {
            "address": {
                "type": "string",
                "description": "Address, place name, or landmark to geocode.",
            },
            **_LANGUAGE_PARAM,
            **_REGION_PARAM,
        },
        "required": ["address"],
    },
    handler=_geocode_handler,
    tags=("google", "maps", "geocoding", "read"),
    cache_ttl_seconds=86400,
    rate_limit=(30, 60),
    parallel_safe=True,
    examples=("where is Chorsu Bazaar", "geocode Tashkent airport address"),
)

GOOGLE_MAPS_REVERSE_GEOCODE = ToolSpec(
    name="google.maps.reverse_geocode",
    description="Convert latitude and longitude to a human-readable address.",
    parameters={
        "type": "object",
        "properties": {
            "lat": {"type": "number", "description": "Latitude."},
            "lng": {"type": "number", "description": "Longitude."},
            **_LANGUAGE_PARAM,
            **_REGION_PARAM,
        },
        "required": ["lat", "lng"],
    },
    handler=_reverse_geocode_handler,
    tags=("google", "maps", "geocoding", "read"),
    cache_ttl_seconds=86400,
    rate_limit=(30, 60),
    parallel_safe=True,
    examples=("what address is at these coordinates", "reverse geocode location"),
)

GOOGLE_MAPS_GEOCODE_BATCH = ToolSpec(
    name="google.maps.geocode_batch",
    description="Geocode up to 10 addresses in one call.",
    parameters={
        "type": "object",
        "properties": {
            "addresses": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of addresses to geocode (max 10).",
            },
            **_LANGUAGE_PARAM,
            **_REGION_PARAM,
        },
        "required": ["addresses"],
    },
    handler=_geocode_batch_handler,
    tags=("google", "maps", "geocoding", "read"),
    cache_ttl_seconds=86400,
    rate_limit=(30, 60),
    parallel_safe=False,
    examples=("geocode multiple addresses", "batch geocode delivery stops"),
)

_LOCATION_BIAS_PARAMS = {
    "lat": {"type": "number", "description": "Latitude for location bias/center."},
    "lng": {"type": "number", "description": "Longitude for location bias/center."},
    "radius_m": {
        "type": "number",
        "description": "Search radius in meters. Default 1500.",
        "default": 1500,
    },
}


async def _places_text_search_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await places_text_search(
        str(arguments["text_query"]),
        language=arguments.get("language"),
        region=arguments.get("region"),
        max_results=int(arguments.get("max_results", 20)),
        included_type=arguments.get("included_type"),
        min_rating=arguments.get("min_rating"),
        open_now=arguments.get("open_now"),
        lat=arguments.get("lat"),
        lng=arguments.get("lng"),
        radius_m=arguments.get("radius_m"),
    )


async def _places_nearby_search_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await places_nearby_search(
        lat=arguments.get("lat"),
        lng=arguments.get("lng"),
        radius_m=float(arguments.get("radius_m", 1500)),
        included_types=arguments.get("included_types"),
        max_results=int(arguments.get("max_results", 20)),
        language=arguments.get("language"),
        open_now=arguments.get("open_now"),
    )


async def _place_details_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await place_details(
        str(arguments["place_id"]),
        detail_level=str(arguments.get("detail_level", "contact")),
        language=arguments.get("language"),
    )


async def _place_photo_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await place_photo(
        str(arguments["place_id"]),
        photo_index=int(arguments.get("photo_index", 0)),
        max_width_px=int(arguments.get("max_width_px", 800)),
        max_height_px=arguments.get("max_height_px"),
    )


async def _places_autocomplete_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await places_autocomplete(
        str(arguments["input"]),
        language=arguments.get("language"),
        lat=arguments.get("lat"),
        lng=arguments.get("lng"),
        radius_m=arguments.get("radius_m"),
    )


GOOGLE_MAPS_PLACES_TEXT_SEARCH = ToolSpec(
    name="google.maps.places_text_search",
    description=(
        "Search Google Places by text query (cafes, landmarks, businesses). "
        "Use parameter text_query (not query). Returns place_id for place_details. "
        "Optional lat/lng bias the search; defaults to bot map center if omitted."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text_query": {
                "type": "string",
                "description": "What to search for (required; do not use 'query').",
            },
            "included_type": {
                "type": "string",
                "description": "Optional place type filter, e.g. restaurant, pharmacy.",
            },
            "min_rating": {"type": "number", "description": "Minimum rating filter."},
            "open_now": {"type": "boolean", "description": "Only places open now."},
            "max_results": {"type": "integer", "default": 20},
            **_LANGUAGE_PARAM,
            **_REGION_PARAM,
            **_LOCATION_BIAS_PARAMS,
        },
        "required": ["text_query"],
    },
    handler=_places_text_search_handler,
    tags=("google", "maps", "places", "read"),
    cache_ttl_seconds=3600,
    rate_limit=(15, 60),
    parallel_safe=True,
    examples=("coffee shop in Tashkent center", "find pharmacy near me"),
)

GOOGLE_MAPS_PLACES_NEARBY_SEARCH = ToolSpec(
    name="google.maps.places_nearby_search",
    description=(
        "Find places near coordinates by type (restaurant, atm, etc.). "
        "lat/lng default to bot map center if omitted — geocode first when the user "
        "names a landmark instead of coordinates."
    ),
    parameters={
        "type": "object",
        "properties": {
            "included_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Up to 5 Google place types.",
            },
            "open_now": {"type": "boolean"},
            "max_results": {"type": "integer", "default": 20},
            **_LANGUAGE_PARAM,
            **_LOCATION_BIAS_PARAMS,
        },
    },
    handler=_places_nearby_search_handler,
    tags=("google", "maps", "places", "read"),
    cache_ttl_seconds=3600,
    rate_limit=(15, 60),
    parallel_safe=True,
    examples=("restaurants nearby", "atm near coordinates"),
)

GOOGLE_MAPS_PLACE_DETAILS = ToolSpec(
    name="google.maps.place_details",
    description=(
        "Get detailed info for a place by place_id (from text_search or nearby_search): "
        "hours, phone, website, rating. "
        "detail_level: basic (name/address), contact (+phone/hours), full (+reviews/photos)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "place_id": {"type": "string", "description": "Google place_id."},
            "detail_level": {
                "type": "string",
                "enum": ["basic", "contact", "full"],
                "default": "contact",
                "description": "basic: identity/address; contact: +phone/hours; full: +reviews/photos.",
            },
            **_LANGUAGE_PARAM,
        },
        "required": ["place_id"],
    },
    handler=_place_details_handler,
    tags=("google", "maps", "places", "read"),
    cache_ttl_seconds=21600,
    rate_limit=(20, 60),
    parallel_safe=True,
    examples=("place opening hours", "phone number for restaurant"),
)

GOOGLE_MAPS_PLACE_PHOTO = ToolSpec(
    name="google.maps.place_photo",
    description=(
        "Get a photo URL for a place by place_id (returns photo_uri only)."
        + _MEDIA_URL_TOOL_HINT
    ),
    parameters={
        "type": "object",
        "properties": {
            "place_id": {"type": "string", "description": "Google place_id."},
            "photo_index": {"type": "integer", "default": 0},
            "max_width_px": {"type": "integer", "default": 800},
            "max_height_px": {"type": "integer"},
        },
        "required": ["place_id"],
    },
    handler=_place_photo_handler,
    tags=("google", "maps", "places", "read"),
    cache_ttl_seconds=86400,
    rate_limit=(20, 60),
    parallel_safe=True,
    examples=("photo of restaurant", "place image url"),
)

GOOGLE_MAPS_PLACES_AUTOCOMPLETE = ToolSpec(
    name="google.maps.places_autocomplete",
    description="Autocomplete partial place or address input for disambiguation.",
    parameters={
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "Partial user input."},
            **_LANGUAGE_PARAM,
            **_LOCATION_BIAS_PARAMS,
        },
        "required": ["input"],
    },
    handler=_places_autocomplete_handler,
    tags=("google", "maps", "places", "read"),
    cache_ttl_seconds=600,
    rate_limit=(15, 60),
    parallel_safe=True,
    examples=("autocomplete address partial", "suggest places while typing"),
)

GOOGLE_MAPS_PLACES_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_MAPS_PLACES_TEXT_SEARCH,
    GOOGLE_MAPS_PLACES_NEARBY_SEARCH,
    GOOGLE_MAPS_PLACE_DETAILS,
    GOOGLE_MAPS_PLACE_PHOTO,
    GOOGLE_MAPS_PLACES_AUTOCOMPLETE,
)

_WAYPOINT_SCHEMA = {
    "type": "string",
    "description": "Address, place name, or 'lat,lng' coordinates.",
}
_TRAVEL_MODE_PARAM = {
    "travel_mode": {
        "type": "string",
        "enum": ["DRIVE", "WALK", "TRANSIT"],
        "default": "DRIVE",
        "description": "DRIVE (default, traffic-aware), WALK, or TRANSIT.",
    }
}
_DEPARTURE_TIME_PARAM = {
    "departure_time": {
        "type": "string",
        "description": "RFC3339 departure time for traffic-aware routing.",
    }
}
_AVOID_PARAM = {
    "avoid": {
        "type": "array",
        "items": {"type": "string", "enum": ["tolls", "highways", "ferries"]},
        "description": "Road features to avoid (DRIVE only).",
    }
}


async def _compute_routes_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await compute_routes(
        arguments["origin"],
        arguments["destination"],
        waypoints=arguments.get("waypoints"),
        travel_mode=str(arguments.get("travel_mode", "DRIVE")),
        departure_time=arguments.get("departure_time"),
        avoid=arguments.get("avoid"),
        language=arguments.get("language"),
        include_steps=bool(arguments.get("include_steps", False)),
        include_polyline=bool(arguments.get("include_polyline", False)),
    )


async def _compute_route_matrix_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await compute_route_matrix(
        list(arguments["origins"]),
        list(arguments["destinations"]),
        travel_mode=str(arguments.get("travel_mode", "DRIVE")),
        departure_time=arguments.get("departure_time"),
        language=arguments.get("language"),
    )


async def _directions_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await directions(
        arguments["origin"],
        arguments["destination"],
        waypoints=arguments.get("waypoints"),
        travel_mode=str(arguments.get("travel_mode", "DRIVE")),
        departure_time=arguments.get("departure_time"),
        avoid=arguments.get("avoid"),
        language=arguments.get("language"),
    )


async def _travel_time_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await travel_time(
        arguments["origin"],
        arguments["destination"],
        travel_mode=str(arguments.get("travel_mode", "DRIVE")),
        departure_time=arguments.get("departure_time"),
        language=arguments.get("language"),
    )


GOOGLE_MAPS_COMPUTE_ROUTES = ToolSpec(
    name="google.maps.compute_routes",
    description=(
        "Low-level route API with optional turn-by-turn steps and polyline. "
        "Prefer directions for navigation text or travel_time for ETA-only queries."
        + _MAPS_URI_TOOL_HINT
    ),
    parameters={
        "type": "object",
        "properties": {
            "origin": _WAYPOINT_SCHEMA,
            "destination": _WAYPOINT_SCHEMA,
            "waypoints": {
                "type": "array",
                "items": _WAYPOINT_SCHEMA,
                "description": "Optional intermediate stops (max 25).",
            },
            **_TRAVEL_MODE_PARAM,
            **_DEPARTURE_TIME_PARAM,
            **_AVOID_PARAM,
            **_LANGUAGE_PARAM,
            "include_steps": {"type": "boolean", "default": False},
            "include_polyline": {"type": "boolean", "default": False},
        },
        "required": ["origin", "destination"],
    },
    handler=_compute_routes_handler,
    tags=("google", "maps", "routes", "read"),
    cache_ttl_seconds=1800,
    rate_limit=(10, 60),
    parallel_safe=True,
    examples=("route from airport to city center", "driving directions with steps"),
)

GOOGLE_MAPS_COMPUTE_ROUTE_MATRIX = ToolSpec(
    name="google.maps.compute_route_matrix",
    description="Compute travel times/distances between multiple origins and destinations.",
    parameters={
        "type": "object",
        "properties": {
            "origins": {
                "type": "array",
                "items": _WAYPOINT_SCHEMA,
                "description": "Up to 10 origin points.",
            },
            "destinations": {
                "type": "array",
                "items": _WAYPOINT_SCHEMA,
                "description": "Up to 10 destination points.",
            },
            **_TRAVEL_MODE_PARAM,
            **_DEPARTURE_TIME_PARAM,
            **_LANGUAGE_PARAM,
        },
        "required": ["origins", "destinations"],
    },
    handler=_compute_route_matrix_handler,
    tags=("google", "maps", "routes", "read"),
    cache_ttl_seconds=1800,
    rate_limit=(10, 60),
    parallel_safe=True,
    examples=("travel time matrix between offices", "compare ETA to multiple places"),
)

GOOGLE_MAPS_DIRECTIONS = ToolSpec(
    name="google.maps.directions",
    description=(
        "Turn-by-turn directions between two points (alias of compute_routes with steps). "
        "Prefer travel_time when the user only needs ETA/distance."
        + _MAPS_URI_TOOL_HINT
    ),
    parameters={
        "type": "object",
        "properties": {
            "origin": _WAYPOINT_SCHEMA,
            "destination": _WAYPOINT_SCHEMA,
            "waypoints": {
                "type": "array",
                "items": _WAYPOINT_SCHEMA,
                "description": "Optional intermediate stops (max 25).",
            },
            **_TRAVEL_MODE_PARAM,
            **_DEPARTURE_TIME_PARAM,
            **_AVOID_PARAM,
            **_LANGUAGE_PARAM,
        },
        "required": ["origin", "destination"],
    },
    handler=_directions_handler,
    tags=("google", "maps", "routes", "read"),
    cache_ttl_seconds=1800,
    rate_limit=(10, 60),
    parallel_safe=False,
    examples=("how to drive to Chorsu Bazaar", "transit directions to airport"),
)

GOOGLE_MAPS_TRAVEL_TIME = ToolSpec(
    name="google.maps.travel_time",
    description=(
        "ETA and distance only — no turn-by-turn steps. "
        "Fastest choice when the user asks how long or how far."
        + _MAPS_URI_TOOL_HINT
    ),
    parameters={
        "type": "object",
        "properties": {
            "origin": _WAYPOINT_SCHEMA,
            "destination": _WAYPOINT_SCHEMA,
            **_TRAVEL_MODE_PARAM,
            **_DEPARTURE_TIME_PARAM,
            **_LANGUAGE_PARAM,
        },
        "required": ["origin", "destination"],
    },
    handler=_travel_time_handler,
    tags=("google", "maps", "routes", "read"),
    cache_ttl_seconds=1800,
    rate_limit=(10, 60),
    parallel_safe=True,
    examples=("how long to drive to airport", "walking time between places"),
)

GOOGLE_MAPS_ROUTES_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_MAPS_COMPUTE_ROUTES,
    GOOGLE_MAPS_COMPUTE_ROUTE_MATRIX,
    GOOGLE_MAPS_DIRECTIONS,
    GOOGLE_MAPS_TRAVEL_TIME,
)

_COORD_PARAMS = {
    "lat": {"type": "number", "description": "Latitude."},
    "lng": {"type": "number", "description": "Longitude."},
}
_MARKER_SCHEMA = {
    "type": "object",
    "properties": {
        "lat": {"type": "number"},
        "lng": {"type": "number"},
        "label": {"type": "string", "description": "Single character marker label."},
        "color": {
            "type": "string",
            "enum": ["black", "brown", "green", "purple", "yellow", "blue", "gray", "orange", "red", "white"],
        },
    },
    "required": ["lat", "lng"],
}


async def _static_map_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return static_map(
        center=arguments.get("center"),
        lat=arguments.get("lat"),
        lng=arguments.get("lng"),
        zoom=int(arguments.get("zoom", 14)),
        size=str(arguments.get("size", "640x640")),
        map_type=str(arguments.get("map_type", "roadmap")),
        markers=arguments.get("markers"),
        path=arguments.get("path"),
    )


async def _street_view_metadata_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await street_view_metadata(float(arguments["lat"]), float(arguments["lng"]))


async def _street_view_image_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return street_view_image(
        float(arguments["lat"]),
        float(arguments["lng"]),
        size=str(arguments.get("size", "640x640")),
        heading=int(arguments.get("heading", 0)),
        pitch=int(arguments.get("pitch", 0)),
        fov=int(arguments.get("fov", 90)),
    )


async def _timezone_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    timestamp = arguments.get("timestamp")
    return await timezone(
        float(arguments["lat"]),
        float(arguments["lng"]),
        timestamp=int(timestamp) if timestamp is not None else None,
    )


async def _elevation_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return await elevation(
        lat=arguments.get("lat"),
        lng=arguments.get("lng"),
        locations=arguments.get("locations"),
    )


GOOGLE_MAPS_STATIC_MAP = ToolSpec(
    name="google.maps.static_map",
    description=(
        "Build a Static Maps image URL with center, markers, and optional route path. "
        "center/lat/lng default to bot map center if omitted."
        + _MEDIA_URL_TOOL_HINT
    ),
    parameters={
        "type": "object",
        "properties": {
            "center": {
                "type": "string",
                "description": "Map center as address or 'lat,lng'. Uses bot default if omitted.",
            },
            **_COORD_PARAMS,
            "zoom": {"type": "integer", "default": 14, "description": "Zoom level 1-21."},
            "size": {"type": "string", "default": "640x640", "description": "Image size WIDTHxHEIGHT (max 640)."},
            "map_type": {
                "type": "string",
                "enum": ["roadmap", "satellite", "hybrid", "terrain"],
                "default": "roadmap",
            },
            "markers": {
                "type": "array",
                "items": _MARKER_SCHEMA,
                "description": "Optional map markers.",
            },
            "path": {
                "type": "string",
                "description": "Optional encoded polyline from a route (with or without enc: prefix).",
            },
        },
    },
    handler=_static_map_handler,
    tags=("google", "maps", "static", "read"),
    cache_ttl_seconds=3600,
    rate_limit=(5, 60),
    parallel_safe=True,
    examples=("show Chorsu on a map", "static map with markers"),
)

GOOGLE_MAPS_STREET_VIEW_METADATA = ToolSpec(
    name="google.maps.street_view_metadata",
    description="Check whether Street View imagery exists for coordinates.",
    parameters={
        "type": "object",
        "properties": _COORD_PARAMS,
        "required": ["lat", "lng"],
    },
    handler=_street_view_metadata_handler,
    tags=("google", "maps", "static", "read"),
    cache_ttl_seconds=86400,
    rate_limit=(5, 60),
    parallel_safe=True,
    examples=("is street view available here", "panorama exists at coordinates"),
)

GOOGLE_MAPS_STREET_VIEW_IMAGE = ToolSpec(
    name="google.maps.street_view_image",
    description=(
        "Build a Street View panorama image URL for coordinates."
        + _MEDIA_URL_TOOL_HINT
    ),
    parameters={
        "type": "object",
        "properties": {
            **_COORD_PARAMS,
            "size": {"type": "string", "default": "640x640"},
            "heading": {"type": "integer", "default": 0, "description": "Compass heading 0-360."},
            "pitch": {"type": "integer", "default": 0, "description": "Up/down angle -90 to 90."},
            "fov": {"type": "integer", "default": 90, "description": "Field of view 10-120."},
        },
        "required": ["lat", "lng"],
    },
    handler=_street_view_image_handler,
    tags=("google", "maps", "static", "read"),
    cache_ttl_seconds=3600,
    rate_limit=(5, 60),
    parallel_safe=True,
    examples=("street view photo url", "panorama image at location"),
)

GOOGLE_MAPS_TIMEZONE = ToolSpec(
    name="google.maps.timezone",
    description="Get timezone ID and UTC offset for coordinates.",
    parameters={
        "type": "object",
        "properties": {
            **_COORD_PARAMS,
            "timestamp": {
                "type": "integer",
                "description": "Unix timestamp for DST calculation. Default: now.",
            },
        },
        "required": ["lat", "lng"],
    },
    handler=_timezone_handler,
    tags=("google", "maps", "geocoding", "read"),
    cache_ttl_seconds=604800,
    rate_limit=(30, 60),
    parallel_safe=True,
    examples=("timezone for Tashkent coordinates", "utc offset at lat lng"),
)

GOOGLE_MAPS_ELEVATION = ToolSpec(
    name="google.maps.elevation",
    description=(
        "Get elevation above sea level for coordinate point(s). "
        "Provide lat+lng for one point or locations[] for multiple (required)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "lat": {"type": "number", "description": "Latitude (with lng for a single point)."},
            "lng": {"type": "number", "description": "Longitude (with lat for a single point)."},
            "locations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": _COORD_PARAMS,
                    "required": ["lat", "lng"],
                },
                "description": "Multiple points — use instead of single lat/lng.",
            },
        },
    },
    handler=_elevation_handler,
    tags=("google", "maps", "read"),
    cache_ttl_seconds=604800,
    rate_limit=(30, 60),
    parallel_safe=True,
    examples=("elevation at coordinates", "altitude above sea level"),
)

GOOGLE_MAPS_STATIC_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_MAPS_STATIC_MAP,
    GOOGLE_MAPS_STREET_VIEW_METADATA,
    GOOGLE_MAPS_STREET_VIEW_IMAGE,
    GOOGLE_MAPS_TIMEZONE,
    GOOGLE_MAPS_ELEVATION,
)

GOOGLE_MAPS_MAPS_LINK = ToolSpec(
    name="google.maps.maps_link",
    description=(
        "Build a Google Maps URL for search, directions, or a place — no API call. "
        "Use when the user only needs a link (faster than route tools). "
        "Supports BICYCLE travel mode for directions links."
        + _MAPS_URL_TOOL_HINT
    ),
    parameters={
        "type": "object",
        "properties": {
            "link_type": {
                "type": "string",
                "enum": ["search", "directions", "place"],
                "default": "search",
            },
            "query": {"type": "string", "description": "Search text or place label."},
            "origin": {"type": "string", "description": "Directions origin address or place."},
            "destination": {
                "type": "string",
                "description": "Directions destination address or place.",
            },
            "place_id": {"type": "string", "description": "Google place_id for place links."},
            "travel_mode": {
                "type": "string",
                "enum": ["DRIVE", "WALK", "TRANSIT", "BICYCLE"],
                "default": "DRIVE",
                "description": "Directions travel mode for the URL.",
            },
        },
    },
    handler=_maps_link_handler,
    tags=("google", "maps", "read"),
    parallel_safe=True,
    examples=("open map search for Chorsu Bazaar", "google maps directions link"),
)

GOOGLE_MAPS_GEOCODING_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_MAPS_GEOCODE,
    GOOGLE_MAPS_REVERSE_GEOCODE,
    GOOGLE_MAPS_GEOCODE_BATCH,
)

GOOGLE_MAPS_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_MAPS_GEOCODING_TOOLS
    + GOOGLE_MAPS_PLACES_TOOLS
    + GOOGLE_MAPS_ROUTES_TOOLS
    + GOOGLE_MAPS_STATIC_TOOLS
    + (GOOGLE_MAPS_MAPS_LINK,)
)
