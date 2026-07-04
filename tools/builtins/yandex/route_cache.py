from __future__ import annotations

from typing import Any


def _cache_key(origin: str, destination: str) -> tuple[str, str]:
    return origin.strip().lower(), destination.strip().lower()


_route_url_cache: dict[tuple[str, str], str] = {}


def cache_yandex_route_url(origin: str, destination: str, url: str) -> None:
    key = _cache_key(origin, destination)
    _route_url_cache[key] = str(url).strip()


def get_cached_yandex_route_url(origin: str, destination: str) -> str | None:
    return _route_url_cache.get(_cache_key(origin, destination))


def clear_yandex_route_cache() -> None:
    _route_url_cache.clear()
