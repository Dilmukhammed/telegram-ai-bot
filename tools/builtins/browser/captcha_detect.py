"""DOM heuristics for common captcha widgets (no Steel dependency)."""

from __future__ import annotations

from typing import Any

# Runs in-page via Playwright evaluate. Returns a plain JSON object.
DETECT_JS = r"""
() => {
  const out = {
    present: false,
    kind: null,
    sitekey: null,
    action: null,
    iframe_url: null,
    selector: null,
    bbox: null,
    confidence: 0,
    candidates: [],
  };

  const push = (c) => {
    out.candidates.push(c);
    if (!out.present || (c.confidence || 0) > (out.confidence || 0)) {
      out.present = true;
      out.kind = c.kind;
      out.sitekey = c.sitekey || null;
      out.action = c.action || null;
      out.iframe_url = c.iframe_url || null;
      out.selector = c.selector || null;
      out.bbox = c.bbox || null;
      out.confidence = c.confidence || 0;
    }
  };

  const boxOf = (el) => {
    try {
      const r = el.getBoundingClientRect();
      if (!r || (r.width < 2 && r.height < 2)) return null;
      return {
        x: Math.round(r.x),
        y: Math.round(r.y),
        width: Math.round(r.width),
        height: Math.round(r.height),
      };
    } catch (_) {
      return null;
    }
  };

  const attr = (el, name) => {
    try {
      return el.getAttribute(name);
    } catch (_) {
      return null;
    }
  };

  // Turnstile
  document.querySelectorAll(
    ".cf-turnstile, [data-sitekey][class*='turnstile'], iframe[src*='challenges.cloudflare.com'], iframe[src*='turnstile']"
  ).forEach((el) => {
    const tag = (el.tagName || "").toLowerCase();
    let sitekey = attr(el, "data-sitekey");
    let action = attr(el, "data-action");
    let iframe_url = null;
    let selector = null;
    if (tag === "iframe") {
      iframe_url = el.src || null;
      selector = "iframe[src*='challenges.cloudflare.com'], iframe[src*='turnstile']";
      const parent = el.closest("[data-sitekey], .cf-turnstile");
      if (parent) {
        sitekey = sitekey || attr(parent, "data-sitekey");
        action = action || attr(parent, "data-action");
      }
    } else {
      selector = ".cf-turnstile, [data-sitekey]";
    }
    push({
      kind: "turnstile",
      sitekey,
      action,
      iframe_url,
      selector,
      bbox: boxOf(el),
      confidence: sitekey ? 0.95 : 0.75,
    });
  });

  // reCAPTCHA
  document.querySelectorAll(
    ".g-recaptcha, [data-sitekey].g-recaptcha, iframe[src*='recaptcha'], iframe[src*='google.com/recaptcha']"
  ).forEach((el) => {
    const tag = (el.tagName || "").toLowerCase();
    let sitekey = attr(el, "data-sitekey");
    let action = attr(el, "data-action") || attr(el, "data-size");
    let iframe_url = null;
    let kind = "recaptcha_v2";
    if (tag === "iframe") {
      iframe_url = el.src || null;
      if ((iframe_url || "").includes("enterprise")) kind = "recaptcha_v2";
      const parent = el.closest(".g-recaptcha, [data-sitekey]");
      if (parent) {
        sitekey = sitekey || attr(parent, "data-sitekey");
        action = action || attr(parent, "data-action");
        if ((attr(parent, "data-size") || "") === "invisible") kind = "recaptcha_v2";
      }
    }
    // v3 heuristic: grecaptcha.execute / badge only
    if (!sitekey && window.grecaptcha && typeof window.___grecaptcha_cfg !== "undefined") {
      kind = "recaptcha_v3";
    }
    push({
      kind,
      sitekey,
      action,
      iframe_url,
      selector: ".g-recaptcha, iframe[src*='recaptcha']",
      bbox: boxOf(el),
      confidence: sitekey ? 0.9 : 0.65,
    });
  });

  // Explicit v3 sitekey on scripts / badges
  document.querySelectorAll("[data-sitekey]").forEach((el) => {
    const sk = attr(el, "data-sitekey") || "";
    const cls = (el.className || "") + " " + (el.id || "");
    if (!sk) return;
    if (cls.includes("turnstile") || cls.includes("cf-")) return;
    if (cls.includes("h-captcha") || cls.includes("hcaptcha")) return;
    if (cls.includes("g-recaptcha") || cls.includes("recaptcha")) return;
    // bare data-sitekey often recaptcha
    if (sk.startsWith("6L")) {
      push({
        kind: "recaptcha_v2",
        sitekey: sk,
        action: attr(el, "data-action"),
        iframe_url: null,
        selector: `[data-sitekey="${sk}"]`,
        bbox: boxOf(el),
        confidence: 0.7,
      });
    }
    if (sk.startsWith("0x")) {
      push({
        kind: "turnstile",
        sitekey: sk,
        action: attr(el, "data-action"),
        iframe_url: null,
        selector: `[data-sitekey="${sk}"]`,
        bbox: boxOf(el),
        confidence: 0.8,
      });
    }
  });

  // hCaptcha
  document.querySelectorAll(
    ".h-captcha, [data-sitekey].h-captcha, iframe[src*='hcaptcha.com']"
  ).forEach((el) => {
    const tag = (el.tagName || "").toLowerCase();
    let sitekey = attr(el, "data-sitekey");
    let iframe_url = null;
    if (tag === "iframe") {
      iframe_url = el.src || null;
      const parent = el.closest(".h-captcha, [data-sitekey]");
      if (parent) sitekey = sitekey || attr(parent, "data-sitekey");
    }
    push({
      kind: "hcaptcha",
      sitekey,
      action: attr(el, "data-action"),
      iframe_url,
      selector: ".h-captcha, iframe[src*='hcaptcha.com']",
      bbox: boxOf(el),
      confidence: sitekey ? 0.9 : 0.7,
    });
  });

  // Slider / Geetest-like
  const sliderRoots = document.querySelectorAll(
    ".geetest_panel, .geetest_holder, .geetest_widget, [class*='slide-verify'], [class*='slider-captcha'], [class*='captcha-slider'], #captcha-box .slider"
  );
  sliderRoots.forEach((el) => {
    push({
      kind: "slider",
      sitekey: null,
      action: null,
      iframe_url: null,
      selector: null,
      bbox: boxOf(el),
      confidence: 0.55,
    });
  });

  // Image captcha: captcha img near input
  const imgs = Array.from(
    document.querySelectorAll(
      "img[src*='captcha'], img[id*='captcha'], img[class*='captcha'], img[alt*='captcha' i], canvas[id*='captcha'], canvas[class*='captcha']"
    )
  ).slice(0, 8);
  imgs.forEach((el) => {
    push({
      kind: "image",
      sitekey: null,
      action: null,
      iframe_url: null,
      selector: null,
      bbox: boxOf(el),
      confidence: 0.5,
      image_src: el.tagName && el.tagName.toLowerCase() === "img" ? (el.currentSrc || el.src || null) : null,
    });
  });

  // Cloudflare interstitial page text
  const bodyText = (document.body && (document.body.innerText || "")) || "";
  if (
    /checking your browser|just a moment|cf-browser-verification|challenge-platform/i.test(
      bodyText + " " + (document.documentElement?.innerHTML || "").slice(0, 2000)
    )
  ) {
    if (!out.present) {
      push({
        kind: "turnstile",
        sitekey: null,
        action: null,
        iframe_url: null,
        selector: null,
        bbox: null,
        confidence: 0.4,
      });
    }
  }

  out.url = location.href;
  out.title = document.title || "";
  return out;
}
"""


