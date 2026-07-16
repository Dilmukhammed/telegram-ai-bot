from __future__ import annotations

from typing import Any

from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser._common import SESSION_HANDLE_PROP, lease_page
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.schema import ToolSpec


async def _storage_get_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    key = arguments.get("key")
    return redact_browser_payload(
        await pw.storage_get(
            session,
            area=str(arguments.get("area") or "local"),
            key=str(key) if key is not None else None,
        )
    )


async def _storage_set_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.storage_set(
            session,
            area=str(arguments.get("area") or "local"),
            key=str(arguments["key"]),
            value=str(arguments.get("value") if arguments.get("value") is not None else ""),
        )
    )


async def _set_viewport_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.set_viewport(
            session,
            width=int(arguments["width"]),
            height=int(arguments["height"]),
        )
    )


async def _set_geolocation_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    accuracy = arguments.get("accuracy")
    return redact_browser_payload(
        await pw.set_geolocation(
            session,
            latitude=float(arguments["latitude"]),
            longitude=float(arguments["longitude"]),
            accuracy=float(accuracy) if accuracy is not None else None,
        )
    )


async def _set_locale_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.set_locale(session, str(arguments["locale"])))


async def _set_timezone_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.set_timezone(session, str(arguments["timezone_id"]))
    )


async def _grant_permissions_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    perms = arguments.get("permissions") or []
    origin = arguments.get("origin")
    return redact_browser_payload(
        await pw.grant_permissions(
            session,
            [str(p) for p in perms],
            origin=str(origin) if origin else None,
        )
    )


async def _clear_permissions_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.clear_permissions(session))


BROWSER_STORAGE_GET = ToolSpec(
    name="browser.storage.get",
    description="Read localStorage/sessionStorage key, or all keys (size-capped).",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "area": {"type": "string", "enum": ["local", "session"], "default": "local"},
            "key": {"type": "string", "description": "Omit to list all keys."},
        },
        "required": [],
    },
    handler=_storage_get_handler,
    tags=("browser", "web", "storage", "read"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.storage.get"),
    examples=("get localStorage", "read sessionStorage key"),
)

BROWSER_STORAGE_SET = ToolSpec(
    name="browser.storage.set",
    description="Set a localStorage/sessionStorage key.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "area": {"type": "string", "enum": ["local", "session"], "default": "local"},
            "key": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["key"],
    },
    handler=_storage_set_handler,
    tags=("browser", "web", "storage", "write"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.storage.set"),
    examples=("set localStorage key",),
)

BROWSER_SET_VIEWPORT = ToolSpec(
    name="browser.set_viewport",
    description="Set the active page viewport size.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "width": {"type": "integer"},
            "height": {"type": "integer"},
        },
        "required": ["width", "height"],
    },
    handler=_set_viewport_handler,
    tags=("browser", "web", "emulation"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.set_viewport"),
    examples=("set browser viewport", "resize browser window"),
)

BROWSER_SET_GEOLOCATION = ToolSpec(
    name="browser.set_geolocation",
    description="Override geolocation (grants geolocation permission).",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
            "accuracy": {"type": "number"},
        },
        "required": ["latitude", "longitude"],
    },
    handler=_set_geolocation_handler,
    tags=("browser", "web", "emulation"),
    cache_ttl_seconds=None,
    rate_limit=(20, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.set_geolocation"),
    examples=("set browser geolocation", "fake gps location"),
)

BROWSER_SET_LOCALE = ToolSpec(
    name="browser.set_locale",
    description="Override browser locale (e.g. ru-RU, en-US) via emulation.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "locale": {"type": "string"},
        },
        "required": ["locale"],
    },
    handler=_set_locale_handler,
    tags=("browser", "web", "emulation"),
    cache_ttl_seconds=None,
    rate_limit=(20, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.set_locale"),
    examples=("set browser locale",),
)

BROWSER_SET_TIMEZONE = ToolSpec(
    name="browser.set_timezone",
    description="Override browser timezone (IANA id, e.g. Europe/Moscow).",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "timezone_id": {"type": "string"},
        },
        "required": ["timezone_id"],
    },
    handler=_set_timezone_handler,
    tags=("browser", "web", "emulation"),
    cache_ttl_seconds=None,
    rate_limit=(20, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.set_timezone"),
    examples=("set browser timezone",),
)

BROWSER_GRANT_PERMISSIONS = ToolSpec(
    name="browser.grant_permissions",
    description=(
        "Grant browser permissions (e.g. geolocation, notifications, clipboard-read)."
    ),
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "permissions": {
                "type": "array",
                "items": {"type": "string"},
            },
            "origin": {"type": "string"},
        },
        "required": ["permissions"],
    },
    handler=_grant_permissions_handler,
    tags=("browser", "web", "emulation"),
    cache_ttl_seconds=None,
    rate_limit=(20, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.grant_permissions"),
    examples=("grant geolocation permission",),
)

BROWSER_CLEAR_PERMISSIONS = ToolSpec(
    name="browser.clear_permissions",
    description="Clear all granted browser permissions for the context.",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP},
        "required": [],
    },
    handler=_clear_permissions_handler,
    tags=("browser", "web", "emulation"),
    cache_ttl_seconds=None,
    rate_limit=(20, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.clear_permissions"),
    examples=("clear browser permissions",),
)

BROWSER_STATE_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_STORAGE_GET,
    BROWSER_STORAGE_SET,
    BROWSER_SET_VIEWPORT,
    BROWSER_SET_GEOLOCATION,
    BROWSER_SET_LOCALE,
    BROWSER_SET_TIMEZONE,
    BROWSER_GRANT_PERMISSIONS,
    BROWSER_CLEAR_PERMISSIONS,
)
