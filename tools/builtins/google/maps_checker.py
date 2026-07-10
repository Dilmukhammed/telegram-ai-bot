from __future__ import annotations

from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_USER_GOAL,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    EvidenceRef,
    VerificationQuestion,
)

_USER_GOAL = EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal")

_PRIOR_GEOCODE = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "google.maps.geocode",
        "google.maps.reverse_geocode",
        "google.maps.geocode_batch",
    ),
    optional=True,
    max_age_steps=10,
    label="prior_geocode",
)

_PRIOR_PLACES_SEARCH = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "google.maps.places_text_search",
        "google.maps.places_nearby_search",
        "google.maps.places_autocomplete",
        "google.maps.place_details",
    ),
    match=(("place_id", "$call.place_id"),),
    optional=True,
    max_age_steps=10,
    label="prior_places_search",
)

_PRIOR_MAPS_CONTEXT = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_name_pattern="google.maps.*",
    optional=True,
    max_age_steps=10,
    label="prior_maps_context",
)


def _call(label: str, *fields: str) -> EvidenceRef:
    return EvidenceRef(kind=EVIDENCE_CALL, fields=fields, label=label)


# --- Geocoding ---

GOOGLE_MAPS_GEOCODE_QUESTIONS = (
    VerificationQuestion(
        id="address_matches_intent",
        text="Does address match the place or location the user asked to locate?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("geocode_call", "address", "language", "region"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="region_bias_sensible",
        text="Is region/language bias appropriate for the user's locale or named place?",
        severity=SEVERITY_INFO,
        evidence=(_call("geocode_call", "language", "region"), _USER_GOAL),
    ),
)

GOOGLE_MAPS_REVERSE_GEOCODE_QUESTIONS = (
    VerificationQuestion(
        id="coordinates_correct",
        text="Do lat/lng match coordinates from prior geocode or the user's pin?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("reverse_call", "lat", "lng"), _USER_GOAL, _PRIOR_GEOCODE, _PRIOR_MAPS_CONTEXT),
    ),
)

GOOGLE_MAPS_GEOCODE_BATCH_QUESTIONS = (
    VerificationQuestion(
        id="addresses_match_intent",
        text="Does each address in addresses[] match a stop the user asked to geocode?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("geocode_batch_call", "addresses"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="batch_size_reasonable",
        text="Is the batch size (max 10) sufficient for all stops without missing one?",
        severity=SEVERITY_WARN,
        evidence=(_call("geocode_batch_call", "addresses"), _USER_GOAL),
    ),
)

# --- Places ---

GOOGLE_MAPS_PLACES_TEXT_SEARCH_QUESTIONS = (
    VerificationQuestion(
        id="text_query_matches",
        text="Does text_query match what the user asked to find (not the deprecated query param)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("text_search_call", "text_query", "included_type", "open_now"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="location_bias",
        text="If lat/lng/radius_m are set, do they center search on the user's area of interest?",
        severity=SEVERITY_WARN,
        evidence=(_call("text_search_call", "lat", "lng", "radius_m"), _USER_GOAL, _PRIOR_GEOCODE),
    ),
    VerificationQuestion(
        id="filters_match_intent",
        text="Do included_type, min_rating, and open_now filters match user constraints?",
        severity=SEVERITY_INFO,
        evidence=(_call("text_search_call", "included_type", "min_rating", "open_now"), _USER_GOAL),
    ),
)

GOOGLE_MAPS_PLACES_NEARBY_SEARCH_QUESTIONS = (
    VerificationQuestion(
        id="coordinates_or_geocode_first",
        text="Are lat/lng set for the area the user meant, or was geocode used when they named a landmark?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("nearby_call", "lat", "lng", "radius_m"), _USER_GOAL, _PRIOR_GEOCODE),
    ),
    VerificationQuestion(
        id="types_match_intent",
        text="Do included_types match the category the user asked for (restaurant, atm, etc.)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("nearby_call", "included_types", "open_now"), _USER_GOAL),
    ),
)

GOOGLE_MAPS_PLACE_DETAILS_QUESTIONS = (
    VerificationQuestion(
        id="place_id_correct",
        text="Is place_id from the place the user picked in prior text_search/nearby_search?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("place_details_call", "place_id", "detail_level"), _USER_GOAL, _PRIOR_PLACES_SEARCH, _PRIOR_MAPS_CONTEXT),
    ),
    VerificationQuestion(
        id="detail_level_sufficient",
        text="Does detail_level (basic/contact/full) provide fields the user asked for (hours, phone, reviews)?",
        severity=SEVERITY_WARN,
        evidence=(_call("place_details_call", "detail_level"), _USER_GOAL),
    ),
)

