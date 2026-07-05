from __future__ import annotations

from typing import Any

from tools.builtins.yandex.auth import (
    auth_status_payload,
    poll_device_connect_once,
    revoke_and_delete,
    start_device_connect,
)
from tools.builtins.yandex.music_client import call_music_method, download_track_to_file_ref, get_music_client
from tools.builtins.yandex.music_serialize import build_method_response
from tools.builtins.yandex.music_tool_registry import MUSIC_TOOL_REGISTRY
from tools.builtins.yandex.tool_hints import YANDEX_MUSIC_OAUTH_HINT
from tools.context import get_run_context
from tools.schema import ToolSpec


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


def _tool_name(method: str) -> str:
    return f"yandex.music.{method}"


def _prepare_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(arguments)
    if "from" in prepared and "from_" not in prepared:
        prepared["from_"] = prepared.pop("from")
    return prepared


def _make_handler(method: str, *, auth: bool) -> Any:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        user_id = _require_user_id()
        client = await get_music_client(telegram_user_id=user_id, require_auth=auth)
        result = await call_music_method(client, method, _prepare_arguments(arguments))
        return build_method_response(result, method=method)

    return handler


async def _track_download_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    track_id = str(arguments.get("track_id", "")).strip()
    if not track_id:
        raise ValueError("track_id is required")
    codec = str(arguments.get("codec", "mp3")).lower()
    filename = arguments.get("filename")
    return await download_track_to_file_ref(
        telegram_user_id=user_id,
        track_id=track_id,
        codec=codec,
        filename=str(filename).strip() if filename else None,
        require_auth=bool(arguments.get("require_auth", True)),
    )


async def _auth_status_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    return auth_status_payload(_require_user_id())


async def _auth_connect_start_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    return await start_device_connect(_require_user_id())


async def _auth_poll_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    stored = await poll_device_connect_once(_require_user_id())
    if stored is None:
        pending = auth_status_payload(_require_user_id())
        return {"ok": False, "connected": False, "pending": pending.get("device_auth_pending", False)}
    return {
        "ok": True,
        "connected": True,
        "login": stored.login,
        "uid": stored.uid,
    }


async def _auth_disconnect_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    deleted = await revoke_and_delete(_require_user_id())
    return {"ok": True, "disconnected": deleted}


def _examples(method: str) -> tuple[str, ...]:
    label = method.replace("_", " ")
    return (f"yandex music {label}", f"ym {label}", method)


def _build_music_tools() -> tuple[ToolSpec, ...]:
    tools: list[ToolSpec] = []
    for entry in MUSIC_TOOL_REGISTRY:
        method = str(entry["method"])
        auth = bool(entry["auth"])
        write = bool(entry["write"])
        description = str(entry["description"])
        if auth:
            description += YANDEX_MUSIC_OAUTH_HINT
        tags = ("yandex", "music", "write" if write else "read")
        cache = None if write else 300 if method in {"search", "search_suggest"} else 120
        rate = (30, 60) if write else (60, 60)
        tools.append(
            ToolSpec(
                name=_tool_name(method),
                description=description,
                parameters=entry["schema"],
                handler=_make_handler(method, auth=auth),
                tags=tags,
                cache_ttl_seconds=cache,
                rate_limit=rate,
                parallel_safe=not write,
                examples=_examples(method),
            )
        )
    return tuple(tools)


YANDEX_AUTH_STATUS = ToolSpec(
    name="yandex.auth.status",
    description="Check Yandex Music connection for the current Telegram user.",
    parameters={"type": "object", "properties": {}},
    handler=_auth_status_handler,
    tags=("yandex", "auth"),
    cache_ttl_seconds=10,
    parallel_safe=True,
    examples=("yandex music connected", "yandex auth status"),
)

YANDEX_AUTH_CONNECT_START = ToolSpec(
    name="yandex.auth.connect_start",
    description=(
        "Start Yandex Music device OAuth — returns verification_url and user_code. "
        "Alternative: /connect_yandex in Telegram (auto-polls)."
    ),
    parameters={"type": "object", "properties": {}},
    handler=_auth_connect_start_handler,
    tags=("yandex", "auth"),
    parallel_safe=False,
    examples=("connect yandex music", "yandex oauth"),
)

YANDEX_AUTH_POLL = ToolSpec(
    name="yandex.auth.poll_device",
    description="Poll once for Yandex device OAuth completion after connect_start.",
    parameters={"type": "object", "properties": {}},
    handler=_auth_poll_handler,
    tags=("yandex", "auth"),
    parallel_safe=True,
    examples=("check yandex oauth",),
)

YANDEX_AUTH_DISCONNECT = ToolSpec(
    name="yandex.auth.disconnect",
    description="Disconnect Yandex Music for the current Telegram user. Alternative: /disconnect_yandex.",
    parameters={"type": "object", "properties": {}},
    handler=_auth_disconnect_handler,
    tags=("yandex", "auth"),
    parallel_safe=True,
    examples=("disconnect yandex music",),
)

YANDEX_MUSIC_TRACK_DOWNLOAD = ToolSpec(
    name="yandex.music.track_download",
    description=(
        "Download a track to a run file_ref for telegram.send_file (audio/mpeg). "
        "track_id format: trackId or trackId:albumId."
        + YANDEX_MUSIC_OAUTH_HINT
    ),
    parameters={
        "type": "object",
        "properties": {
            "track_id": {"type": "string", "description": "Yandex track id or trackId:albumId."},
            "codec": {
                "type": "string",
                "enum": ["mp3", "aac"],
                "default": "mp3",
                "description": "Preferred download codec.",
            },
            "filename": {"type": "string", "description": "Optional output filename."},
            "require_auth": {
                "type": "boolean",
                "default": True,
                "description": "Require connected account (needed for full track).",
            },
        },
        "required": ["track_id"],
    },
    handler=_track_download_handler,
    tags=("yandex", "music", "write"),
    parallel_safe=False,
    examples=("download track mp3", "send yandex music file"),
)

YANDEX_AUTH_TOOLS: tuple[ToolSpec, ...] = (
    YANDEX_AUTH_STATUS,
    YANDEX_AUTH_CONNECT_START,
    YANDEX_AUTH_POLL,
    YANDEX_AUTH_DISCONNECT,
)

YANDEX_MUSIC_TOOLS: tuple[ToolSpec, ...] = _build_music_tools() + (YANDEX_MUSIC_TRACK_DOWNLOAD,)

YANDEX_TOOLS: tuple[ToolSpec, ...] = YANDEX_AUTH_TOOLS + YANDEX_MUSIC_TOOLS
