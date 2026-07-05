"""Generate tools/builtins/yandex/music_tool_registry.py from ClientAsync introspection."""

from __future__ import annotations

import inspect
import re
import textwrap
from pathlib import Path

from yandex_music import ClientAsync

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tools" / "builtins" / "yandex" / "music_tool_registry.py"

EXCLUDE_METHODS = frozenset({"device_auth", "request_device_code", "poll_device_token"})

AUTH_METHODS = frozenset(
    {
        "music_history",
        "music_history_items",
        "queues_list",
        "queue",
        "queue_create",
        "queue_update_position",
        "feed",
        "feed_wizard_is_passed",
        "play_audio",
        "playlists_personal",
        "consume_promo_code",
        "account_settings",
        "account_settings_set",
        "permission_alerts",
        "account_experiments",
        "account_experiments_details",
        "rotor_account_status",
        "rotor_stations_dashboard",
        "rotor_station_settings2",
        "rotor_station_feedback",
        "rotor_station_feedback_radio_started",
        "rotor_station_feedback_track_started",
        "rotor_station_feedback_track_finished",
        "rotor_station_feedback_skip",
    }
)

WRITE_SUFFIXES = (
    "_add",
    "_remove",
    "_delete",
    "_create",
    "_set",
    "_insert",
    "_insert_track",
    "_delete_track",
    "_change",
    "_join",
    "_update",
)
WRITE_CONTAINS = (
    "consume_",
    "play_audio",
    "feedback",
    "device_auth",
)
WRITE_PREFIXES = ("pin_", "unpin_")


def requires_auth(method: str) -> bool:
    if method.startswith("users_"):
        return True
    if "likes" in method or "dislikes" in method:
        return True
    if method.startswith("queue") or method.startswith("queues_"):
        return True
    if method.startswith("pin") or method.startswith("unpin"):
        return True
    if method.startswith("users_presaves"):
        return True
    return method in AUTH_METHODS


def is_write(method: str) -> bool:
    if any(method.startswith(prefix) for prefix in WRITE_PREFIXES):
        return True
    if any(fragment in method for fragment in WRITE_CONTAINS):
        return True
    return any(method.endswith(suffix) for suffix in WRITE_SUFFIXES)


def format_description(method: str, doc: str) -> str:
    label = method.replace("_", " ")
    return f"Yandex Music API `{method}` ({label}). {doc}"


def param_type(name: str, default) -> dict:
    if default is not inspect.Parameter.empty:
        if isinstance(default, bool):
            return {"type": "boolean", "default": default}
        if isinstance(default, int):
            return {"type": "integer", "default": default}
        if isinstance(default, float):
            return {"type": "number", "default": default}
        if isinstance(default, str):
            return {"type": "string", "default": default}
    if name in {"page", "limit", "zoom", "width", "height", "timestamp"}:
        return {"type": "integer"}
    if name.endswith("_id") or name.endswith("_ids") or name in {"text", "part", "query", "type_", "types"}:
        return {"type": "string"}
    if name in {"track_ids", "album_ids", "artist_ids", "playlist_ids", "items", "data", "ids"}:
        return {"type": "array", "items": {}}
    return {"description": f"Parameter `{name}` (passed to Yandex Music API)."}


def build_schema(method: str, sig: inspect.Signature) -> dict:
    properties: dict = {}
    required: list[str] = []
    for name, param in list(sig.parameters.items())[1:]:  # skip self
        if name in {"args", "kwargs"}:
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        prop = param_type(name, param.default)
        if name == "from_":
            properties["from"] = {**prop, "description": "Alias for API parameter `from`."}
            continue
        properties[name] = prop
        if param.default is inspect.Parameter.empty and param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
            required.append(name)
    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    schema["additionalProperties"] = True
    return schema


def main() -> None:
    entries: list[dict] = []
    for name, fn in sorted(inspect.getmembers(ClientAsync, predicate=inspect.isfunction)):
        if name.startswith("_") or re.search(r"[A-Z]", name):
            continue
        if name in EXCLUDE_METHODS:
            continue
        doc = (inspect.getdoc(fn) or name.replace("_", " ")).split("\n")[0].strip()
        entries.append(
            {
                "method": name,
                "auth": requires_auth(name),
                "write": is_write(name),
                "description": format_description(name, doc)[:320],
                "schema": build_schema(name, inspect.signature(fn)),
            }
        )

    lines = [
        '"""Auto-generated Yandex Music tool registry — do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "MUSIC_TOOL_REGISTRY: tuple[dict[str, Any], ...] = (",
    ]
    for entry in entries:
        lines.append("    {")
        lines.append(f'        "method": "{entry["method"]}",')
        lines.append(f'        "auth": {entry["auth"]!r},')
        lines.append(f'        "write": {entry["write"]!r},')
        lines.append(f'        "description": {entry["description"]!r},')
        lines.append(f"        \"schema\": {entry['schema']!r},")
        lines.append("    },")
    lines.append(")")
    lines.append("")
    lines.append(f"MUSIC_TOOL_COUNT = {len(entries)}")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(entries)} tools to {OUT}")


if __name__ == "__main__":
    main()
