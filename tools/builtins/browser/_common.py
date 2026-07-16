from __future__ import annotations

from typing import Any

from tools.builtins.browser.session_manager import require_browser_session_manager

SESSION_HANDLE_PROP = {
    "session_handle": {
        "type": "string",
        "description": "Optional handle from browser.session_open.",
    }
}


async def lease_page(arguments: dict[str, Any]):
    manager = require_browser_session_manager()
    handle = arguments.get("session_handle")
    return await manager.get_playwright(str(handle) if handle else None)
