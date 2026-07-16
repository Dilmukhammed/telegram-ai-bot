from __future__ import annotations

from typing import Any

from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser._common import SESSION_HANDLE_PROP, lease_page
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.schema import ToolSpec


async def _frame_switch_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    index = arguments.get("index")
    return redact_browser_payload(
        await pw.frame_switch(
            session,
            main=bool(arguments.get("main", False)),
            name=str(arguments["name"]) if arguments.get("name") is not None else None,
            url=str(arguments["url"]) if arguments.get("url") is not None else None,
            index=int(index) if index is not None else None,
        )
    )


async def _evaluate_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.evaluate(
            session,
            str(arguments["expression"]),
            timeout_ms=int(arguments.get("timeout_ms") or 15_000),
        )
    )


async def _evaluate_on_ref_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.evaluate_on_ref(
            session,
            str(arguments["ref"]),
            str(arguments["expression"]),
            timeout_ms=int(arguments.get("timeout_ms") or 15_000),
        )
    )


BROWSER_FRAME_SWITCH = ToolSpec(
    name="browser.frame_switch",
    description=(
        "Switch locator/evaluate target to an iframe (name/url/index) or main:true for top."
    ),
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "main": {"type": "boolean", "default": False},
            "name": {"type": "string"},
            "url": {"type": "string"},
            "index": {"type": "integer"},
        },
        "required": [],
    },
    handler=_frame_switch_handler,
    tags=("browser", "web", "frames", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.frame_switch"),
    examples=("switch to iframe", "frame main content"),
)

BROWSER_EVALUATE = ToolSpec(
    name="browser.evaluate",
    description=(
        "Run JavaScript in the active page/frame. Expression or () => value. "
        "Result is JSON-serialized and size-capped. Prefer snapshot/refs when possible."
    ),
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "expression": {"type": "string"},
            "timeout_ms": {"type": "integer", "default": 15000},
        },
        "required": ["expression"],
    },
    handler=_evaluate_handler,
    tags=("browser", "web", "automation", "js"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.evaluate"),
    examples=("evaluate javascript in browser", "run js on page"),
)

BROWSER_EVALUATE_ON_REF = ToolSpec(
    name="browser.evaluate_on_ref",
    description=(
        "Run JavaScript on an element ref. Expression receives `el` "
        "(e.g. `el => el.innerText`)."
    ),
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "ref": {"type": "string"},
            "expression": {"type": "string"},
            "timeout_ms": {"type": "integer", "default": 15000},
        },
        "required": ["ref", "expression"],
    },
    handler=_evaluate_on_ref_handler,
    tags=("browser", "web", "automation", "js"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.evaluate_on_ref"),
    examples=("evaluate on element ref", "get innerText via js"),
)

BROWSER_FRAME_EVAL_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_FRAME_SWITCH,
    BROWSER_EVALUATE,
    BROWSER_EVALUATE_ON_REF,
)