GOOGLE_MAPS_PLACE_PHOTO_QUESTIONS = (
    VerificationQuestion(
        id="place_id_correct",
        text="Is place_id the place whose photo the user asked to see?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("place_photo_call", "place_id", "photo_index"), _USER_GOAL, _PRIOR_PLACES_SEARCH),
    ),
)

GOOGLE_MAPS_PLACES_AUTOCOMPLETE_QUESTIONS = (
    VerificationQuestion(
        id="input_matches_partial",
        text="Does input reflect the partial address or place name the user is typing?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("autocomplete_call", "input", "lat", "lng"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="bias_for_disambiguation",
        text="If location bias is set, does it help disambiguate local place names?",
        severity=SEVERITY_INFO,
        evidence=(_call("autocomplete_call", "lat", "lng", "radius_m"), _USER_GOAL, _PRIOR_GEOCODE),
    ),
)

# --- Routes ---

GOOGLE_MAPS_COMPUTE_ROUTES_QUESTIONS = (
    VerificationQuestion(
        id="endpoints_match_intent",
        text="Do origin and destination match where the user asked to route from/to?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("compute_routes_call", "origin", "destination", "waypoints"), _USER_GOAL, _PRIOR_GEOCODE, _PRIOR_MAPS_CONTEXT),
    ),
    VerificationQuestion(
        id="travel_mode_matches",
        text="Does travel_mode (DRIVE/WALK/TRANSIT) match how the user wants to travel?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("compute_routes_call", "travel_mode", "departure_time", "avoid"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="tool_choice",
        text="Did the user need full steps/polyline here, or would travel_time/directions suffice?",
        severity=SEVERITY_INFO,
        evidence=(_call("compute_routes_call", "include_steps", "include_polyline"), _USER_GOAL),
    ),
)

