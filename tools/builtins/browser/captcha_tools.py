"""browser.captcha.detect / browser.captcha.solve tools."""

from __future__ import annotations

import base64
import logging
from typing import Any

from bot.browser_login_notify import send_browser_captcha_link
from config import get_settings
from tools.builtins.browser import playwright_bridge as pw
from tools.builtins.browser._common import SESSION_HANDLE_PROP, lease_page
from tools.builtins.browser.captcha_detect import (
    DETECT_JS,
    classify_solve_backend,
    normalize_detect_result,
)
from tools.builtins.browser.captcha_ocr import (
    CaptchaOcrMissingError,
    ocr_available,
    recognize_text,
    slide_gap_distance,
)
from tools.builtins.browser.captcha_token import (
    CaptchaTokenNotConfiguredError,
    INJECT_TOKEN_JS,
    get_token_provider,
)
from tools.builtins.browser.errors import (
    BrowserError,
    BrowserNoSessionError,
    BrowserViewerNotConfiguredError,
)
from tools.builtins.browser.serialize import redact_browser_payload
from tools.builtins.browser.session_manager import require_browser_session_manager
from tools.builtins.browser.timeouts import handler_timeout_for_browser_tool
from tools.builtins.browser.viewer_tokens import mint_viewer_token
from tools.context import get_run_context
from tools.schema import ToolSpec

logger = logging.getLogger(__name__)


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise BrowserError("Telegram user_id is missing in tool context")
    return user_id


async def _detect_on_session(session: Any) -> dict[str, Any]:
    eval_result = await pw.evaluate(session, DETECT_JS, timeout_ms=20_000)
    raw = eval_result.get("result")
    page_url = getattr(session.page, "url", None)
    return normalize_detect_result(raw, page_url=page_url)


async def _detect_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _lease, session = await lease_page(arguments)
    detected = await _detect_on_session(session)
    detected["preferred_backend"] = classify_solve_backend(detected.get("kind"))
    settings = get_settings()
    detected["backends"] = {
        "ocr": bool(settings.captcha_ocr_enabled) and ocr_available(),
        "token": bool((settings.capsolver_api_key or "").strip()),
        "hitl": True,
    }
    return redact_browser_payload(detected)


