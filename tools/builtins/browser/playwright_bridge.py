from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from config import get_settings
from tools.builtins.browser.errors import (
    BrowserNavigationError,
    BrowserNotConfiguredError,
    BrowserRefNotFoundError,
)
from tools.builtins.browser.serialize import truncate_text

logger = logging.getLogger(__name__)

_REF_RE = re.compile(r"^e\d+$")
_EVAL_MAX_CHARS = 8_000
_NETWORK_MAX = 80
_CONSOLE_MAX = 80
_PAGE_ERROR_MAX = 40


@dataclass
class PlaywrightSession:
    playwright: Any
    browser: Any
    context: Any
    page: Any
    frame: Any | None = None
    refs: dict[str, str] = field(default_factory=dict)
    next_ref: int = 1
    network_events: list[dict[str, Any]] = field(default_factory=list)
    console_messages: list[dict[str, Any]] = field(default_factory=list)
    page_error_messages: list[dict[str, Any]] = field(default_factory=list)
    _diag_attached: set[int] = field(default_factory=set)

    @property
    def target(self) -> Any:
        """Active frame or page for locators/evaluate."""
        return self.frame if self.frame is not None else self.page


def _ring_append(buf: list[dict[str, Any]], item: dict[str, Any], max_n: int) -> None:
    buf.append(item)
    overflow = len(buf) - max_n
    if overflow > 0:
        del buf[:overflow]


def _attach_page_diagnostics(session: PlaywrightSession, page: Any) -> None:
    page_id = id(page)
    if page_id in session._diag_attached:
        return
    session._diag_attached.add(page_id)

    def on_request(request: Any) -> None:
        try:
            _ring_append(
                session.network_events,
                {
                    "type": "request",
                    "method": getattr(request, "method", None),
                    "url": getattr(request, "url", None),
                    "resource_type": getattr(request, "resource_type", None),
                },
                _NETWORK_MAX,
            )
        except Exception:
            pass

    def on_response(response: Any) -> None:
        try:
            req = getattr(response, "request", None)
            _ring_append(
                session.network_events,
                {
                    "type": "response",
                    "status": getattr(response, "status", None),
                    "url": getattr(response, "url", None),
                    "method": getattr(req, "method", None) if req else None,
                    "resource_type": getattr(req, "resource_type", None) if req else None,
                },
                _NETWORK_MAX,
            )
        except Exception:
            pass

    def on_console(msg: Any) -> None:
        try:
            text = str(getattr(msg, "text", "") or "")
            clipped, _ = truncate_text(text, 500)
            _ring_append(
                session.console_messages,
                {
                    "type": str(getattr(msg, "type", "") or ""),
                    "text": clipped,
                },
                _CONSOLE_MAX,
            )
        except Exception:
            pass

    def on_page_error(exc: Any) -> None:
        try:
            text = str(exc)
            clipped, _ = truncate_text(text, 800)
            _ring_append(
                session.page_error_messages,
                {"message": clipped},
                _PAGE_ERROR_MAX,
            )
        except Exception:
            pass

    on = getattr(page, "on", None)
    if not callable(on):
        return
    on("request", on_request)
    on("response", on_response)
    on("console", on_console)
    on("pageerror", on_page_error)


def _ensure_context_diagnostics(session: PlaywrightSession) -> None:
    for page in list(session.context.pages):
        _attach_page_diagnostics(session, page)

    def on_new_page(page: Any) -> None:
        _attach_page_diagnostics(session, page)

    try:
        session.context.on("page", on_new_page)
    except Exception:
        logger.debug("context.on(page) failed", exc_info=True)


