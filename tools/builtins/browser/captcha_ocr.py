"""Optional ddddocr backend for image / slider captchas."""

from __future__ import annotations

import logging
from typing import Any

from tools.builtins.browser.errors import BrowserError

logger = logging.getLogger(__name__)

_ocr = None
_slide = None
_import_error: str | None = None


class CaptchaOcrMissingError(BrowserError):
    code = "ocr_backend_missing"


class CaptchaOcrError(BrowserError):
    code = "ocr_failed"


def ocr_available() -> bool:
    try:
        _ensure_ocr()
        return True
    except CaptchaOcrMissingError:
        return False


def _ensure_ocr() -> Any:
    global _ocr, _import_error
    if _ocr is not None:
        return _ocr
    if _import_error is not None:
        raise CaptchaOcrMissingError(
            f"ddddocr not available: {_import_error}. Install with: pip install ddddocr"
        )
    try:
        import ddddocr  # type: ignore

        _ocr = ddddocr.DdddOcr(show_ad=False)
        return _ocr
    except Exception as exc:  # ImportError or onnx issues
        _import_error = str(exc)
        logger.warning("ddddocr import failed: %s", exc)
        raise CaptchaOcrMissingError(
            f"ddddocr not available: {exc}. Install with: pip install ddddocr"
        ) from exc


def _ensure_slide() -> Any:
    global _slide, _import_error
    if _slide is not None:
        return _slide
    try:
        import ddddocr  # type: ignore

        _slide = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
        return _slide
    except Exception as exc:
        _import_error = str(exc)
        raise CaptchaOcrMissingError(
            f"ddddocr not available: {exc}. Install with: pip install ddddocr"
        ) from exc


def recognize_text(image_bytes: bytes) -> str:
    if not image_bytes:
        raise CaptchaOcrError("empty captcha image")
    ocr = _ensure_ocr()
    try:
        text = ocr.classification(image_bytes)
    except Exception as exc:
        raise CaptchaOcrError(f"OCR failed: {exc}") from exc
    text = (text or "").strip()
    if not text:
        raise CaptchaOcrError("OCR returned empty text")
    return text


def slide_gap_distance(*, target_bytes: bytes, background_bytes: bytes) -> int:
    """Return horizontal pixel offset for slider gap (ddddocr slide_match)."""
    if not target_bytes or not background_bytes:
        raise CaptchaOcrError("slider images required")
    slide = _ensure_slide()
    try:
        result = slide.slide_match(target_bytes, background_bytes, simple_target=True)
    except Exception as exc:
        raise CaptchaOcrError(f"slide_match failed: {exc}") from exc
    if isinstance(result, dict):
        # ddddocr returns {"target": [x1,y1,x2,y2]} or {"target_x": n}
        if "target_x" in result:
            return int(result["target_x"])
        target = result.get("target")
        if isinstance(target, (list, tuple)) and target:
            return int(target[0])
    raise CaptchaOcrError(f"unexpected slide_match result: {result!r}")
