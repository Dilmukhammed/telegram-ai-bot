from __future__ import annotations

from typing import Any

from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.session_manager import require_browser_session_manager
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.schema import ToolSpec


async def _lease_page(arguments: dict[str, Any]):
    manager = require_browser_session_manager()
    handle = arguments.get("session_handle")
    return await manager.get_playwright(str(handle) if handle else None)


async def _navigate_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await _lease_page(arguments)
    result = await pw.navigate(
        session,
        arguments["url"],
        wait_until=str(arguments.get("wait_until") or "domcontentloaded"),
    )
    return redact_browser_payload(result)


async def _snapshot_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await _lease_page(arguments)
    result = await pw.snapshot(
        session,
        interactive=bool(arguments.get("interactive", True)),
        max_chars=int(arguments.get("max_chars") or 12_000),
    )
    return redact_browser_payload(result)


async def _click_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await _lease_page(arguments)
    result = await pw.click(
        session,
        arguments["ref"],
        button=str(arguments.get("button") or "left"),
        double=bool(arguments.get("double", False)),
    )
    return redact_browser_payload(result)


async def _type_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await _lease_page(arguments)
    result = await pw.type_text(
        session,
        arguments["ref"],
        str(arguments["text"]),
        clear=bool(arguments.get("clear", False)),
    )
    return redact_browser_payload(result)


async def _fill_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await _lease_page(arguments)
    result = await pw.fill(session, arguments["ref"], str(arguments["value"]))
    return redact_browser_payload(result)


async def _press_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await _lease_page(arguments)
    result = await pw.press(session, str(arguments["key"]))
    return redact_browser_payload(result)


async def _scroll_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await _lease_page(arguments)
    result = await pw.scroll(
        session,
        direction=str(arguments.get("direction") or "down"),
        amount=int(arguments.get("amount") or 800),
    )
    return redact_browser_payload(result)


async def _wait_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await _lease_page(arguments)
    result = await pw.wait_for(
        session,
        for_=str(arguments["for"]),
        value=arguments.get("value"),
        timeout_ms=int(arguments.get("timeout_ms") or 30_000),
    )
    return redact_browser_payload(result)


_SESSION_HANDLE_PROP = {
    "session_handle": {
        "type": "string",
        "description": "Optional handle from browser.session_open.",
    }
}

BROWSER_NAVIGATE = ToolSpec(
    name="browser.navigate",
    description="Navigate the active browser session to a URL.",
    parameters={
        "type": "object",
        "properties": {
            **_SESSION_HANDLE_PROP,
            "url": {"type": "string", "description": "Absolute http(s) URL."},
            "wait_until": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle"],
                "default": "domcontentloaded",
            },
        },
        "required": ["url"],
    },
    handler=_navigate_handler,
    tags=("browser", "web", "navigation", "read"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.navigate"),
    examples=("open url in browser", "navigate to website", "go to page"),
)

BROWSER_SNAPSHOT = ToolSpec(
    name="browser.snapshot",
    description=(
        "Capture an accessibility/DOM snapshot with stable refs for click/type/fill. "
        "Call again after navigation or major page changes."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_SESSION_HANDLE_PROP,
            "interactive": {"type": "boolean", "default": True},
            "max_chars": {"type": "integer", "default": 12000},
        },
        "required": [],
    },
    handler=_snapshot_handler,
    tags=("browser", "web", "read", "snapshot"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.snapshot"),
    examples=("browser snapshot", "list clickable elements", "page accessibility tree"),
)

BROWSER_CLICK = ToolSpec(
    name="browser.click",
    description="Click an element by ref from browser.snapshot.",
    parameters={
        "type": "object",
        "properties": {
            **_SESSION_HANDLE_PROP,
            "ref": {"type": "string"},
            "button": {"type": "string", "enum": ["left", "right"], "default": "left"},
            "double": {"type": "boolean", "default": False},
        },
        "required": ["ref"],
    },
    handler=_click_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.click"),
    examples=("click button in browser", "click link ref"),
)

BROWSER_TYPE = ToolSpec(
    name="browser.type",
    description="Type text into an element by ref (optional clear first).",
    parameters={
        "type": "object",
        "properties": {
            **_SESSION_HANDLE_PROP,
            "ref": {"type": "string"},
            "text": {"type": "string"},
            "clear": {"type": "boolean", "default": False},
        },
        "required": ["ref", "text"],
    },
    handler=_type_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.type"),
    examples=("type into form field", "enter text in browser"),
)

BROWSER_FILL = ToolSpec(
    name="browser.fill",
    description="Fill an input by ref (replaces existing value).",
    parameters={
        "type": "object",
        "properties": {
            **_SESSION_HANDLE_PROP,
            "ref": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["ref", "value"],
    },
    handler=_fill_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.fill"),
    examples=("fill input browser", "set form value"),
)

BROWSER_PRESS = ToolSpec(
    name="browser.press",
    description="Press a keyboard key in the active browser page (e.g. Enter, Escape).",
    parameters={
        "type": "object",
        "properties": {
            **_SESSION_HANDLE_PROP,
            "key": {"type": "string"},
        },
        "required": ["key"],
    },
    handler=_press_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.press"),
    examples=("press enter in browser", "keyboard key browser"),
)

BROWSER_SCROLL = ToolSpec(
    name="browser.scroll",
    description="Scroll the page up or down.",
    parameters={
        "type": "object",
        "properties": {
            **_SESSION_HANDLE_PROP,
            "direction": {"type": "string", "enum": ["down", "up"], "default": "down"},
            "amount": {"type": "integer", "default": 800},
        },
        "required": [],
    },
    handler=_scroll_handler,
    tags=("browser", "web", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.scroll"),
    examples=("scroll page down", "scroll browser"),
)

BROWSER_WAIT = ToolSpec(
    name="browser.wait",
    description="Wait for a selector, text, or a timeout (ms capped).",
    parameters={
        "type": "object",
        "properties": {
            **_SESSION_HANDLE_PROP,
            "for": {
                "type": "string",
                "enum": ["selector", "text", "timeout"],
            },
            "value": {"type": "string"},
            "timeout_ms": {"type": "integer", "default": 30000},
        },
        "required": ["for"],
    },
    handler=_wait_handler,
    tags=("browser", "web", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.wait"),
    examples=("wait for text on page", "wait for selector"),
)

BROWSER_PAGE_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_NAVIGATE,
    BROWSER_SNAPSHOT,
    BROWSER_CLICK,
    BROWSER_TYPE,
    BROWSER_FILL,
    BROWSER_PRESS,
    BROWSER_SCROLL,
    BROWSER_WAIT,
)