async def connect_session(*, websocket_url: str, api_key: str) -> PlaywrightSession:
    try:
        from playwright.async_api import async_playwright
    except ModuleNotFoundError as exc:
        raise BrowserNotConfiguredError(
            "The optional playwright package is required for browser tools"
        ) from exc

    if "apiKey=" in websocket_url or "api_key=" in websocket_url:
        cdp_url = websocket_url
    else:
        sep = "&" if "?" in websocket_url else "?"
        cdp_url = f"{websocket_url}{sep}{urlencode({'apiKey': api_key})}"

    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            context = await browser.new_context()
            page = await context.new_page()
        else:
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
        settings = get_settings()
        try:
            await page.set_viewport_size(
                {
                    "width": settings.browser_viewport_width,
                    "height": settings.browser_viewport_height,
                }
            )
        except Exception:
            logger.debug("viewport set failed", exc_info=True)
        session = PlaywrightSession(
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
        )
        _ensure_context_diagnostics(session)
        return session
    except Exception:
        await playwright.stop()
        raise


async def disconnect_session(session: PlaywrightSession | None) -> None:
    if session is None:
        return
    try:
        await session.browser.close()
    except Exception:
        logger.debug("browser.close failed", exc_info=True)
    try:
        await session.playwright.stop()
    except Exception:
        logger.debug("playwright.stop failed", exc_info=True)


async def add_cookies(
    session: PlaywrightSession,
    cookies: list[dict[str, Any]],
) -> int:
    await session.context.add_cookies(cookies)
    return len(cookies)


async def navigate(
    session: PlaywrightSession,
    url: str,
    *,
    wait_until: str = "domcontentloaded",
) -> dict[str, Any]:
    session.frame = None
    try:
        response = await session.page.goto(url, wait_until=wait_until, timeout=45_000)
        status = response.status if response is not None else None
    except Exception as exc:
        raise BrowserNavigationError(str(exc)) from exc
    return {
        "url": session.page.url,
        "title": await session.page.title(),
        "status": status,
    }


async def snapshot(
    session: PlaywrightSession,
    *,
    interactive: bool = True,
    max_chars: int = 12_000,
) -> dict[str, Any]:
    session.refs.clear()
    session.next_ref = 1
    try:
        tree = await session.page.accessibility.snapshot(interesting_only=True)
    except Exception:
        tree = None

    refs: list[dict[str, Any]] = []
    text_parts: list[str] = []

    def walk(node: dict[str, Any] | None, depth: int = 0) -> None:
        if not node:
            return
        role = str(node.get("role") or "")
        name = str(node.get("name") or "")
        value = node.get("value")
        interactive_roles = {
            "button",
            "link",
            "textbox",
            "checkbox",
            "radio",
            "combobox",
            "menuitem",
            "tab",
            "switch",
            "searchbox",
            "option",
        }
        include = (not interactive) or role in interactive_roles or bool(name and role)
        if include and (role or name):
            ref = f"e{session.next_ref}"
            session.next_ref += 1
            selector = _guess_selector(role, name, value)
            session.refs[ref] = selector
            entry: dict[str, Any] = {"ref": ref, "role": role, "name": name}
            if value is not None:
                entry["value"] = value
            refs.append(entry)
            indent = "  " * depth
            text_parts.append(f"{indent}[{ref}] {role} {name}".rstrip())
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, depth + 1)

    if isinstance(tree, dict):
        walk(tree)

    if not refs:
        # Fallback: collect common interactive elements via DOM.
        handles = await session.page.query_selector_all(
            "a, button, input, textarea, select, [role='button'], [role='link']"
        )
        for handle in handles[:80]:
            try:
                tag = (await handle.evaluate("el => el.tagName")).lower()
                name = (
                    await handle.get_attribute("aria-label")
                    or await handle.inner_text()
                    or await handle.get_attribute("placeholder")
                    or await handle.get_attribute("name")
                    or ""
                )
                name = " ".join(str(name).split())[:120]
                ref = f"e{session.next_ref}"
                session.next_ref += 1
                selector = await handle.evaluate(
                    """el => {
                        if (el.id) return '#' + CSS.escape(el.id);
                        const name = el.getAttribute('name');
                        if (name) return el.tagName.toLowerCase() + '[name="' + name.replace(/"/g, '\\\\"') + '"]';
                        return null;
                    }"""
                )
                if not selector:
                    selector = f"{tag}:nth-of-type({session.next_ref})"
                session.refs[ref] = selector
                refs.append({"ref": ref, "role": tag, "name": name})
                text_parts.append(f"[{ref}] {tag} {name}".rstrip())
            except Exception:
                continue

    text_preview, truncated = truncate_text("\n".join(text_parts), max_chars)
    return {
        "url": session.page.url,
        "title": await session.page.title(),
        "refs": refs[:200],
        "text_preview": text_preview,
        "truncated": truncated,
    }


