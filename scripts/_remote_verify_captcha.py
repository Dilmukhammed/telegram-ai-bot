#!/usr/bin/env python3
import ddddocr  # noqa: F401
from tools.builtins.browser import BROWSER_TOOLS
from config import get_settings

s = get_settings()
print("ddddocr_ok")
print("tools", len(BROWSER_TOOLS))
print("captcha", [t.name for t in BROWSER_TOOLS if "captcha" in t.name])
print("ocr_enabled", s.captcha_ocr_enabled)
print("capsolver_set", bool((s.capsolver_api_key or "").strip()))
print("timeout", s.captcha_solver_timeout_seconds)
