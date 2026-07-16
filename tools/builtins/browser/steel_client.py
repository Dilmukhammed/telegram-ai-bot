from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

from config import get_settings, steel_configured
from tools.builtins.browser.errors import (
    BrowserNotConfiguredError,
    BrowserSessionLimitError,
    BrowserSteelRateLimitError,
)

logger = logging.getLogger(__name__)


class _TokenBucket:
    def __init__(self, rate_per_minute: int) -> None:
        self._rate = max(1, rate_per_minute)
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            window = 60.0
            while self._timestamps and now - self._timestamps[0] >= window:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._rate:
                retry_after = window - (now - self._timestamps[0])
                raise BrowserSteelRateLimitError(
                    f"Steel API rate limit ({self._rate}/min); retry in {retry_after:.1f}s"
                )
            self._timestamps.append(now)


class SteelClientFacade:
    """Thin wrapper around AsyncSteel with concurrency + RPM guards."""

    def __init__(self, sdk: Any, *, max_concurrent: int, rpm: int) -> None:
        self._sdk = sdk
        self._slots_held = 0
        self._slots_lock = asyncio.Lock()
        self._bucket = _TokenBucket(rpm)
        self._max_concurrent = max(1, max_concurrent)

    @property
    def sdk(self) -> Any:
        return self._sdk

    @property
    def active_slots(self) -> int:
        return self._slots_held

    async def acquire_session_slot(self) -> None:
        async with self._slots_lock:
            if self._slots_held >= self._max_concurrent:
                raise BrowserSessionLimitError(
                    f"Browser session limit reached ({self._max_concurrent} concurrent)"
                )
            self._slots_held += 1

    async def release_session_slot(self) -> None:
        async with self._slots_lock:
            if self._slots_held <= 0:
                return
            self._slots_held -= 1

    async def _throttle(self) -> None:
        await self._bucket.acquire()

    async def create_session(self, **kwargs: Any) -> Any:
        await self._throttle()
        return await self._sdk.sessions.create(**kwargs)

    async def release_session(self, session_id: str) -> Any:
        await self._throttle()
        return await self._sdk.sessions.release(session_id)

    async def retrieve_profile(self, profile_id: str) -> Any:
        """Fetch profile details. Steel SDK uses profiles.get (not retrieve)."""
        await self._throttle()
        profiles = self._sdk.profiles
        if hasattr(profiles, "get"):
            return await profiles.get(profile_id)
        if hasattr(profiles, "retrieve"):
            return await profiles.retrieve(profile_id)
        raise BrowserNotConfiguredError("Steel SDK profiles.get is unavailable")

    async def delete_profile(self, profile_id: str) -> Any:
        await self._throttle()
        profiles = self._sdk.profiles
        if hasattr(profiles, "delete"):
            return await profiles.delete(profile_id)
        # Older/newer SDKs may omit delete — local disconnect still works.
        raise BrowserNotConfiguredError(
            "Steel SDK has no profiles.delete; local profile was/can be cleared without remote delete"
        )

    async def list_sessions(self, **kwargs: Any) -> Any:
        await self._throttle()
        return await self._sdk.sessions.list(**kwargs)


_client: SteelClientFacade | None = None


def reset_steel_client_for_tests() -> None:
    global _client
    _client = None


def get_steel_client() -> SteelClientFacade:
    global _client
    if _client is not None:
        return _client

    if not steel_configured():
        raise BrowserNotConfiguredError("STEEL_API_KEY is not set")

    try:
        from steel import AsyncSteel
    except ModuleNotFoundError as exc:
        raise BrowserNotConfiguredError(
            "The optional steel-sdk package is required for browser tools"
        ) from exc

    settings = get_settings()
    sdk = AsyncSteel(steel_api_key=settings.steel_api_key)
    _client = SteelClientFacade(
        sdk,
        max_concurrent=settings.browser_max_concurrent_sessions,
        rpm=settings.browser_steel_api_rpm,
    )
    return _client


def set_steel_client_for_tests(client: SteelClientFacade | None) -> None:
    global _client
    _client = client
