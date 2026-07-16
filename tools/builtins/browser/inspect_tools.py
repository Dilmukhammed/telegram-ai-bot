from __future__ import annotations

from typing import Any

from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser._common import SESSION_HANDLE_PROP, lease_page
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.schema import ToolSpec


async def _wait_for_url_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.wait_for_url(
            session,
            url=str(arguments["url"]) if arguments.get("url") else None,
            glob=str(arguments["glob"]) if arguments.get("glob") else None,
            regex=str(arguments["regex"]) if arguments.get("regex") else None,
            timeout_ms=int(arguments.get("timeout_ms") or 30_000),
        )
    )


async def _wait_for_load_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.wait_for_load(
            session,
            wait_until=str(arguments.get("wait_until") or "load"),
            timeout_ms=int(arguments.get("timeout_ms") or 45_000),
        )
    )


async def _get_attribute_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.get_attribute(session, str(arguments["ref"]), str(arguments["name"]))
    )


async def _get_value_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.get_value(session, str(arguments["ref"])))


async def _is_visible_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.is_visible(session, str(arguments["ref"])))


async def _is_enabled_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.is_enabled(session, str(arguments["ref"])))


_REF_PROP = {"ref": {"type": "string", "description": "Element ref from browser.snapshot."}}

BROWSER_WAIT_FOR_URL = ToolSpec(
    name="browser.wait_for_url",
    description="Wait until the page URL matches url, glob, or regex.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "url": {"type": "string"},
            "glob": {"type": "string", "description": "e.g. **/dashboard**"},
            "regex": {"type": "string"},
            "timeout_ms": {"type": "integer", "default": 30000},
        },
        "required": [],
    },
    handler=_wait_for_url_handler,
    tags=("browser", "web", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.wait_for_url"),
    examples=("wait for url change", "wait until redirected"),
)

BROWSER_WAIT_FOR_LOAD = ToolSpec(
    name="browser.wait_for_load",
    description="Wait for page load state (load|domcontentloaded|networkidle).",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "wait_until": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle"],
                "default": "load",
            },
            "timeout_ms": {"type": "integer", "default": 45000},
        },
        "required": [],
    },
    handler=_wait_for_load_handler,
    tags=("browser", "web", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.wait_for_load"),
    examples=("wait for page load", "wait networkidle"),
)

BROWSER_GET_ATTRIBUTE = ToolSpec(
    name="browser.get_attribute",
    description="Read a DOM attribute from an element ref.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            **_REF_PROP,
            "name": {"type": "string", "description": "Attribute name, e.g. href, aria-label."},
        },
        "required": ["ref", "name"],
    },
    handler=_get_attribute_handler,
    tags=("browser", "web", "read"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.get_attribute"),
    examples=("get href attribute", "read aria-label"),
)

BROWSER_GET_VALUE = ToolSpec(
    name="browser.get_value",
    description="Read the current value of an input/textarea/select by ref.",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP, **_REF_PROP},
        "required": ["ref"],
    },
    handler=_get_value_handler,
    tags=("browser", "web", "read"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.get_value"),
    examples=("get input value", "read form field"),
)

BROWSER_IS_VISIBLE = ToolSpec(
    name="browser.is_visible",
    description="Check whether an element ref is visible.",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP, **_REF_PROP},
        "required": ["ref"],
    },
    handler=_is_visible_handler,
    tags=("browser", "web", "read"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.is_visible"),
    examples=("is element visible",),
)

BROWSER_IS_ENABLED = ToolSpec(
    name="browser.is_enabled",
    description="Check whether an element ref is enabled.",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP, **_REF_PROP},
        "required": ["ref"],
    },
    handler=_is_enabled_handler,
    tags=("browser", "web", "read"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.is_enabled"),
    examples=("is button enabled",),
)

BROWSER_INSPECT_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_WAIT_FOR_URL,
    BROWSER_WAIT_FOR_LOAD,
    BROWSER_GET_ATTRIBUTE,
    BROWSER_GET_VALUE,
    BROWSER_IS_VISIBLE,
    BROWSER_IS_ENABLED,
)
