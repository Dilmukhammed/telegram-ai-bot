from __future__ import annotations

import re
from typing import Any

from yandex_music import ClientAsync

from config import get_settings
from tools.builtins.yandex.errors import YandexNotConnectedError
from tools.builtins.yandex.music_serialize import compact_track_dict
from tools.builtins.yandex.token_store import get_token_store
from tools.filename_utils import ensure_filename_extension
from tools.run_files import require_run_file_store

_anonymous_client: ClientAsync | None = None


async def get_anonymous_client() -> ClientAsync:
    global _anonymous_client
    if _anonymous_client is None:
        settings = get_settings()
        _anonymous_client = ClientAsync(language=settings.yandex_music_language)
        await _anonymous_client.init()
    return _anonymous_client


async def get_music_client(*, telegram_user_id: int | None, require_auth: bool) -> ClientAsync:
    if telegram_user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")

    stored = get_token_store().get(telegram_user_id)
    if stored is None:
        if require_auth:
            raise YandexNotConnectedError(
                "Yandex Music is not connected. Run /connect_yandex in Telegram."
            )
        return await get_anonymous_client()

    settings = get_settings()
    client = ClientAsync(stored.access_token, language=settings.yandex_music_language)
    await client.init()
    return client


REVISION_AWARE_METHODS: frozenset[str] = frozenset(
    {"users_playlists_insert_track", "users_playlists_delete_track", "users_playlists_change"}
)


async def _fetch_current_revision(client: ClientAsync, kind: str | int) -> int:
    playlist = await client.users_playlists(kind=kind)
    if playlist is None:
        raise ValueError(f"Playlist not found: kind={kind}")
    revision = getattr(playlist, "revision", None)
    if not isinstance(revision, int) or revision < 1:
        revision = 1
    return revision


async def call_music_method(client: ClientAsync, method: str, arguments: dict[str, Any]) -> Any:
    if method in REVISION_AWARE_METHODS:
        kind = arguments.get("kind")
        revision = arguments.get("revision")
        if kind is not None and (revision is None or revision <= 1):
            arguments = dict(arguments)
            arguments["revision"] = await _fetch_current_revision(client, kind)
    fn = getattr(client, method, None)
    if fn is None or not callable(fn):
        raise ValueError(f"Unknown Yandex Music API method: {method}")
    return await fn(**arguments)


def _safe_filename(title: str | None, track_id: str) -> str:
    base = title or f"track_{track_id.split(':')[0]}"
    cleaned = re.sub(r"[^\w\s\-().]+", "", base, flags=re.UNICODE).strip() or "track"
    return ensure_filename_extension(f"{cleaned[:80]}.mp3", "audio/mpeg")


def _download_track_id(track: Any, track_id: str) -> str:
    """Yandex API expects trackId:albumId for download info when album is known."""
    if ":" in track_id:
        return track_id
    album_id = track.albums[0].id if getattr(track, "albums", None) else None
    if album_id is not None and track.id is not None:
        return f"{track.id}:{album_id}"
    return track_id


def _pick_download_info(download_infos: list[Any], codec: str) -> Any:
    preferred = None
    for info in download_infos:
        info_codec = (info.codec or "").lower()
        if info_codec == codec:
            preferred = info
            break
    return preferred or download_infos[0]


async def download_track_to_file_ref(
    *,
    telegram_user_id: int,
    track_id: str,
    codec: str = "mp3",
    filename: str | None = None,
    require_auth: bool = True,
) -> dict[str, Any]:
    client = await get_music_client(telegram_user_id=telegram_user_id, require_auth=require_auth)
    tracks = await client.tracks(track_id)
    if not tracks:
        raise ValueError(f"Track not found: {track_id}")
    track = tracks[0]

    download_infos = await track.get_download_info_async(get_direct_links=True)
    if not download_infos:
        download_infos = await client.tracks_download_info(
            _download_track_id(track, track_id),
            get_direct_links=True,
        )
    if not download_infos:
        raise ValueError("No download info available for this track")

    preferred = _pick_download_info(download_infos, codec.lower())
    bitrate = getattr(preferred, "bitrate_in_kbps", None) or 192
    data = await track.download_bytes_async(preferred.codec, bitrate)
    store = require_run_file_store()
    out_name = filename or _safe_filename(track.title, track_id)
    meta = store.save(data, filename=out_name, mime_type="audio/mpeg")

    album_id = track.albums[0].id if track.albums else None
    url = None
    if track.id and album_id:
        url = f"https://music.yandex.ru/album/{album_id}/track/{track.id}"

    return {
        **meta,
        "track_id": track_id,
        "title": track.title,
        "codec": preferred.codec,
        "url": url,
        "track": compact_track_dict(track.to_dict()),
    }
