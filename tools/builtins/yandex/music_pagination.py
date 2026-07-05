from __future__ import annotations

import copy
from typing import Any

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100

PAGINATED_METHODS = frozenset({"users_likes_tracks"})


def pop_list_pagination(arguments: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    prepared = dict(arguments)
    offset = prepared.pop("offset", 0)
    limit = prepared.pop("limit", DEFAULT_PAGE_LIMIT)
    try:
        offset = int(offset)
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("offset and limit must be integers") from exc
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if limit < 1 or limit > MAX_PAGE_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_LIMIT}")
    return prepared, offset, limit


def slice_tracks_list_result(
    value: Any,
    *,
    offset: int,
    limit: int,
) -> tuple[Any, dict[str, Any]]:
    tracks = getattr(value, "tracks", None)
    if not isinstance(tracks, list):
        raise ValueError("Expected TracksList-like result with a tracks list")

    total = len(tracks)
    page = tracks[offset : offset + limit]
    sliced = copy.copy(value)
    sliced.tracks = page
    pagination = {
        "total_count": total,
        "offset": offset,
        "limit": limit,
        "returned_count": len(page),
        "has_more": offset + len(page) < total,
    }
    return sliced, pagination