def _guess_selector(role: str, name: str, value: Any) -> str:
    if name:
        safe = name.replace('"', '\\"')
        if role in {"button", "link", "textbox", "checkbox", "radio", "combobox"}:
            return f'role={role}[name="{safe}"]'
        return f'text="{safe}"'
    if role:
        return f"role={role}"
    return "body"


def _resolve_ref(session: PlaywrightSession, ref: str) -> str:
    if ref not in session.refs:
        raise BrowserRefNotFoundError(
            f"Unknown ref {ref}; call browser.snapshot to refresh refs"
        )
    return session.refs[ref]


async def _locator(session: PlaywrightSession, ref: str) -> Any:
    root = session.target
    selector = _resolve_ref(session, ref)
    if selector.startswith("role="):
        # role=button[name="X"]
        body = selector[len("role=") :]
        role = body
        name = None
        if "[name=" in body:
            role, rest = body.split("[name=", 1)
            name = rest.rstrip("]")
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1]
        return root.get_by_role(role, name=name) if name else root.get_by_role(role)
    if selector.startswith('text="') and selector.endswith('"'):
        return root.get_by_text(selector[len('text="') : -1], exact=False)
    return root.locator(selector).first


def _page_info(page: Any) -> dict[str, Any]:
    return {
        "url": getattr(page, "url", None),
    }


async def tabs_list(session: PlaywrightSession) -> dict[str, Any]:
    pages = list(session.context.pages)
    tabs = []
    active_index = 0
    for i, page in enumerate(pages):
        try:
            title = await page.title()
        except Exception:
            title = ""
        active = page is session.page
        if active:
            active_index = i
        tabs.append(
            {
                "index": i,
                "tab_id": str(id(page)),
                "url": page.url,
                "title": title,
                "active": active,
            }
        )
    return {"tabs": tabs, "active_index": active_index, "count": len(tabs)}


async def tabs_new(session: PlaywrightSession, url: str | None = None) -> dict[str, Any]:
    page = await session.context.new_page()
    session.page = page
    session.frame = None
    if url:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    pages = list(session.context.pages)
    return {
        "index": pages.index(page) if page in pages else len(pages) - 1,
        "tab_id": str(id(page)),
        "url": page.url,
        "title": await page.title(),
    }


async def tabs_switch(
    session: PlaywrightSession,
    *,
    index: int | None = None,
    tab_id: str | None = None,
) -> dict[str, Any]:
    pages = list(session.context.pages)
    if not pages:
        raise BrowserNavigationError("No tabs open")
    page = None
    if tab_id is not None:
        for p in pages:
            if str(id(p)) == str(tab_id):
                page = p
                break
        if page is None:
            raise BrowserNavigationError(f"Unknown tab_id: {tab_id}")
    elif index is not None:
        if index < 0 or index >= len(pages):
            raise BrowserNavigationError(f"tab index out of range: {index}")
        page = pages[index]
    else:
        raise ValueError("index or tab_id is required")
    session.page = page
    session.frame = None
    await page.bring_to_front()
    return {
        "index": pages.index(page),
        "tab_id": str(id(page)),
        "url": page.url,
        "title": await page.title(),
    }


async def tabs_close(
    session: PlaywrightSession,
    *,
    index: int | None = None,
    tab_id: str | None = None,
) -> dict[str, Any]:
    pages = list(session.context.pages)
    if not pages:
        raise BrowserNavigationError("No tabs open")
    if tab_id is not None or index is not None:
        await tabs_switch(session, index=index, tab_id=tab_id)
    target = session.page
    pages = list(session.context.pages)
    if len(pages) <= 1:
        # Keep at least one page — navigate to blank instead of closing last.
        await target.goto("about:blank")
        session.frame = None
        return {"closed": False, "kept_last": True, "active_index": 0, "url": target.url}
    await target.close()
    remaining = list(session.context.pages)
    session.page = remaining[-1]
    session.frame = None
    await session.page.bring_to_front()
    return {
        "closed": True,
        "kept_last": False,
        "active_index": remaining.index(session.page),
        "url": session.page.url,
        "title": await session.page.title(),
    }


