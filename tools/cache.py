import hashlib
import json
import time
from typing import Any


def cache_key(tool_name: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(f"{tool_name}:{payload}".encode("utf-8")).hexdigest()
    return digest


class ToolResultCache:
    def __init__(self, max_ttl_seconds: int) -> None:
        self._max_ttl_seconds = max_ttl_seconds
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        self._purge_expired()
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= time.monotonic():
            self._entries.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        ttl = min(max(int(ttl_seconds), 0), self._max_ttl_seconds)
        if ttl <= 0:
            return
        self._entries[key] = (time.monotonic() + ttl, value)
        self._purge_expired()

    def clear(self) -> None:
        self._entries.clear()

    def size(self) -> int:
        self._purge_expired()
        return len(self._entries)

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [key for key, (expires_at, _) in self._entries.items() if expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)
