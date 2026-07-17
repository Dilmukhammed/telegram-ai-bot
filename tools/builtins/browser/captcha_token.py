"""Token captcha solvers (CapSolver) + inject helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from tools.builtins.browser.errors import BrowserError

logger = logging.getLogger(__name__)

CAPSOLVER_CREATE_URL = "https://api.capsolver.com/createTask"
CAPSOLVER_RESULT_URL = "https://api.capsolver.com/getTaskResult"


class CaptchaTokenError(BrowserError):
    code = "captcha_token_failed"


class CaptchaTokenNotConfiguredError(BrowserError):
    code = "captcha_token_not_configured"


class CaptchaTokenProvider(Protocol):
    async def solve(
        self,
        *,
        kind: str,
        website_url: str,
        website_key: str,
        action: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> str: ...


class CapSolverProvider:
    """CapSolver createTask / getTaskResult client."""

    def __init__(self, api_key: str, *, poll_interval: float = 2.0) -> None:
        self.api_key = api_key
        self.poll_interval = max(0.5, poll_interval)

    def _task_payload(
        self,
        *,
        kind: str,
        website_url: str,
        website_key: str,
        action: str | None,
    ) -> dict[str, Any]:
        kind = kind.lower().strip()
        if kind == "turnstile":
            task: dict[str, Any] = {
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": website_url,
                "websiteKey": website_key,
            }
            if action:
                task["metadata"] = {"action": action}
            return task
        if kind == "hcaptcha":
            return {
                "type": "HCaptchaTaskProxyLess",
                "websiteURL": website_url,
                "websiteKey": website_key,
            }
        if kind == "recaptcha_v3":
            task = {
                "type": "ReCaptchaV3TaskProxyLess",
                "websiteURL": website_url,
                "websiteKey": website_key,
                "pageAction": action or "verify",
            }
            return task
        # default / recaptcha_v2
        return {
            "type": "ReCaptchaV2TaskProxyLess",
            "websiteURL": website_url,
            "websiteKey": website_key,
        }

    async def solve(
        self,
        *,
        kind: str,
        website_url: str,
        website_key: str,
        action: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> str:
        if not self.api_key.strip():
            raise CaptchaTokenNotConfiguredError("CAPSOLVER_API_KEY is empty")

        import urllib.error
        import urllib.request
        import json

        def _post(url: str, body: dict[str, Any]) -> dict[str, Any]:
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                raise CaptchaTokenError(f"CapSolver HTTP {exc.code}: {raw[:300]}") from exc
            except Exception as exc:
                raise CaptchaTokenError(f"CapSolver request failed: {exc}") from exc

        task = self._task_payload(
            kind=kind,
            website_url=website_url,
            website_key=website_key,
            action=action,
        )
        create = await asyncio.to_thread(
            _post,
            CAPSOLVER_CREATE_URL,
            {"clientKey": self.api_key, "task": task},
        )
        if create.get("errorId"):
            raise CaptchaTokenError(
                f"CapSolver createTask error: {create.get('errorDescription') or create}"
            )
        task_id = create.get("taskId")
        # Some responses return solution immediately
        if create.get("status") == "ready" and isinstance(create.get("solution"), dict):
            token = _extract_token(create["solution"])
            if token:
                return token
        if not task_id:
            raise CaptchaTokenError(f"CapSolver createTask missing taskId: {create}")

        import time as _time

        deadline = _time.monotonic() + max(10.0, timeout_seconds)
        while _time.monotonic() < deadline:
            await asyncio.sleep(self.poll_interval)
            result = await asyncio.to_thread(
                _post,
                CAPSOLVER_RESULT_URL,
                {"clientKey": self.api_key, "taskId": task_id},
            )
            if result.get("errorId"):
                raise CaptchaTokenError(
                    f"CapSolver getTaskResult error: {result.get('errorDescription') or result}"
                )
            status = str(result.get("status") or "")
            if status == "ready":
                token = _extract_token(result.get("solution") or {})
                if not token:
                    raise CaptchaTokenError("CapSolver ready but token empty")
                return token
            if status in {"failed", "error"}:
                raise CaptchaTokenError(f"CapSolver task failed: {result}")
        raise CaptchaTokenError("CapSolver solve timed out")


def _extract_token(solution: Any) -> str | None:
    if not isinstance(solution, dict):
        return None
    for key in ("token", "gRecaptchaResponse", "g_recaptcha_response"):
        val = solution.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def get_token_provider() -> CaptchaTokenProvider | None:
    from config import get_settings

    key = (get_settings().capsolver_api_key or "").strip()
    if not key:
        return None
    return CapSolverProvider(key)


# Inject a solved token into the page (no token logged by callers).
# Playwright evaluate takes a single arg — pass {token, kind}.
INJECT_TOKEN_JS = r"""
({token, kind}) => {
  const t = String(token || "");
  if (!t) return { ok: false, reason: "empty_token" };
  const k = String(kind || "").toLowerCase();
  let filled = 0;

  const setValue = (el) => {
    if (!el) return;
    el.value = t;
    el.innerHTML = t;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    filled += 1;
  };

  document.querySelectorAll(
    "textarea[name='g-recaptcha-response'], textarea#g-recaptcha-response, input[name='g-recaptcha-response']"
  ).forEach(setValue);
  document.querySelectorAll(
    "textarea[name='h-captcha-response'], textarea[name='hcaptcha-response'], textarea[name='cf-turnstile-response']"
  ).forEach(setValue);
  document.querySelectorAll("[name='cf-turnstile-response'], input[name='cf-turnstile-response']").forEach(setValue);

  // Turnstile widgets often expose a callback via data-callback
  if (k === "turnstile" || k === "unknown") {
    document.querySelectorAll(".cf-turnstile, [data-sitekey]").forEach((el) => {
      const cbName = el.getAttribute("data-callback");
      if (cbName && typeof window[cbName] === "function") {
        try { window[cbName](t); filled += 1; } catch (_) {}
      }
    });
    if (window.turnstile && typeof window.turnstile.getResponse === "function") {
      // best-effort: some sites listen on hidden input only
    }
  }

  if (k.startsWith("recaptcha") || k === "unknown") {
    document.querySelectorAll(".g-recaptcha, [data-sitekey]").forEach((el) => {
      const cbName = el.getAttribute("data-callback");
      if (cbName && typeof window[cbName] === "function") {
        try { window[cbName](t); filled += 1; } catch (_) {}
      }
    });
    try {
      if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
        // leave clients alone; textarea fill is the main path
      }
    } catch (_) {}
  }

  if (k === "hcaptcha" || k === "unknown") {
    document.querySelectorAll(".h-captcha, [data-sitekey]").forEach((el) => {
      const cbName = el.getAttribute("data-callback");
      if (cbName && typeof window[cbName] === "function") {
        try { window[cbName](t); filled += 1; } catch (_) {}
      }
    });
  }

  return { ok: filled > 0, filled, kind: k };
}
"""
