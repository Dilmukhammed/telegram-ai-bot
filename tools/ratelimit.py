import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[tuple[int | None, str], list[float]] = {}

    def check(
        self,
        user_id: int | None,
        bucket: str,
        max_calls: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        if max_calls <= 0 or window_seconds <= 0:
            return RateLimitDecision(allowed=True)

        key = (user_id, bucket)
        now = time.monotonic()
        window_start = now - window_seconds
        timestamps = [ts for ts in self._events.get(key, []) if ts > window_start]

        if len(timestamps) >= max_calls:
            retry_after = max(1, int(window_seconds - (now - timestamps[0])))
            self._events[key] = timestamps
            return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)

        timestamps.append(now)
        self._events[key] = timestamps
        return RateLimitDecision(allowed=True)

    def reset(self) -> None:
        self._events.clear()