async def go_back(session: PlaywrightSession) -> dict[str, Any]:
    await session.page.go_back(wait_until="domcontentloaded", timeout=45_000)
    session.frame = None
    return {"url": session.page.url, "title": await session.page.title()}


async def go_forward(session: PlaywrightSession) -> dict[str, Any]:
    await session.page.go_forward(wait_until="domcontentloaded", timeout=45_000)
    session.frame = None
    return {"url": session.page.url, "title": await session.page.title()}


async def reload(
    session: PlaywrightSession,
    *,
    wait_until: str = "domcontentloaded",
) -> dict[str, Any]:
    await session.page.reload(wait_until=wait_until, timeout=45_000)
    session.frame = None
    return {"url": session.page.url, "title": await session.page.title()}


async def hover(session: PlaywrightSession, ref: str) -> dict[str, Any]:
    locator = await _locator(session, ref)
    await locator.hover(timeout=15_000)
    return {"ref": ref, "url": session.page.url}


async def select_option(
    session: PlaywrightSession,
    ref: str,
    *,
    value: str | None = None,
    label: str | None = None,
    index: int | None = None,
) -> dict[str, Any]:
    locator = await _locator(session, ref)
    if value is not None:
        selected = await locator.select_option(value=value, timeout=15_000)
    elif label is not None:
        selected = await locator.select_option(label=label, timeout=15_000)
    elif index is not None:
        selected = await locator.select_option(index=index, timeout=15_000)
    else:
        raise ValueError("value, label, or index is required")
    return {"ref": ref, "selected": selected}


async def check(session: PlaywrightSession, ref: str) -> dict[str, Any]:
    locator = await _locator(session, ref)
    await locator.check(timeout=15_000)
    return {"ref": ref, "checked": True}


async def uncheck(session: PlaywrightSession, ref: str) -> dict[str, Any]:
    locator = await _locator(session, ref)
    await locator.uncheck(timeout=15_000)
    return {"ref": ref, "checked": False}


async def clear_input(session: PlaywrightSession, ref: str) -> dict[str, Any]:
    locator = await _locator(session, ref)
    await locator.fill("", timeout=15_000)
    return {"ref": ref}


async def upload_files(
    session: PlaywrightSession,
    ref: str,
    paths: list[str | Path],
) -> dict[str, Any]:
    locator = await _locator(session, ref)
    str_paths = [str(p) for p in paths]
    await locator.set_input_files(str_paths, timeout=30_000)
    return {
        "ref": ref,
        "files": [Path(p).name for p in str_paths],
        "count": len(str_paths),
    }


async def click_and_download(
    session: PlaywrightSession,
    ref: str | None,
    *,
    timeout_ms: int = 60_000,
) -> tuple[bytes, str]:
    timeout_ms = max(1_000, min(timeout_ms, 120_000))
    async with session.page.expect_download(timeout=timeout_ms) as di:
        if ref:
            locator = await _locator(session, ref)
            await locator.click(timeout=15_000)
    download = await di.value
    path = await download.path()
    suggested = download.suggested_filename or "download.bin"
    if path is None:
        # Stream to bytes via temporary save
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="browser_dl_")) / suggested
        await download.save_as(str(tmp))
        data = tmp.read_bytes()
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return data, suggested
    return Path(path).read_bytes(), suggested


async def wait_for_download(
    session: PlaywrightSession,
    *,
    timeout_ms: int = 60_000,
) -> tuple[bytes, str]:
    """Wait for the next download event (trigger must already be in flight or follow)."""
    timeout_ms = max(1_000, min(timeout_ms, 120_000))
    download = await session.page.wait_for_event("download", timeout=timeout_ms)
    suggested = download.suggested_filename or "download.bin"
    path = await download.path()
    if path is None:
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="browser_dl_")) / suggested
        await download.save_as(str(tmp))
        data = tmp.read_bytes()
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return data, suggested
    return Path(path).read_bytes(), suggested


