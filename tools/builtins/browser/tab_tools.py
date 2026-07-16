from __future__ import annotations

from typing import Any

from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser._common import SESSION_HANDLE_PROP, lease_page
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.schema import ToolSpec


async def _tabs_list_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.tabs_list(session))


async def _tabs_new_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    url = arguments.get("url")
    return redact_browser_payload(await pw.tabs_new(session, str(url) if url else None))


async def _tabs_switch_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    index = arguments.get("index")
    tab_id = arguments.get("tab_id")
    return redact_browser_payload(
        await pw.tabs_switch(
            session,
            index=int(index) if index is not None else None,
            tab_id=str(tab_id) if tab_id is not None else None,
        )
    )


async def _tabs_close_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    index = arguments.get("index")
    tab_id = arguments.get("tab_id")
    return redact_browser_payload(
        await pw.tabs_close(
            session,
            index=int(index) if index is not None else None,
            tab_id=str(tab_id) if tab_id is not None else None,
        )
    )


async def _back_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.go_back(session))


async def _forward_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.go_forward(session))


async def _reload_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.reload(
            session,
            wait_until=str(arguments.get("wait_until") or "domcontentloaded"),
        )
    )


BROWSER_TABS_LIST = ToolSpec(
    name="browser.tabs.list",
    description="List open browser tabs (index, url, title, active).",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP},
        "required": [],
    },
    handler=_tabs_list_handler,
    tags=("browser", "web", "tabs"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.tabs.list"),
    examples=("list browser tabs", "which tab is open"),
)

BROWSER_TABS_NEW = ToolSpec(
    name="browser.tabs.new",
    description="Open a new browser tab (optionally navigate to url). Becomes active.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "url": {"type": "string", "description": "Optional absolute http(s) URL."},
        },
        "required": [],
    },
    handler=_tabs_new_handler,
    tags=("browser", "web", "tabs", "navigation"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.tabs.new"),
    examples=("new browser tab", "open second tab"),
)

BROWSER_TABS_SWITCH = ToolSpec(
    name="browser.tabs.switch",
    description="Switch active browser tab by index or tab_id from browser.tabs.list.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "index": {"type": "integer"},
            "tab_id": {"type": "string"},
        },
        "required": [],
    },
    handler=_tabs_switch_handler,
    tags=("browser", "web", "tabs"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.tabs.switch"),
    examples=("switch browser tab", "focus tab index"),
)

BROWSER_TABS_CLOSE = ToolSpec(
    name="browser.tabs.close",
    description=(
        "Close a browser tab (default: active). Last tab is kept as about:blank."
    ),
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "index": {"type": "integer"},
            "tab_id": {"type": "string"},
        },
        "required": [],
    },
    handler=_tabs_close_handler,
    tags=("browser", "web", "tabs"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.tabs.close"),
    examples=("close browser tab", "close current tab"),
)

BROWSER_BACK = ToolSpec(
    name="browser.back",
    description="Navigate back in browser history.",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP},
        "required": [],
    },
    handler=_back_handler,
    tags=("browser", "web", "navigation"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.back"),
    examples=("browser go back", "history back"),
)

BROWSER_FORWARD = ToolSpec(
    name="browser.forward",
    description="Navigate forward in browser history.",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP},
        "required": [],
    },
    handler=_forward_handler,
    tags=("browser", "web", "navigation"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.forward"),
    examples=("browser go forward", "history forward"),
)

BROWSER_RELOAD = ToolSpec(
    name="browser.reload",
    description="Reload the active browser page.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "wait_until": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle"],
                "default": "domcontentloaded",
            },
        },
        "required": [],
    },
    handler=_reload_handler,
    tags=("browser", "web", "navigation"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.reload"),
    examples=("reload page", "refresh browser"),
)

BROWSER_TAB_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_TABS_LIST,
    BROWSER_TABS_NEW,
    BROWSER_TABS_SWITCH,
    BROWSER_TABS_CLOSE,
    BROWSER_BACK,
    BROWSER_FORWARD,
    BROWSER_RELOAD,
)
