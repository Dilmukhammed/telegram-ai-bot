from config import get_settings


def cache_max_ttl_seconds() -> int:
    return get_settings().tool_cache_max_ttl


def cache_ttl_for_tool(tool_name: str, spec_ttl: int | None) -> int | None:
    if spec_ttl is None:
        return None

    settings = get_settings()
    overrides = {
        "exa.web_search": settings.exa_search_cache_ttl,
        "exa.web_fetch": settings.exa_fetch_cache_ttl,
    }
    ttl = overrides.get(tool_name)
    if ttl is None:
        ttl = spec_ttl
    return min(max(ttl, 0), cache_max_ttl_seconds())


def rate_limit_for_tool(tool_name: str, spec_limit: tuple[int, int] | None) -> tuple[int, int] | None:
    settings = get_settings()
    overrides = {
        "exa.web_search": settings.rate_limit_exa_search,
        "exa.web_fetch": settings.rate_limit_exa_fetch,
        "google.maps.geocode": settings.rate_limit_maps_geocode,
        "google.maps.reverse_geocode": settings.rate_limit_maps_geocode,
        "google.maps.geocode_batch": settings.rate_limit_maps_geocode,
        "google.maps.places_text_search": settings.rate_limit_maps_places,
        "google.maps.places_nearby_search": settings.rate_limit_maps_places,
        "google.maps.places_autocomplete": settings.rate_limit_maps_places,
        "google.maps.place_details": settings.rate_limit_maps_details,
        "google.maps.place_photo": settings.rate_limit_maps_details,
        "google.maps.compute_routes": settings.rate_limit_maps_routes,
        "google.maps.compute_route_matrix": settings.rate_limit_maps_routes,
        "google.maps.directions": settings.rate_limit_maps_routes,
        "google.maps.travel_time": settings.rate_limit_maps_routes,
        "google.maps.static_map": settings.rate_limit_maps_static,
        "google.maps.street_view_metadata": settings.rate_limit_maps_static,
        "google.maps.street_view_image": settings.rate_limit_maps_static,
    }
    parsed = overrides.get(tool_name)
    if parsed:
        return parsed
    if tool_name.startswith("google.gmail."):
        if any(
            token in tool_name
            for token in (
                ".send_",
                ".reply_",
                ".modify_",
                ".mark_",
                ".archive_",
                ".trash_",
                ".untrash_",
                ".create_",
                ".update_",
                ".delete_",
                ".batch_",
                ".forward_",
                ".patch_",
                ".import_",
            )
        ):
            return settings.rate_limit_gmail_write
        return settings.rate_limit_gmail_read
    if tool_name.startswith("google.maps.") and tool_name != "google.maps.maps_link":
        return settings.rate_limit_maps_default
    return spec_limit


def max_tool_calls_per_user_hour() -> int:
    return get_settings().max_tool_calls_per_user_hour


def admin_user_ids() -> frozenset[int]:
    return get_settings().admin_user_ids
