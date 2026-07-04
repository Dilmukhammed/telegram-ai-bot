from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from config import get_settings, google_maps_configured
from tools.builtins.google.errors import GoogleMapsNotConfiguredError
from tools.builtins.google.maps_serialize import compact_geocode_response

logger = logging.getLogger(__name__)

GEOCODING_API_URL = "https://maps.googleapis.com/maps/api/geocode/json"
DEFAULT_TIMEOUT_SECONDS = 20.0
GEOCODE_BATCH_MAX = 10

_client: httpx.AsyncClient | None = None


class GoogleMapsApiError(RuntimeError):
    def __init__(self, message: str, *, status: str | None = None) -> None:
        super().__init__(message)
        self.status = status


def require_maps_configured() -> None:
    if not google_maps_configured():
        raise GoogleMapsNotConfiguredError(
            "Google Maps API is not configured. Set GOOGLE_MAPS_API_KEY."
        )


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)
    return _client


async def close_maps_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _maps_settings() -> tuple[str, str, str]:
    settings = get_settings()
    require_maps_configured()
    assert settings.google_maps_api_key is not None
    return (
        settings.google_maps_api_key,
        settings.google_maps_default_language,
        settings.google_maps_default_region,
    )


def _log_maps_api_call(*, api: str, operation: str, duration_ms: int, ok: bool, error: str | None = None) -> None:
    logger.info(
        "maps_api_call api=%s op=%s duration_ms=%s ok=%s error=%s",
        api,
        operation,
        duration_ms,
        ok,
        error,
    )


def _raise_for_geocode_status(status: str, error_message: str | None) -> None:
    if status == "OK":
        return
    if status in {"ZERO_RESULTS", "NOT_FOUND"}:
        return
    if status == "OVER_QUERY_LIMIT":
        raise GoogleMapsApiError("Google Maps quota exceeded", status=status)
    if status == "REQUEST_DENIED":
        detail = error_message or "request denied"
        raise GoogleMapsApiError(f"Google Maps request denied: {detail}", status=status)
    if status == "INVALID_REQUEST":
        raise GoogleMapsApiError(error_message or "invalid geocode request", status=status)
    raise GoogleMapsApiError(error_message or f"geocode failed: {status}", status=status)


async def _fetch_geocode(
    params: dict[str, str],
    *,
    operation: str,
    query: str,
) -> dict[str, Any]:
    api_key, default_language, default_region = _maps_settings()
    request_params = {
        "key": api_key,
        "language": params.get("language") or default_language,
        "region": params.get("region") or default_region,
        **{key: value for key, value in params.items() if key not in {"language", "region"}},
    }
    url = f"{GEOCODING_API_URL}?{urlencode(request_params)}"

    started = time.perf_counter()
    response = await _get_client().get(url)
    duration_ms = int((time.perf_counter() - started) * 1000)
    response.raise_for_status()
    payload = response.json()

    status = payload.get("status", "UNKNOWN")
    error_message = payload.get("error_message")
    ok = status in {"OK", "ZERO_RESULTS", "NOT_FOUND"}
    _log_maps_api_call(
        api="geocoding",
        operation=operation,
        duration_ms=duration_ms,
        ok=ok,
        error=None if ok else str(error_message or status),
    )
    _raise_for_geocode_status(status, error_message)
    return compact_geocode_response(payload, query=query)


async def geocode(
    address: str,
    *,
    language: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    params: dict[str, str] = {"address": address}
    if language:
        params["language"] = language
    if region:
        params["region"] = region
    return await _fetch_geocode(params, operation="geocode", query=address)


async def reverse_geocode(
    lat: float,
    lng: float,
    *,
    language: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    params: dict[str, str] = {"latlng": f"{lat},{lng}"}
    if language:
        params["language"] = language
    if region:
        params["region"] = region
    query = f"{lat},{lng}"
    return await _fetch_geocode(params, operation="reverse_geocode", query=query)


async def geocode_batch(
    addresses: list[str],
    *,
    language: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    cleaned = [address.strip() for address in addresses if address and str(address).strip()]
    if not cleaned:
        raise ValueError("addresses must contain at least one non-empty entry")
    if len(cleaned) > GEOCODE_BATCH_MAX:
        raise ValueError(f"geocode_batch supports at most {GEOCODE_BATCH_MAX} addresses")

    async def _one(address: str) -> dict[str, Any]:
        return await geocode(address, language=language, region=region)

    items = await asyncio.gather(*[_one(address) for address in cleaned])
    return {
        "count": len(items),
        "results": items,
    }
