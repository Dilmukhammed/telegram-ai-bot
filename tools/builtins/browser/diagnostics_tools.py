from __future__ import annotations

from typing import Any

from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser._common import SESSION_HANDLE_PROP, lease_page
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.schema import ToolSpec


async def _network_last_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.network_last(session, limit=int(arguments.get("limit") or 20))
    )


async def _network_wait_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.network_wait(
            session,
            url=str(arguments["url"]) if arguments.get("url") else None,
            glob=str(arguments["glob"]) if arguments.get("glob") else None,
            regex=str(arguments["regex"]) if arguments.get("regex") else None,
            timeout_ms=int(arguments.get("timeout_ms") or 30_000),
        )
    )


async def _console_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.console_messages(
            session,
            limit=int(arguments.get("limit") or 30),
            clear=bool(arguments.get("clear", False)),
        )
    )


async def _page_errors_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.page_errors(
            session,
            limit=int(arguments.get("limit") or 20),
            clear=bool(arguments.get("clear", False)),
        )
    )


BROWSER_NETWORK_LAST = ToolSpec(
    name="browser.network.last",
    description=(
        "Return the last N network request/response events (url/method/status only; "
        "bodies redacted/not included)."
    ),
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "limit": {"type": "integer", "default": 20},
        },
        "required": [],
    },
    handler=_network_last_handler,
    tags=("browser", "web", "network", "read"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.network.last"),
    examples=("list recent network requests", "browser network log"),
)

BROWSER_NETWORK_WAIT = ToolSpec(
    name="browser.network.wait",
    description="Wait for a network response matching url, glob, or regex.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "url": {"type": "string"},
            "glob": {"type": "string"},
            "regex": {"type": "string"},
            "timeout_ms": {"type": "integer", "default": 30000},
        },
        "required": [],
    },
    handler=_network_wait_handler,
    tags=("browser", "web", "network", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.network.wait"),
    examples=("wait for api response", "wait network url pattern"),
)

BROWSER_CONSOLE = ToolSpec(
    name="browser.console",
    description="Get recent browser console messages (size-capped).",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "limit": {"type": "integer", "default": 30},
            "clear": {"type": "boolean", "default": False},
        },
        "required": [],
    },
    handler=_console_handler,
    tags=("browser", "web", "diagnostics", "read"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.console"),
    examples=("browser console logs", "get console errors"),
)

BROWSER_PAGE_ERRORS = ToolSpec(
    name="browser.page_errors",
    description="Get recent uncaught page errors.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "limit": {"type": "integer", "default": 20},
            "clear": {"type": "boolean", "default": False},
        },
        "required": [],
    },
    handler=_page_errors_handler,
    tags=("browser", "web", "diagnostics", "read"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.page_errors"),
    examples=("browser page errors", "uncaught js exceptions"),
)

BROWSER_DIAGNOSTICS_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_NETWORK_LAST,
    BROWSER_NETWORK_WAIT,
    BROWSER_CONSOLE,
    BROWSER_PAGE_ERRORS,
)
