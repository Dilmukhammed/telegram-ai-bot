from __future__ import annotations

from typing import Any

from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser._common import SESSION_HANDLE_PROP, lease_page
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.schema import ToolSpec


async def _route_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.route_install(
            session,
            action=str(arguments["action"]),
            url=str(arguments["url"]) if arguments.get("url") else None,
            glob=str(arguments["glob"]) if arguments.get("glob") else None,
            regex=str(arguments["regex"]) if arguments.get("regex") else None,
            status=int(arguments.get("status") or 200),
            body=str(arguments["body"]) if arguments.get("body") is not None else None,
            content_type=str(arguments.get("content_type") or "text/plain"),
        )
    )


async def _unroute_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.route_remove(
            session,
            url=str(arguments["url"]) if arguments.get("url") else None,
            glob=str(arguments["glob"]) if arguments.get("glob") else None,
            regex=str(arguments["regex"]) if arguments.get("regex") else None,
            all_routes=bool(arguments.get("all", False)),
        )
    )


async def _clipboard_read_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.clipboard_read(session))


async def _clipboard_write_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.clipboard_write(session, str(arguments.get("text") or ""))
    )


async def _emulate_media_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.emulate_media(
            session,
            media=str(arguments["media"]) if arguments.get("media") is not None else None,
            color_scheme=(
                str(arguments["color_scheme"])
                if arguments.get("color_scheme") is not None
                else None
            ),
            reduced_motion=(
                str(arguments["reduced_motion"])
                if arguments.get("reduced_motion") is not None
                else None
            ),
        )
    )


async def _perf_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.perf_metrics(session))


BROWSER_ROUTE = ToolSpec(
    name="browser.route",
    description=(
        "Intercept matching requests: action=abort|fulfill only. "
        "Fulfill body capped; no continue/modify. Use before navigation that needs it."
    ),
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "action": {"type": "string", "enum": ["abort", "fulfill"]},
            "url": {"type": "string"},
            "glob": {"type": "string"},
            "regex": {"type": "string"},
            "status": {"type": "integer", "default": 200},
            "body": {"type": "string"},
            "content_type": {"type": "string", "default": "text/plain"},
        },
        "required": ["action"],
    },
    handler=_route_handler,
    tags=("browser", "web", "network", "write"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.route"),
    examples=("abort analytics requests", "fulfill mock api response"),
)

BROWSER_UNROUTE = ToolSpec(
    name="browser.unroute",
    description="Remove a route by url/glob/regex, or all=true to clear every route.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "url": {"type": "string"},
            "glob": {"type": "string"},
            "regex": {"type": "string"},
            "all": {"type": "boolean", "default": False},
        },
        "required": [],
    },
    handler=_unroute_handler,
    tags=("browser", "web", "network", "write"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.unroute"),
    examples=("remove browser route", "clear all routes"),
)

BROWSER_CLIPBOARD_READ = ToolSpec(
    name="browser.clipboard_read",
    description="Read text from the browser clipboard (permission granted when possible).",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP},
        "required": [],
    },
    handler=_clipboard_read_handler,
    tags=("browser", "web", "clipboard", "read"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.clipboard_read"),
    examples=("read browser clipboard",),
)

BROWSER_CLIPBOARD_WRITE = ToolSpec(
    name="browser.clipboard_write",
    description="Write text to the browser clipboard (size-capped).",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "text": {"type": "string"},
        },
        "required": ["text"],
    },
    handler=_clipboard_write_handler,
    tags=("browser", "web", "clipboard", "write"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.clipboard_write"),
    examples=("write browser clipboard", "copy text to clipboard"),
)

BROWSER_EMULATE_MEDIA = ToolSpec(
    name="browser.emulate_media",
    description="Emulate print/screen media, dark/light color scheme, reduced motion.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "media": {"type": "string", "enum": ["screen", "print"]},
            "color_scheme": {
                "type": "string",
                "enum": ["light", "dark", "no-preference", "null"],
            },
            "reduced_motion": {
                "type": "string",
                "enum": ["reduce", "no-preference", "null"],
            },
        },
        "required": [],
    },
    handler=_emulate_media_handler,
    tags=("browser", "web", "emulation"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.emulate_media"),
    examples=("emulate dark mode", "print media browser"),
)

BROWSER_PERF = ToolSpec(
    name="browser.perf",
    description="Return compact navigation performance timings for the active page.",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP},
        "required": [],
    },
    handler=_perf_handler,
    tags=("browser", "web", "diagnostics", "read"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.perf"),
    examples=("page performance timings", "browser nav metrics"),
)

BROWSER_ADVANCED_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_ROUTE,
    BROWSER_UNROUTE,
    BROWSER_CLIPBOARD_READ,
    BROWSER_CLIPBOARD_WRITE,
    BROWSER_EMULATE_MEDIA,
    BROWSER_PERF,
)
