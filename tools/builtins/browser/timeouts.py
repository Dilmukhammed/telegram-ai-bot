from __future__ import annotations

from config import get_settings


def handler_timeout_for_browser_tool(tool_name: str) -> float:
    settings = get_settings()
    if tool_name in {"browser.session_open", "browser.session_close"}:
        return settings.browser_handler_timeout_session
    if tool_name in {
        "browser.navigate",
        "browser.back",
        "browser.forward",
        "browser.reload",
        "browser.tabs.new",
        "browser.wait_for_url",
        "browser.wait_for_load",
        "browser.network.wait",
        "browser.drag",
    }:
        return settings.browser_handler_timeout_navigate
    if tool_name == "browser.snapshot":
        return settings.browser_handler_timeout_snapshot
    if tool_name in {
        "browser.screenshot",
        "browser.pdf",
        "browser.download",
        "browser.wait_for_download",
        "browser.upload",
    }:
        return settings.browser_handler_timeout_screenshot
    return settings.browser_handler_timeout_default