def normalize_detect_result(raw: Any, *, page_url: str | None = None) -> dict[str, Any]:
    """Normalize evaluate output into a stable tool payload."""
    if not isinstance(raw, dict):
        return {
            "present": False,
            "kind": None,
            "sitekey": None,
            "action": None,
            "iframe_url": None,
            "selector": None,
            "bbox": None,
            "confidence": 0.0,
            "candidates": [],
            "url": page_url,
        }

    kind = raw.get("kind")
    if kind is not None:
        kind = str(kind).strip().lower() or None
    allowed = {
        "turnstile",
        "recaptcha_v2",
        "recaptcha_v3",
        "hcaptcha",
        "image",
        "slider",
        "unknown",
    }
    if kind and kind not in allowed:
        kind = "unknown"

    candidates: list[dict[str, Any]] = []
    for item in raw.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        ck = item.get("kind")
        ck_s = str(ck).strip().lower() if ck is not None else None
        if ck_s and ck_s not in allowed:
            ck_s = "unknown"
        candidates.append(
            {
                "kind": ck_s,
                "sitekey": item.get("sitekey"),
                "action": item.get("action"),
                "iframe_url": item.get("iframe_url"),
                "selector": item.get("selector"),
                "bbox": item.get("bbox"),
                "confidence": float(item.get("confidence") or 0),
                "image_src": item.get("image_src"),
            }
        )
        if len(candidates) >= 12:
            break

    present = bool(raw.get("present")) and kind is not None
    return {
        "present": present,
        "kind": kind if present else None,
        "sitekey": raw.get("sitekey") if present else None,
        "action": raw.get("action") if present else None,
        "iframe_url": raw.get("iframe_url") if present else None,
        "selector": raw.get("selector") if present else None,
        "bbox": raw.get("bbox") if present else None,
        "confidence": float(raw.get("confidence") or 0) if present else 0.0,
        "candidates": candidates,
        "url": raw.get("url") or page_url,
        "title": raw.get("title"),
    }


def classify_solve_backend(kind: str | None) -> str:
    """Return preferred solve backend: ocr | token | hitl."""
    if kind in {"image", "slider"}:
        return "ocr"
    if kind in {"turnstile", "recaptcha_v2", "recaptcha_v3", "hcaptcha"}:
        return "token"
    return "hitl"