async def wait_for_url(
    session: PlaywrightSession,
    *,
    url: str | None = None,
    glob: str | None = None,
    regex: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    timeout_ms = max(100, min(timeout_ms, 120_000))
    if url:
        await session.page.wait_for_url(url, timeout=timeout_ms)
        matched = url
    elif glob:
        await session.page.wait_for_url(glob, timeout=timeout_ms)
        matched = glob
    elif regex:
        await session.page.wait_for_url(re.compile(regex), timeout=timeout_ms)
        matched = regex
    else:
        raise ValueError("url, glob, or regex is required")
    return {"url": session.page.url, "matched": matched, "title": await session.page.title()}


async def wait_for_load(
    session: PlaywrightSession,
    *,
    wait_until: str = "load",
    timeout_ms: int = 45_000,
) -> dict[str, Any]:
    timeout_ms = max(100, min(timeout_ms, 120_000))
    await session.page.wait_for_load_state(wait_until, timeout=timeout_ms)
    return {"url": session.page.url, "title": await session.page.title(), "wait_until": wait_until}


async def get_attribute(session: PlaywrightSession, ref: str, name: str) -> dict[str, Any]:
    locator = await _locator(session, ref)
    value = await locator.get_attribute(name, timeout=15_000)
    return {"ref": ref, "name": name, "value": value}


async def get_value(session: PlaywrightSession, ref: str) -> dict[str, Any]:
    locator = await _locator(session, ref)
    value = await locator.input_value(timeout=15_000)
    return {"ref": ref, "value": value}


async def is_visible(session: PlaywrightSession, ref: str) -> dict[str, Any]:
    locator = await _locator(session, ref)
    visible = await locator.is_visible()
    return {"ref": ref, "visible": bool(visible)}


async def is_enabled(session: PlaywrightSession, ref: str) -> dict[str, Any]:
    locator = await _locator(session, ref)
    enabled = await locator.is_enabled()
    return {"ref": ref, "enabled": bool(enabled)}


async def cookies_get(session: PlaywrightSession, urls: list[str] | None = None) -> dict[str, Any]:
    if urls:
        cookies = await session.context.cookies(urls)
    else:
        cookies = await session.context.cookies()
    return {"count": len(cookies), "cookies": cookies}


async def cookies_clear(session: PlaywrightSession) -> dict[str, Any]:
    await session.context.clear_cookies()
    return {"cleared": True}


async def frame_switch(
    session: PlaywrightSession,
    *,
    main: bool = False,
    name: str | None = None,
    url: str | None = None,
    index: int | None = None,
) -> dict[str, Any]:
    if main:
        session.frame = None
        return {"frame": "main", "url": session.page.url}
    frame = None
    if name is not None:
        frame = session.page.frame(name=name)
    elif url is not None:
        frame = session.page.frame(url=url)
        if frame is None:
            for f in session.page.frames:
                if url in (f.url or ""):
                    frame = f
                    break
    elif index is not None:
        frames = session.page.frames
        if index < 0 or index >= len(frames):
            raise BrowserNavigationError(f"frame index out of range: {index}")
        frame = frames[index]
    else:
        raise ValueError("main, name, url, or index is required")
    if frame is None:
        raise BrowserNavigationError("Frame not found")
    session.frame = frame
    return {"frame": name or url or index, "url": frame.url}


def _serialize_eval_result(value: Any) -> Any:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = json.dumps(str(value), ensure_ascii=False)
    clipped, truncated = truncate_text(text, _EVAL_MAX_CHARS)
    if truncated:
        return {"truncated": True, "json": clipped}
    try:
        return json.loads(clipped)
    except Exception:
        return clipped


async def evaluate(
    session: PlaywrightSession,
    expression: str,
    *,
    timeout_ms: int = 15_000,
) -> dict[str, Any]:
    timeout_ms = max(100, min(timeout_ms, 60_000))
    # Playwright evaluate doesn't take timeout directly on all versions — race with wait.
    import asyncio

    expr = expression.strip()
    if not expr:
        raise ValueError("expression is required")
    # Allow bare expressions or function bodies
    if not (expr.startswith("(") or expr.startswith("()") or expr.startswith("async")):
        if "return " in expr or ";" in expr:
            expr = f"() => {{ {expr} }}"
        else:
            expr = f"() => ({expr})"
    result = await asyncio.wait_for(session.target.evaluate(expr), timeout=timeout_ms / 1000)
    return {"result": _serialize_eval_result(result)}


async def evaluate_on_ref(
    session: PlaywrightSession,
    ref: str,
    expression: str,
    *,
    timeout_ms: int = 15_000,
) -> dict[str, Any]:
    import asyncio

    timeout_ms = max(100, min(timeout_ms, 60_000))
    locator = await _locator(session, ref)
    expr = expression.strip()
    if not expr:
        raise ValueError("expression is required")
    if not expr.startswith("el") and "=>" not in expr:
        expr = f"el => ({expr})"
    result = await asyncio.wait_for(locator.evaluate(expr), timeout=timeout_ms / 1000)
    return {"ref": ref, "result": _serialize_eval_result(result)}


async def click(
    session: PlaywrightSession,
    ref: str,
    *,
    button: str = "left",
    double: bool = False,
) -> dict[str, Any]:
    locator = await _locator(session, ref)
    if double:
        await locator.dblclick(button=button, timeout=15_000)
    else:
        await locator.click(button=button, timeout=15_000)
    return {
        "ref": ref,
        "url": session.page.url,
        "title": await session.page.title(),
    }


async def type_text(
    session: PlaywrightSession,
    ref: str,
    text: str,
    *,
    clear: bool = False,
) -> dict[str, Any]:
    locator = await _locator(session, ref)
    if clear:
        await locator.fill("")
    await locator.type(text, timeout=15_000)
    return {"ref": ref, "length": len(text)}


async def fill(session: PlaywrightSession, ref: str, value: str) -> dict[str, Any]:
    locator = await _locator(session, ref)
    await locator.fill(value, timeout=15_000)
    return {"ref": ref}


async def press(session: PlaywrightSession, key: str) -> dict[str, Any]:
    await session.page.keyboard.press(key)
    return {"key": key}


async def scroll(
    session: PlaywrightSession,
    *,
    direction: str = "down",
    amount: int = 800,
) -> dict[str, Any]:
    delta = amount if direction == "down" else -amount
    await session.page.mouse.wheel(0, delta)
    scroll_y = await session.page.evaluate("() => window.scrollY")
    return {"scroll_y": scroll_y}


async def wait_for(
    session: PlaywrightSession,
    *,
    for_: str,
    value: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    timeout_ms = max(100, min(timeout_ms, 60_000))
    if for_ == "timeout":
        await session.page.wait_for_timeout(timeout_ms if value is None else int(value))
        return {"ok": True, "detail": "timeout"}
    if for_ == "selector":
        if not value:
            raise ValueError("value is required for wait selector")
        await session.page.wait_for_selector(value, timeout=timeout_ms)
        return {"ok": True, "detail": f"selector:{value}"}
    if for_ == "text":
        if not value:
            raise ValueError("value is required for wait text")
        await session.page.get_by_text(value, exact=False).first.wait_for(timeout=timeout_ms)
        return {"ok": True, "detail": f"text:{value}"}
    raise ValueError("for must be selector|text|timeout")


async def get_content(
    session: PlaywrightSession,
    *,
    format: str = "text",
    max_chars: int = 16_000,
) -> dict[str, Any]:
    if format == "html":
        content = await session.page.content()
    elif format == "markdown":
        text = await session.page.inner_text("body")
        content = text
    else:
        content = await session.page.inner_text("body")
    clipped, truncated = truncate_text(content, max_chars)
    return {
        "url": session.page.url,
        "format": format,
        "content": clipped,
        "truncated": truncated,
    }


async def screenshot(
    session: PlaywrightSession,
    *,
    full_page: bool = False,
    ref: str | None = None,
) -> bytes:
    if ref:
        locator = await _locator(session, ref)
        return await locator.screenshot(type="png")
    return await session.page.screenshot(full_page=full_page, type="png")


async def pdf(session: PlaywrightSession, *, landscape: bool = False) -> bytes:
    return await session.page.pdf(landscape=landscape)


def png_to_data_url(png: bytes) -> str:
    encoded = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{encoded}"


async def _ref_center(session: PlaywrightSession, ref: str) -> tuple[float, float]:
    locator = await _locator(session, ref)
    box = await locator.bounding_box(timeout=15_000)
    if not box:
        raise BrowserNavigationError(f"Element {ref} has no bounding box")
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


async def drag(
    session: PlaywrightSession,
    source_ref: str,
    target_ref: str,
) -> dict[str, Any]:
    source = await _locator(session, source_ref)
    target = await _locator(session, target_ref)
    await source.drag_to(target, timeout=30_000)
    return {"source_ref": source_ref, "target_ref": target_ref, "url": session.page.url}


async def focus(session: PlaywrightSession, ref: str) -> dict[str, Any]:
    locator = await _locator(session, ref)
    await locator.focus(timeout=15_000)
    return {"ref": ref}


async def keydown(session: PlaywrightSession, key: str) -> dict[str, Any]:
    await session.page.keyboard.down(key)
    return {"key": key, "action": "down"}


async def keyup(session: PlaywrightSession, key: str) -> dict[str, Any]:
    await session.page.keyboard.up(key)
    return {"key": key, "action": "up"}


async def mouse_move(
    session: PlaywrightSession,
    *,
    x: float | None = None,
    y: float | None = None,
    ref: str | None = None,
    steps: int = 1,
) -> dict[str, Any]:
    if ref is not None:
        x, y = await _ref_center(session, ref)
    if x is None or y is None:
        raise ValueError("Provide x+y or ref")
    await session.page.mouse.move(float(x), float(y), steps=max(1, min(int(steps), 50)))
    return {"x": x, "y": y, "ref": ref}


async def mouse_down(
    session: PlaywrightSession,
    *,
    button: str = "left",
    click_count: int = 1,
) -> dict[str, Any]:
    await session.page.mouse.down(button=button, click_count=max(1, int(click_count)))
    return {"button": button, "action": "down"}


async def mouse_up(
    session: PlaywrightSession,
    *,
    button: str = "left",
    click_count: int = 1,
) -> dict[str, Any]:
    await session.page.mouse.up(button=button, click_count=max(1, int(click_count)))
    return {"button": button, "action": "up"}


async def storage_get(
    session: PlaywrightSession,
    *,
    area: str,
    key: str | None = None,
) -> dict[str, Any]:
    if area not in {"local", "session"}:
        raise ValueError("area must be local|session")
    store = "localStorage" if area == "local" else "sessionStorage"
    if key is None:
        raw = await session.page.evaluate(
            f"() => JSON.stringify(Object.fromEntries(Object.entries({store})))"
        )
        data = json.loads(raw or "{}")
        text = json.dumps(data, ensure_ascii=False)
        clipped, truncated = truncate_text(text, _EVAL_MAX_CHARS)
        return {
            "area": area,
            "count": len(data) if isinstance(data, dict) else 0,
            "items": json.loads(clipped) if not truncated else None,
            "json": clipped if truncated else None,
            "truncated": truncated,
        }
    value = await session.page.evaluate(
        f"(k) => {store}.getItem(k)",
        str(key),
    )
    if isinstance(value, str):
        value, _ = truncate_text(value, _EVAL_MAX_CHARS)
    return {"area": area, "key": key, "value": value}


async def storage_set(
    session: PlaywrightSession,
    *,
    area: str,
    key: str,
    value: str,
) -> dict[str, Any]:
    if area not in {"local", "session"}:
        raise ValueError("area must be local|session")
    store = "localStorage" if area == "local" else "sessionStorage"
    await session.page.evaluate(
        f"([k, v]) => {{ {store}.setItem(k, v); }}",
        [str(key), str(value)],
    )
    return {"area": area, "key": key, "set": True}


async def set_viewport(
    session: PlaywrightSession,
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    width = max(200, min(int(width), 3840))
    height = max(200, min(int(height), 2160))
    await session.page.set_viewport_size({"width": width, "height": height})
    return {"width": width, "height": height}


async def set_geolocation(
    session: PlaywrightSession,
    *,
    latitude: float,
    longitude: float,
    accuracy: float | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "latitude": float(latitude),
        "longitude": float(longitude),
    }
    if accuracy is not None:
        payload["accuracy"] = float(accuracy)
    await session.context.set_geolocation(payload)
    try:
        await session.context.grant_permissions(["geolocation"])
    except Exception:
        logger.debug("grant geolocation permission failed", exc_info=True)
    return {"geolocation": payload}


async def set_locale(session: PlaywrightSession, locale: str) -> dict[str, Any]:
    locale = str(locale).strip()
    if not locale:
        raise ValueError("locale is required")
    client = await session.context.new_cdp_session(session.page)
    try:
        await client.send("Emulation.setLocaleOverride", {"locale": locale})
    finally:
        try:
            await client.detach()
        except Exception:
            pass
    return {"locale": locale}


async def set_timezone(session: PlaywrightSession, timezone_id: str) -> dict[str, Any]:
    timezone_id = str(timezone_id).strip()
    if not timezone_id:
        raise ValueError("timezone_id is required")
    client = await session.context.new_cdp_session(session.page)
    try:
        await client.send("Emulation.setTimezoneOverride", {"timezoneId": timezone_id})
    finally:
        try:
            await client.detach()
        except Exception:
            pass
    return {"timezone_id": timezone_id}


async def grant_permissions(
    session: PlaywrightSession,
    permissions: list[str],
    *,
    origin: str | None = None,
) -> dict[str, Any]:
    perms = [str(p) for p in permissions]
    if origin:
        await session.context.grant_permissions(perms, origin=origin)
    else:
        await session.context.grant_permissions(perms)
    return {"granted": perms, "origin": origin}


async def clear_permissions(session: PlaywrightSession) -> dict[str, Any]:
    await session.context.clear_permissions()
    return {"cleared": True}


async def network_last(session: PlaywrightSession, *, limit: int = 20) -> dict[str, Any]:
    _ensure_context_diagnostics(session)
    limit = max(1, min(int(limit), _NETWORK_MAX))
    events = session.network_events[-limit:]
    return {"count": len(events), "events": list(events)}


async def network_wait(
    session: PlaywrightSession,
    *,
    url: str | None = None,
    glob: str | None = None,
    regex: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    timeout_ms = max(100, min(timeout_ms, 120_000))
    pattern: Any
    if url:
        pattern = url
    elif glob:
        pattern = glob
    elif regex:
        pattern = re.compile(regex)
    else:
        raise ValueError("url, glob, or regex is required")

    response = await session.page.wait_for_response(pattern, timeout=timeout_ms)
    return {
        "url": response.url,
        "status": response.status,
        "ok": response.ok,
    }


async def console_messages(
    session: PlaywrightSession,
    *,
    limit: int = 30,
    clear: bool = False,
) -> dict[str, Any]:
    _ensure_context_diagnostics(session)
    limit = max(1, min(int(limit), _CONSOLE_MAX))
    msgs = list(session.console_messages[-limit:])
    if clear:
        session.console_messages.clear()
    return {"count": len(msgs), "messages": msgs}


async def page_errors(
    session: PlaywrightSession,
    *,
    limit: int = 20,
    clear: bool = False,
) -> dict[str, Any]:
    _ensure_context_diagnostics(session)
    limit = max(1, min(int(limit), _PAGE_ERROR_MAX))
    errs = list(session.page_error_messages[-limit:])
    if clear:
        session.page_error_messages.clear()
    return {"count": len(errs), "errors": errs}