GOOGLE_MAPS_COMPUTE_ROUTE_MATRIX_QUESTIONS = (
    VerificationQuestion(
        id="matrix_points_match",
        text="Do origins[] and destinations[] cover all points the user asked to compare?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("route_matrix_call", "origins", "destinations", "travel_mode"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="matrix_not_single_pair",
        text="Was a matrix (many-to-many) actually needed, not a single origin-destination pair?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
)

GOOGLE_MAPS_DIRECTIONS_QUESTIONS = (
    VerificationQuestion(
        id="endpoints_match_intent",
        text="Do origin and destination match the navigation the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("directions_call", "origin", "destination", "waypoints"), _USER_GOAL, _PRIOR_GEOCODE),
    ),
    VerificationQuestion(
        id="travel_mode_matches",
        text="Does travel_mode match drive/walk/transit intent?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("directions_call", "travel_mode", "departure_time"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="directions_not_eta_only",
        text="Did the user want turn-by-turn directions, not just ETA (travel_time)?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

GOOGLE_MAPS_TRAVEL_TIME_QUESTIONS = (
    VerificationQuestion(
        id="endpoints_match_intent",
        text="Do origin and destination match the trip the user asked how long/far?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("travel_time_call", "origin", "destination"), _USER_GOAL, _PRIOR_GEOCODE),
    ),
    VerificationQuestion(
        id="travel_mode_matches",
        text="Does travel_mode match how the user will travel?",
        severity=SEVERITY_WARN,
        evidence=(_call("travel_time_call", "travel_mode", "departure_time"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="eta_only_intent",
        text="Did the user only need ETA/distance without turn-by-turn steps?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
)

# --- Static / misc ---

GOOGLE_MAPS_STATIC_MAP_QUESTIONS = (
    VerificationQuestion(
        id="map_center_matches",
        text="Does center or lat/lng show the area or markers the user asked to visualize?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("static_map_call", "center", "lat", "lng", "markers", "zoom"), _USER_GOAL, _PRIOR_GEOCODE),
    ),
    VerificationQuestion(
        id="path_from_route",
        text="If path is set, is it the polyline from a prior route the user asked to draw?",
        severity=SEVERITY_INFO,
        evidence=(_call("static_map_call", "path"), _PRIOR_MAPS_CONTEXT),
    ),
)

GOOGLE_MAPS_STREET_VIEW_METADATA_QUESTIONS = (
    VerificationQuestion(
        id="coordinates_correct",
        text="Do lat/lng match the location the user asked about Street View availability?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("street_view_meta_call", "lat", "lng"), _USER_GOAL, _PRIOR_GEOCODE),
    ),
)

GOOGLE_MAPS_STREET_VIEW_IMAGE_QUESTIONS = (
    VerificationQuestion(
        id="coordinates_correct",
        text="Do lat/lng match where the user wants a panorama image?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("street_view_image_call", "lat", "lng", "heading"), _USER_GOAL, _PRIOR_GEOCODE),
    ),
    VerificationQuestion(
        id="metadata_checked",
        text="Was street_view_metadata checked first when availability was uncertain?",
        severity=SEVERITY_INFO,
        evidence=(_PRIOR_MAPS_CONTEXT, _USER_GOAL),
    ),
)

GOOGLE_MAPS_TIMEZONE_QUESTIONS = (
    VerificationQuestion(
        id="coordinates_correct",
        text="Do lat/lng match the place whose timezone the user asked for?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("timezone_call", "lat", "lng", "timestamp"), _USER_GOAL, _PRIOR_GEOCODE),
    ),
)

GOOGLE_MAPS_ELEVATION_QUESTIONS = (
    VerificationQuestion(
        id="points_match_intent",
        text="Do lat/lng or locations[] cover the point(s) the user asked elevation for?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("elevation_call", "lat", "lng", "locations"), _USER_GOAL, _PRIOR_GEOCODE),
    ),
)

GOOGLE_MAPS_MAPS_LINK_QUESTIONS = (
    VerificationQuestion(
        id="link_type_params",
        text="Does link_type match intent and are required params set (query / origin+destination / place_id)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("maps_link_call", "link_type", "query", "origin", "destination", "place_id"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="link_vs_api_route",
        text="Did the user only need a shareable URL, not live ETA or place data from API?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL, _PRIOR_MAPS_CONTEXT),
    ),
    VerificationQuestion(
        id="travel_mode_for_directions",
        text="For directions links, does travel_mode match intent (including BICYCLE when cycling)?",
        severity=SEVERITY_WARN,
        evidence=(_call("maps_link_call", "travel_mode"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="place_id_from_search",
        text="For place links, is place_id from the correct prior search result?",
        severity=SEVERITY_WARN,
        evidence=(_call("maps_link_call", "place_id", "query"), _USER_GOAL, _PRIOR_PLACES_SEARCH),
    ),
)

MAPS_CHECKER_QUESTIONS_BY_TOOL: dict[str, tuple[VerificationQuestion, ...]] = {
    "google.maps.geocode": GOOGLE_MAPS_GEOCODE_QUESTIONS,
    "google.maps.reverse_geocode": GOOGLE_MAPS_REVERSE_GEOCODE_QUESTIONS,
    "google.maps.geocode_batch": GOOGLE_MAPS_GEOCODE_BATCH_QUESTIONS,
    "google.maps.places_text_search": GOOGLE_MAPS_PLACES_TEXT_SEARCH_QUESTIONS,
    "google.maps.places_nearby_search": GOOGLE_MAPS_PLACES_NEARBY_SEARCH_QUESTIONS,
    "google.maps.place_details": GOOGLE_MAPS_PLACE_DETAILS_QUESTIONS,
    "google.maps.place_photo": GOOGLE_MAPS_PLACE_PHOTO_QUESTIONS,
    "google.maps.places_autocomplete": GOOGLE_MAPS_PLACES_AUTOCOMPLETE_QUESTIONS,
    "google.maps.compute_routes": GOOGLE_MAPS_COMPUTE_ROUTES_QUESTIONS,
    "google.maps.compute_route_matrix": GOOGLE_MAPS_COMPUTE_ROUTE_MATRIX_QUESTIONS,
    "google.maps.directions": GOOGLE_MAPS_DIRECTIONS_QUESTIONS,
    "google.maps.travel_time": GOOGLE_MAPS_TRAVEL_TIME_QUESTIONS,
    "google.maps.static_map": GOOGLE_MAPS_STATIC_MAP_QUESTIONS,
    "google.maps.street_view_metadata": GOOGLE_MAPS_STREET_VIEW_METADATA_QUESTIONS,
    "google.maps.street_view_image": GOOGLE_MAPS_STREET_VIEW_IMAGE_QUESTIONS,
    "google.maps.timezone": GOOGLE_MAPS_TIMEZONE_QUESTIONS,
    "google.maps.elevation": GOOGLE_MAPS_ELEVATION_QUESTIONS,
    "google.maps.maps_link": GOOGLE_MAPS_MAPS_LINK_QUESTIONS,
}

MAPS_CHECKER_ALL_TOOL_NAMES = tuple(MAPS_CHECKER_QUESTIONS_BY_TOOL.keys())

MAPS_CHECKER_READ_TOOL_NAMES = MAPS_CHECKER_ALL_TOOL_NAMES

MAPS_CHECKER_WRITE_TOOL_NAMES: tuple[str, ...] = ()
