from __future__ import annotations

from typing import Any

_MAX_STRING = 2000
_MAX_LIST = 50
_MAX_DEPTH = 6


def _truncate(value: str, limit: int = _MAX_STRING) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _list_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            return items
    return []


def _looks_like_track_dict(data: dict[str, Any]) -> bool:
    if "timestamp" in data and "track" in data:
        return False
    if ("id" not in data and "track_id" not in data) or "title" not in data:
        return False
    return any(
        key in data
        for key in ("artists", "albums", "duration_ms", "cover_uri", "track_id", "lyrics_available")
    )


def _looks_like_playlist_track_entry(data: dict[str, Any]) -> bool:
    track = data.get("track")
    if not isinstance(track, dict) or "track" not in data:
        return False
    return "original_index" in data or "album_id" in data


def _looks_like_playlist_dict(data: dict[str, Any]) -> bool:
    if "title" not in data or "track_count" not in data:
        return False
    return any(key in data for key in ("uid", "kind", "playlist_uuid", "playlistUuid"))


def _compact_tracks_field(tracks: Any, *, max_list: int = _MAX_LIST) -> dict[str, Any] | None:
    if isinstance(tracks, dict) and isinstance(tracks.get("items"), list):
        items = tracks["items"]
        compact_items = [
            compact_playlist_track_entry(item)
            if isinstance(item, dict) and _looks_like_playlist_track_entry(item)
            else serialize_value(item, depth=1, max_list=max_list)
            for item in items[:max_list]
        ]
        result: dict[str, Any] = {"count": tracks.get("count", len(items)), "items": compact_items}
        if tracks.get("truncated") or len(items) > max_list:
            result["truncated"] = True
        return result
    if isinstance(tracks, list):
        compact_items = [
            compact_playlist_track_entry(item)
            if isinstance(item, dict) and _looks_like_playlist_track_entry(item)
            else serialize_value(item, depth=1, max_list=max_list)
            for item in tracks[:max_list]
        ]
        result = {"count": len(tracks), "items": compact_items}
        if len(tracks) > max_list:
            result["truncated"] = True
        return result
    return None


def compact_playlist_track_entry(data: dict[str, Any]) -> dict[str, Any]:
    track = data.get("track")
    compact = (
        compact_track_dict(track)
        if isinstance(track, dict) and _looks_like_track_dict(track)
        else serialize_value(track, depth=1)
    )
    entry: dict[str, Any] = {"track": compact}
    if data.get("original_index") is not None:
        entry["original_index"] = data["original_index"]
    return entry


def compact_playlist_dict(data: dict[str, Any]) -> dict[str, Any]:
    owner = data.get("owner")
    owner_name = owner.get("name") or owner.get("display_name") if isinstance(owner, dict) else None
    tracks = _compact_tracks_field(data.get("tracks"))
    return {
        key: value
        for key, value in {
            "uid": data.get("uid"),
            "kind": data.get("kind"),
            "playlist_uuid": data.get("playlist_uuid") or data.get("playlistUuid"),
            "title": data.get("title"),
            "track_count": data.get("track_count"),
            "owner": owner_name,
            "visibility": data.get("visibility"),
            "url_part": data.get("url_part"),
            "modified": data.get("modified"),
            "tracks": tracks,
        }.items()
        if value is not None
    }


def compact_track_dict(data: dict[str, Any]) -> dict[str, Any]:
    artists = _list_items(data.get("artists"))
    artist_names = [
        (artist.get("name") if isinstance(artist, dict) else None)
        for artist in artists[:5]
    ]
    albums = _list_items(data.get("albums"))
    album = albums[0] if albums and isinstance(albums[0], dict) else {}
    track_id = data.get("id") or data.get("track_id")
    album_id = album.get("id") or data.get("album_id")
    url = None
    if track_id and album_id:
        url = f"https://music.yandex.ru/album/{album_id}/track/{track_id}"
    return {
        key: value
        for key, value in {
            "track_id": track_id,
            "album_id": album_id,
            "title": data.get("title"),
            "artists": [name for name in artist_names if name],
            "duration_ms": data.get("duration_ms"),
            "available": data.get("available"),
            "lyrics_available": data.get("lyrics_available"),
            "content_warning": data.get("content_warning"),
            "cover_uri": data.get("cover_uri") or data.get("og_image"),
            "url": url,
        }.items()
        if value is not None
    }


def serialize_value(value: Any, *, depth: int = 0, max_list: int = _MAX_LIST) -> Any:
    if depth >= _MAX_DEPTH:
        return str(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate(value)
    if hasattr(value, "to_dict"):
        raw = value.to_dict()
        if isinstance(raw, dict) and _looks_like_track_dict(raw):
            return compact_track_dict(raw)
        return serialize_value(raw, depth=depth + 1, max_list=max_list)
    if isinstance(value, dict):
        if _looks_like_playlist_track_entry(value):
            return compact_playlist_track_entry(value)
        if _looks_like_playlist_dict(value):
            return compact_playlist_dict(value)
        if _looks_like_track_dict(value):
            return compact_track_dict(value)
        return {
            str(key): serialize_value(item, depth=depth + 1, max_list=max_list)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        items = [serialize_value(item, depth=depth + 1, max_list=max_list) for item in value[:max_list]]
        result: dict[str, Any] = {"count": len(value), "items": items}
        if len(value) > max_list:
            result["truncated"] = True
        return result
    return _truncate(str(value))


def build_method_response(
    value: Any,
    *,
    method: str,
    pagination: dict[str, Any] | None = None,
    max_list: int | None = None,
) -> dict[str, Any]:
    list_cap = max_list if max_list is not None else _MAX_LIST
    serialized = serialize_value(value, max_list=list_cap)
    if isinstance(serialized, dict) and "count" in serialized and "items" in serialized:
        response: dict[str, Any] = {"method": method, **serialized}
    else:
        response = {"method": method, "result": serialized}
    if pagination:
        response.update(pagination)
    return response
