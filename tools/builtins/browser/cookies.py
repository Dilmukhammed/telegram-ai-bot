from __future__ import annotations

import json
from typing import Any


def _map_same_site(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("_", "-")
    if text in {"", "unspecified", "no_restriction", "none"}:
        return "None"
    if text in {"lax"}:
        return "Lax"
    if text in {"strict"}:
        return "Strict"
    if text in {"no-restriction"}:
        return "None"
    # Already Playwright-ish
    if text in {"none", "lax", "strict"}:
        return text[:1].upper() + text[1:]
    return None


def normalize_cookie(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = raw.get("name")
    value = raw.get("value")
    if not name or value is None:
        return None

    cookie: dict[str, Any] = {
        "name": str(name),
        "value": str(value),
    }

    domain = raw.get("domain")
    url = raw.get("url")
    path = raw.get("path") or "/"
    if domain:
        cookie["domain"] = str(domain)
        cookie["path"] = str(path)
    elif url:
        cookie["url"] = str(url)
    else:
        # Google exports sometimes omit url; refuse rather than guess wrong host.
        return None

    if "httpOnly" in raw or "http_only" in raw:
        cookie["httpOnly"] = bool(raw.get("httpOnly", raw.get("http_only")))
    if "secure" in raw:
        cookie["secure"] = bool(raw.get("secure"))

    expires = raw.get("expires")
    if expires is None:
        expires = raw.get("expirationDate")
    if expires is None:
        expires = raw.get("expiry")
    if expires is not None:
        try:
            exp_f = float(expires)
            # Cookie-Editor sometimes uses ms
            if exp_f > 10_000_000_000:
                exp_f = exp_f / 1000.0
            cookie["expires"] = exp_f
        except (TypeError, ValueError):
            pass

    same_site = _map_same_site(raw.get("sameSite") or raw.get("same_site"))
    if same_site:
        cookie["sameSite"] = same_site
        # Playwright requires secure=True when sameSite=None
        if same_site == "None":
            cookie["secure"] = True

    return cookie


def parse_cookies_payload(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return []
        payload = json.loads(text)

    if isinstance(payload, dict):
        if isinstance(payload.get("cookies"), list):
            payload = payload["cookies"]
        else:
            payload = [payload]

    if not isinstance(payload, list):
        raise ValueError("cookies must be a JSON array or {cookies:[...]}")

    out: list[dict[str, Any]] = []
    skipped = 0
    for item in payload:
        if not isinstance(item, dict):
            skipped += 1
            continue
        normalized = normalize_cookie(item)
        if normalized is None:
            skipped += 1
            continue
        out.append(normalized)
    if not out:
        raise ValueError(
            "No valid cookies parsed (need name, value, and domain or url). "
            f"skipped={skipped}"
        )
    return out


def cookies_summary(cookies: list[dict[str, Any]]) -> dict[str, Any]:
    domains: dict[str, int] = {}
    for cookie in cookies:
        domain = str(cookie.get("domain") or cookie.get("url") or "?")
        domains[domain] = domains.get(domain, 0) + 1
    names = [str(c["name"]) for c in cookies[:40]]
    return {
        "count": len(cookies),
        "domains": domains,
        "names_sample": names,
    }
