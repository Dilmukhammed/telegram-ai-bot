from __future__ import annotations

from typing import Any

from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.session_manager import require_browser_session_manager
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.builtins.pdf.io import _save_image_to_file_ref_sync
from tools.run_files import require_run_file_store
from tools.schema import ToolSpec
from tools.workspace.vision_pending import push_pending_vision

_SESSION_HANDLE_PROP = {
    "session_handle": {
        "type": "string",
        "description": "Optional handle from browser.session_open.",
    }
}


async def _lease_page(arguments: dict[str, Any]):
    manager = require_browser_session_manager()
    handle = arguments.get("session_handle")
    return await manager.get_playwright(str(handle) if handle else None)


async def _get_content_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await _lease_page(arguments)
    result = await pw.get_content(
        session,
        format=str(arguments.get("format") or "text"),
        max_chars=int(arguments.get("max_chars") or 16_000),
    )
    return redact_browser_payload(result)


async def _screenshot_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await _lease_page(arguments)
    png = await pw.screenshot(
        session,
        full_page=bool(arguments.get("full_page", False)),
        ref=arguments.get("ref"),
    )
    output_mode = str(arguments.get("output") or "both")
    width = height = 0
    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(png))
        width, height = img.size
    except Exception:
        pass

    result: dict[str, Any] = {
        "url": session.page.url,
        "width": width,
        "height": height,
        "size_bytes": len(png),
    }
    if output_mode in {"file_ref", "both"}:
        saved = _save_image_to_file_ref_sync(png, "browser_screenshot.png", "image/png")
        result["file_ref"] = saved["file_ref"]
        result["filename"] = saved["filename"]
        result["mime_type"] = saved["mime_type"]
    if output_mode in {"vision", "both"}:
        push_pending_vision("browser screenshot", pw.png_to_data_url(png))
        result["vision_injected"] = True
    return redact_browser_payload(result)


async def _pdf_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await _lease_page(arguments)
    data = await pw.pdf(session, landscape=bool(arguments.get("landscape", False)))
    store = require_run_file_store()
    saved = store.save(data, filename="browser_page.pdf", mime_type="application/pdf")
    return redact_browser_payload(
        {
            "url": session.page.url,
            "file_ref": saved["file_ref"],
            "filename": saved["filename"],
            "mime_type": saved["mime_type"],
            "size": saved["size"],
        }
    )


BROWSER_GET_CONTENT = ToolSpec(
    name="browser.get_content",
    description="Extract page text/HTML/markdown from the active browser session (size-capped).",
    parameters={
        "type": "object",
        "properties": {
            **_SESSION_HANDLE_PROP,
            "format": {
                "type": "string",
                "enum": ["text", "html", "markdown"],
                "default": "text",
            },
            "max_chars": {"type": "integer", "default": 16000},
        },
        "required": [],
    },
    handler=_get_content_handler,
    tags=("browser", "web", "read", "scrape"),
    cache_ttl_seconds=None,
    rate_limit=(60, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.get_content"),
    examples=("get page text", "scrape browser html", "extract page content"),
)

BROWSER_SCREENSHOT = ToolSpec(
    name="browser.screenshot",
    description=(
        "Take a PNG screenshot of the page (or element ref). "
        "Returns file_ref for telegram.send_file and can inject vision for the agent."
    ),
    parameters={
        "type": "object",
        "properties": {
            **_SESSION_HANDLE_PROP,
            "full_page": {"type": "boolean", "default": False},
            "ref": {"type": "string"},
            "output": {
                "type": "string",
                "enum": ["vision", "file_ref", "both"],
                "default": "both",
            },
        },
        "required": [],
    },
    handler=_screenshot_handler,
    tags=("browser", "web", "screenshot", "read"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.screenshot"),
    examples=("screenshot webpage", "capture browser page image"),
)

BROWSER_PDF = ToolSpec(
    name="browser.pdf",
    description="Export the current page to a PDF file_ref.",
    parameters={
        "type": "object",
        "properties": {
            **_SESSION_HANDLE_PROP,
            "landscape": {"type": "boolean", "default": False},
        },
        "required": [],
    },
    handler=_pdf_handler,
    tags=("browser", "web", "pdf", "read"),
    cache_ttl_seconds=None,
    rate_limit=(20, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.pdf"),
    examples=("save page as pdf", "browser print pdf"),
)

BROWSER_CONTENT_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_GET_CONTENT,
    BROWSER_SCREENSHOT,
    BROWSER_PDF,
)
