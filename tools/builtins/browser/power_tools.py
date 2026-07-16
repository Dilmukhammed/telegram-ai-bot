from __future__ import annotations

from typing import Any

from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser._common import SESSION_HANDLE_PROP, lease_page
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.schema import ToolSpec

_REF_PROP = {"ref": {"type": "string", "description": "Element ref from browser.snapshot."}}


async def _drag_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.drag(
            session,
            str(arguments["source_ref"]),
            str(arguments["target_ref"]),
        )
    )


async def _focus_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.focus(session, str(arguments["ref"])))


async def _keydown_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.keydown(session, str(arguments["key"])))


async def _keyup_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(await pw.keyup(session, str(arguments["key"])))


async def _mouse_move_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    x = arguments.get("x")
    y = arguments.get("y")
    return redact_browser_payload(
        await pw.mouse_move(
            session,
            x=float(x) if x is not None else None,
            y=float(y) if y is not None else None,
            ref=str(arguments["ref"]) if arguments.get("ref") else None,
            steps=int(arguments.get("steps") or 1),
        )
    )


async def _mouse_down_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.mouse_down(
            session,
            button=str(arguments.get("button") or "left"),
            click_count=int(arguments.get("click_count") or 1),
        )
    )


async def _mouse_up_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    return redact_browser_payload(
        await pw.mouse_up(
            session,
            button=str(arguments.get("button") or "left"),
            click_count=int(arguments.get("click_count") or 1),
        )
    )


BROWSER_DRAG = ToolSpec(
    name="browser.drag",
    description="Drag source_ref onto target_ref (HTML5 / pointer drag).",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "source_ref": {"type": "string"},
            "target_ref": {"type": "string"},
        },
        "required": ["source_ref", "target_ref"],
    },
    handler=_drag_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.drag"),
    examples=("drag and drop browser", "drag element onto target"),
)

BROWSER_FOCUS = ToolSpec(
    name="browser.focus",
    description="Focus an element by ref.",
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP, **_REF_PROP},
        "required": ["ref"],
    },
    handler=_focus_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.focus"),
    examples=("focus input browser",),
)

BROWSER_KEYDOWN = ToolSpec(
    name="browser.keydown",
    description="Hold a keyboard key down (pair with browser.keyup).",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "key": {"type": "string"},
        },
        "required": ["key"],
    },
    handler=_keydown_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.keydown"),
    examples=("keydown shift browser",),
)

BROWSER_KEYUP = ToolSpec(
    name="browser.keyup",
    description="Release a keyboard key previously held with browser.keydown.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "key": {"type": "string"},
        },
        "required": ["key"],
    },
    handler=_keyup_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.keyup"),
    examples=("keyup shift browser",),
)

BROWSER_MOUSE_MOVE = ToolSpec(
    name="browser.mouse_move",
    description="Move mouse to x/y or center of an element ref.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "x": {"type": "number"},
            "y": {"type": "number"},
            "ref": {"type": "string"},
            "steps": {"type": "integer", "default": 1},
        },
        "required": [],
    },
    handler=_mouse_move_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.mouse_move"),
    examples=("move mouse to element", "mouse move coordinates"),
)

BROWSER_MOUSE_DOWN = ToolSpec(
    name="browser.mouse_down",
    description="Press mouse button at current position.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
            "click_count": {"type": "integer", "default": 1},
        },
        "required": [],
    },
    handler=_mouse_down_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.mouse_down"),
    examples=("mouse down browser",),
)

BROWSER_MOUSE_UP = ToolSpec(
    name="browser.mouse_up",
    description="Release mouse button at current position.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
            "click_count": {"type": "integer", "default": 1},
        },
        "required": [],
    },
    handler=_mouse_up_handler,
    tags=("browser", "web", "write", "automation"),
    cache_ttl_seconds=None,
    rate_limit=(120, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.mouse_up"),
    examples=("mouse up browser",),
)

BROWSER_POWER_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_DRAG,
    BROWSER_FOCUS,
    BROWSER_KEYDOWN,
    BROWSER_KEYUP,
    BROWSER_MOUSE_MOVE,
    BROWSER_MOUSE_DOWN,
    BROWSER_MOUSE_UP,
)
