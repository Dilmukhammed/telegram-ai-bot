from __future__ import annotations


def _like_action_bonus(query_tokens: set[str], tool_name: str, method: str) -> float:
    if not query_tokens & {"like", "liked", "likes", "favorite", "favorites"}:
        return 0.0
    if not query_tokens & {"track", "tracks", "song", "songs"}:
        return 0.0

    explicit_read = bool(query_tokens & {"liked", "likes", "favorite", "favorites", "library"})
    remove = bool(query_tokens & {"remove", "unlike"})
    add = bool(query_tokens & {"add", "like", "set", "put"}) and not explicit_read
    target = "users_likes_tracks_remove" if remove else "users_likes_tracks_add" if add else "users_likes_tracks"

    bonus = 0.0
    if method == target:
        bonus += 12.0
    elif method in {
        "users_likes_tracks",
        "users_likes_tracks_add",
        "users_likes_tracks_remove",
    }:
        bonus -= 5.0
    elif tool_name.startswith("yandex.music.") and "like" in method:
        bonus -= 8.0
    return bonus


def _playlist_action_bonus(query_tokens: set[str], tool_name: str, method: str) -> float:
    if not query_tokens & {"playlist", "playlists"}:
        return 0.0

    has_track = bool(query_tokens & {"track", "tracks", "song", "songs"})
    remove = bool(query_tokens & {"remove", "delete"})
    add = bool(query_tokens & {"add", "insert"})
    create = "create" in query_tokens and not has_track
    delete = "delete" in query_tokens and not has_track
    list_intent = bool(query_tokens & {"list", "show", "user"}) and not (
        add or remove or create or delete
    )

    target: str | None = None
    if has_track and remove:
        target = "users_playlists_delete_track"
    elif has_track and add:
        target = "users_playlists_insert_track"
    elif create:
        target = "users_playlists_create"
    elif delete:
        target = "users_playlists_delete"
    elif list_intent:
        target = "users_playlists_list"

    if target is None:
        return 0.0
    if method == target:
        return 12.0
    if method.startswith("users_playlists_") or method in {
        "playlist",
        "playlists",
        "playlists_list",
        "metatag_playlists",
    }:
        return -5.0
    return 0.0


def music_action_bonus(query_tokens: set[str], tool_name: str, method: str) -> float:
    return _like_action_bonus(query_tokens, tool_name, method) + _playlist_action_bonus(
        query_tokens,
        tool_name,
        method,
    )