async def _solve_ocr(session: Any, detected: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.captcha_ocr_enabled:
        raise CaptchaOcrMissingError("CAPTCHA_OCR_ENABLED=0")

    kind = detected.get("kind")
    page = session.page

    if kind == "slider":
        # Best-effort: find bg + piece images inside bbox region via evaluate
        imgs = await page.evaluate(
            """() => {
              const pick = (sel) => {
                const el = document.querySelector(sel);
                if (!el) return null;
                return el.currentSrc || el.src || null;
              };
              return {
                bg: pick('img.geetest_canvas_bg, img.geetest_bg, .geetest_canvas_img img, [class*="slide"] img:nth-of-type(1)'),
                piece: pick('img.geetest_canvas_slice, img.geetest_slice, [class*="slide"] img:nth-of-type(2)'),
              };
            }"""
        )
        bg_url = (imgs or {}).get("bg")
        piece_url = (imgs or {}).get("piece")
        if not bg_url or not piece_url:
            raise BrowserError(
                "slider images not found; use mode=hitl or provide manual drag"
            )
        bg_bytes = await _fetch_image_bytes(page, bg_url)
        piece_bytes = await _fetch_image_bytes(page, piece_url)
        distance = slide_gap_distance(target_bytes=piece_bytes, background_bytes=bg_bytes)
        # Drag slider handle by distance pixels
        handle = page.locator(
            ".geetest_slider_button, .slider-btn, [class*='slider'] [class*='btn'], "
            "[class*='slide-verify'] .slider, .captcha-slider-btn"
        ).first
        box = await handle.bounding_box(timeout=10_000)
        if not box:
            raise BrowserError("slider handle not found")
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        await page.mouse.move(start_x, start_y)
        await page.mouse.down()
        await page.mouse.move(start_x + float(distance), start_y, steps=20)
        await page.mouse.up()
        return {
            "solved": True,
            "mode": "ocr",
            "kind": "slider",
            "distance": distance,
            "url": page.url,
        }

    # Image / text captcha
    bbox = detected.get("bbox")
    png: bytes
    if isinstance(bbox, dict) and bbox.get("width") and bbox.get("height"):
        png = await page.screenshot(
            type="png",
            clip={
                "x": max(0, float(bbox["x"])),
                "y": max(0, float(bbox["y"])),
                "width": float(bbox["width"]),
                "height": float(bbox["height"]),
            },
        )
    else:
        # Try captcha img element
        loc = page.locator(
            "img[src*='captcha'], img[id*='captcha'], img[class*='captcha'], "
            "canvas[id*='captcha'], canvas[class*='captcha']"
        ).first
        try:
            png = await loc.screenshot(type="png", timeout=8_000)
        except Exception:
            png = await page.screenshot(type="png")

    text = recognize_text(png)
    # Fill nearest captcha input
    filled = await page.evaluate(
        """(text) => {
          const candidates = Array.from(document.querySelectorAll(
            "input[name*='captcha' i], input[id*='captcha' i], input[placeholder*='captcha' i], " +
            "input[name*='code' i], input[autocomplete='off']"
          )).filter(el => el.offsetParent !== null);
          const el = candidates[0];
          if (!el) return { filled: false };
          el.focus();
          el.value = text;
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
          return { filled: true, name: el.name || el.id || null };
        }""",
        text,
    )
    return {
        "solved": True,
        "mode": "ocr",
        "kind": kind or "image",
        "text_len": len(text),
        "input_filled": bool((filled or {}).get("filled")),
        "url": page.url,
    }


async def _fetch_image_bytes(page: Any, url: str) -> bytes:
    if url.startswith("data:"):
        # data:image/png;base64,...
        try:
            _header, b64 = url.split(",", 1)
            return base64.b64decode(b64)
        except Exception as exc:
            raise BrowserError(f"bad data-url image: {exc}") from exc
    # Fetch in-page to reuse cookies
    b64 = await page.evaluate(
        """async (url) => {
          const resp = await fetch(url, { credentials: 'include' });
          const buf = await resp.arrayBuffer();
          const bytes = new Uint8Array(buf);
          let binary = '';
          for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
          return btoa(binary);
        }""",
        url,
    )
    if not b64:
        raise BrowserError("failed to fetch captcha image")
    return base64.b64decode(b64)


async def _solve_token(
    session: Any,
    detected: dict[str, Any],
    *,
    timeout_ms: int,
) -> dict[str, Any]:
    provider = get_token_provider()
    if provider is None:
        raise CaptchaTokenNotConfiguredError(
            "CAPSOLVER_API_KEY not set; use mode=hitl or configure CapSolver"
        )
    kind = str(detected.get("kind") or "recaptcha_v2")
    sitekey = detected.get("sitekey")
    if not sitekey:
        raise BrowserError("token captcha detected but sitekey missing; try mode=hitl")
    website_url = detected.get("url") or session.page.url
    settings = get_settings()
    timeout_s = max(
        10.0,
        min(
            timeout_ms / 1000.0,
            float(settings.captcha_solver_timeout_seconds),
        ),
    )
    token = await provider.solve(
        kind=kind,
        website_url=str(website_url),
        website_key=str(sitekey),
        action=detected.get("action"),
        timeout_seconds=timeout_s,
    )
    # Never put token in tool result
    inject = await session.page.evaluate(
        INJECT_TOKEN_JS,
        {"token": token, "kind": kind},
    )
    return {
        "solved": bool((inject or {}).get("ok")),
        "mode": "token",
        "kind": kind,
        "injected": (inject or {}).get("filled", 0),
        "url": session.page.url,
        "provider": "capsolver",
    }


async def _solve_hitl(
    *,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    user_id = _require_user_id()
    manager = require_browser_session_manager()
    lease = manager.lease
    if lease is None or lease.closed:
        raise BrowserNoSessionError("No active browser session for captcha HITL")
    debug_url = lease.debug_url
    if not debug_url:
        raise BrowserViewerNotConfiguredError("Session has no debug/viewer URL")

    settings = get_settings()
    ttl = None
    if timeout_ms is not None:
        ttl = max(30, min(int(timeout_ms / 1000), settings.browser_session_max_seconds))

    _token, public_url, expires_at = mint_viewer_token(
        telegram_user_id=user_id,
        steel_session_id=lease.steel_session_id,
        debug_url=debug_url,
        ttl_seconds=ttl,
    )
    await send_browser_captcha_link(
        user_id,
        public_url=public_url,
        expires_at=expires_at,
    )
    return {
        "solved": False,
        "mode": "hitl",
        "viewer_dispatched": True,
        "expires_at": expires_at,
        "message": "Captcha viewer link sent in Telegram; wait for the user to solve it.",
    }


async def _solve_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    mode = str(arguments.get("mode") or "auto").lower().strip()
    if mode not in {"auto", "ocr", "token", "hitl"}:
        mode = "auto"
    timeout_ms = int(arguments.get("timeout_ms") or 120_000)
    timeout_ms = max(5_000, min(timeout_ms, 300_000))

    if mode == "hitl":
        return redact_browser_payload(await _solve_hitl(timeout_ms=timeout_ms))

    _lease, session = await lease_page(arguments)

    # Optional overrides from agent
    detected: dict[str, Any]
    if arguments.get("kind") or arguments.get("sitekey"):
        detected = {
            "present": True,
            "kind": arguments.get("kind"),
            "sitekey": arguments.get("sitekey"),
            "action": arguments.get("action"),
            "url": session.page.url,
            "bbox": arguments.get("bbox"),
            "confidence": 1.0,
            "candidates": [],
        }
    else:
        detected = await _detect_on_session(session)

    if not detected.get("present") and mode == "auto":
        # Nothing found — escalate to HITL so user can inspect
        hitl = await _solve_hitl(timeout_ms=timeout_ms)
        hitl["detect"] = detected
        hitl["reason"] = "no_captcha_detected"
        return redact_browser_payload(hitl)

    kind = detected.get("kind")
    if mode == "auto":
        preferred = classify_solve_backend(kind)
        settings = get_settings()
        if preferred == "ocr" and settings.captcha_ocr_enabled:
            mode = "ocr"
        elif preferred == "token" and (settings.capsolver_api_key or "").strip():
            mode = "token"
        else:
            mode = "hitl"

    try:
        if mode == "ocr":
            result = await _solve_ocr(session, detected)
        elif mode == "token":
            result = await _solve_token(session, detected, timeout_ms=timeout_ms)
        else:
            result = await _solve_hitl(timeout_ms=timeout_ms)
    except (CaptchaOcrMissingError, CaptchaTokenNotConfiguredError) as exc:
        # Soft fallback to HITL when auto path lacks backend
        if str(arguments.get("mode") or "auto").lower().strip() == "auto":
            hitl = await _solve_hitl(timeout_ms=timeout_ms)
            hitl["fallback_from"] = mode
            hitl["fallback_reason"] = exc.agent_code
            hitl["detect"] = {
                "kind": kind,
                "present": detected.get("present"),
                "confidence": detected.get("confidence"),
            }
            return redact_browser_payload(hitl)
        raise

    result["detect"] = {
        "kind": kind,
        "present": detected.get("present"),
        "confidence": detected.get("confidence"),
        "sitekey_present": bool(detected.get("sitekey")),
    }
    return redact_browser_payload(result)


BROWSER_CAPTCHA_DETECT = ToolSpec(
    name="browser.captcha.detect",
    description=(
        "Detect captcha widgets on the current page (Turnstile, reCAPTCHA, hCaptcha, "
        "image, slider). Returns kind, sitekey presence, bbox, and preferred solve backend."
    ),
    parameters={
        "type": "object",
        "properties": {**SESSION_HANDLE_PROP},
        "required": [],
    },
    handler=_detect_handler,
    tags=("browser", "web", "auth"),
    cache_ttl_seconds=None,
    rate_limit=(30, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.captcha.detect"),
    checker_enabled=False,
    examples=("detect captcha", "is there a captcha", "cloudflare turnstile"),
)

BROWSER_CAPTCHA_SOLVE = ToolSpec(
    name="browser.captcha.solve",
    description=(
        "Solve a captcha on the current page. mode=auto picks OCR (ddddocr) for image/slider, "
        "CapSolver token for Turnstile/reCAPTCHA/hCaptcha, else HITL Telegram viewer. "
        "Never use for Google account challenges — prefer cookie seed."
    ),
    parameters={
        "type": "object",
        "properties": {
            **SESSION_HANDLE_PROP,
            "mode": {
                "type": "string",
                "enum": ["auto", "ocr", "token", "hitl"],
                "default": "auto",
                "description": "auto (default), ocr, token (CapSolver), or hitl (Telegram viewer).",
            },
            "kind": {
                "type": "string",
                "enum": [
                    "turnstile",
                    "recaptcha_v2",
                    "recaptcha_v3",
                    "hcaptcha",
                    "image",
                    "slider",
                ],
                "description": "Optional override from a prior detect.",
            },
            "sitekey": {
                "type": "string",
                "description": "Optional sitekey override for token solvers.",
            },
            "action": {
                "type": "string",
                "description": "Optional action / pageAction for Turnstile or reCAPTCHA v3.",
            },
            "timeout_ms": {
                "type": "integer",
                "description": "Solver timeout (default 120000).",
                "default": 120_000,
            },
        },
        "required": [],
    },
    handler=_solve_handler,
    tags=("browser", "web", "auth"),
    cache_ttl_seconds=None,
    rate_limit=(10, 60),
    parallel_safe=False,
    handler_timeout_seconds=handler_timeout_for_browser_tool("browser.captcha.solve"),
    checker_enabled=False,
    examples=("solve captcha", "bypass turnstile", "ocr captcha", "hitl captcha"),
)

BROWSER_CAPTCHA_TOOLS: tuple[ToolSpec, ...] = (
    BROWSER_CAPTCHA_DETECT,
    BROWSER_CAPTCHA_SOLVE,
)
