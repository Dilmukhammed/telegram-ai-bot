from __future__ import annotations

import json
from typing import Any

from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser._common import SESSION_HANDLE_PROP, lease_page
from tools.builtins.browser.cookies import parse_cookies_payload
from tools.builtins.browser.serialize import redact_browser_payload, truncate_text
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.run_files import require_run_file_store
from tools.schema import ToolSpec

_COOKIE_EXPORT_MAX = 200_000


async def _cookies_get_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    urls = arguments.get("urls")
    url_list = [str(u) for u in urls] if isinstance(urls, list) else None
    return redact_browser_payload(await pw.cookies_get(session, url_list))


async def _cookies_set_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    cookies = parse_cookies_payload(arguments.get("cookies") or arguments.get("cookies_json"))
    added = await pw.add_cookies(session, cookies)
    return redact_browser_payload({"set": added})


async def _cookies_clear_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    # Playwright clear_cookies clears all for context; url filter not available broadly.
    _ = arguments.get("url")
    return redact_browser_payload(await pw.cookies_clear(session))


async def _cookies_export_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    urls = arguments.get("urls")
    url_list = [str(u) for u in urls] if isinstance(urls, list) else None
    payload = await pw.cookies_get(session, url_list)
    cookies = payload.get("cookies") or []
    raw = json.dumps(cookies, ensure_ascii=False, indent=2)
    clipped, truncated = truncate_text(raw, _COOKIE_EXPORT_MAX)
    store = require_run_file_store()
    saved = store.save(
        clipped.encode("utf-8"),
        filename="browser_cookies.json",
        mime_type="application/json",
    )
    return redact_browser_payload(
        {
            "count": len(cookies),
            "truncated": truncated,
            "file_ref": saved["file_ref"],
            "filename": saved["filename"],
            "mime_type": saved["mime_type"],
            "size": saved["size"],
        }
    )


BROWSER_COOKIES_GET = ToolSpec(
    name="browser.cookies.get",
    description="Get cookies from the active browser context (optionally filter by urls).",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional URL filters.",
            },
        },
        "required": [],
    },
    handler=_cookies_get_handler,
    tags=("browser", "web", "auth", "cookies"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.cookies.get"),
    examples=("get browser cookies", "list session cookies"),
)

BROWSER_COOKIES_SET = ToolSpec(
    name="browser.cookies.set",
    description="Set cookies on the active browser context (Chrome export / Playwright format).",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "cookies": {
                "description": "Cookie list or Chrome Cookie-Editor JSON.",
            },
            "cookies_json": {"type": "string"},
        },
        "required": [],
    },
    handler=_cookies_set_handler,
    tags=("browser", "web", "auth", "cookies"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.cookies.set"),
    examples=("set browser cookies", "add cookies to session"),
)

BROWSER_COOKIES_CLEAR = ToolSpec(
    name="browser.cookies.clear",
    description="Clear all cookies in the active browser context.",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "url": {
                "type": "string",
                "description": "Ignored today; clears entire context.",
            },
        },
        "required": [],
    },
    handler=_cookies_clear_handler,
    tags=("browser", "web", "auth", "cookies"),
    cache_ttl_seconds=None,
    rate_limit=(20, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.cookies.clear"),
    examples=("clear browser cookies",),
)

BROWSER_COOKIES_EXPORT = ToolSpec(
    name="browser.cookies.export",
    description="Export context cookies to a JSON file_ref (size-capped).",
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "urls": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [],
    },
    handler=_cookies_export_handler,
    tags=("browser", "web", "auth", "cookies"),
    cache_ttl_seconds=None,
    rate_limit=(20, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.cookies.export"),
    examples=("export browser cookies json",),
)

BROWSER_COOKIE_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_COOKIES_GET,
    BROWSER_COOKIES_SET,
    BROWSER_COOKIES_CLEAR,
    BROWSER_COOKIES_EXPORT,
)
