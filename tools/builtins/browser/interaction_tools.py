from __future__ import annotations

from typing import Any

from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser._common import SESSION_HANDLE_PROP, lease_page
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.schema import ToolSpec


async def _hover_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.hover(session, str(arguments["ref"])))


async def _select_option_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    index = arguments.get("index")
    return redact_browser_payload(
        await pw.select_option(
            session,
            str(arguments["ref"]),
            value=str(arguments["value"]) if arguments.get("value") is not None else None,
            label=str(arguments["label"]) if arguments.get("label") is not None else None,
            index=int(index) if index is not None else None,
        )
    )


async def _check_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.check(session, str(arguments["ref"])))


async def _uncheck_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.uncheck(session, str(arguments["ref"])))


async def _clear_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.clear_input(session, str(arguments["ref"])))


_REF_PROP = {"ref": {"type": "string", "description": "Element ref from browser.snapshot."}}

BROWSER_HOVER = ToolSpec(
    name="browser.hover",
    description="Hover over an element by ref (opens menus/tooltips).",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP, **_REF_PROP},
        "required": ["ref"],
    },
    handler=_hover_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.hover"),
    examples=("hover menu browser", "hover element ref"),
)

BROWSER_SELECT_OPTION = ToolSpec(
    name="browser.select_option",
    description="Select an option in a <select> by value, label, or index.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            **_REF_PROP,
            "value": {"type": "string"},
            "label": {"type": "string"},
            "index": {"type": "integer"},
        },
        "required": ["ref"],
    },
    handler=_select_option_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.select_option"),
    examples=("select dropdown option", "choose select value"),
)

BROWSER_CHECK = ToolSpec(
    name="browser.check",
    description="Check a checkbox/radio by ref.",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP, **_REF_PROP},
        "required": ["ref"],
    },
    handler=_check_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.check"),
    examples=("check checkbox browser",),
)

BROWSER_UNCHECK = ToolSpec(
    name="browser.uncheck",
    description="Uncheck a checkbox by ref.",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP, **_REF_PROP},
        "required": ["ref"],
    },
    handler=_uncheck_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.uncheck"),
    examples=("uncheck checkbox browser",),
)

BROWSER_CLEAR = ToolSpec(
    name="browser.clear",
    description="Clear an input/textarea value by ref.",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP, **_REF_PROP},
        "required": ["ref"],
    },
    handler=_clear_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.clear"),
    examples=("clear input field", "empty textbox"),
)

BROWSER_INTERACTION_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_HOVER,
    BROWSER_SELECT_OPTION,
    BROWSER_CHECK,
    BROWSER_UNCHECK,
    BROWSER_CLEAR,
)
