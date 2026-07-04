import logging
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger("tools.telemetry")


@dataclass(frozen=True)
class ToolCallRecord:
    tool_name: str
    meta_tool: str
    user_id: int | None
    turn: int
    duration_ms: int
    ok: bool
    cached: bool
    rate_limited: bool
    error: str | None = None


class ToolTelemetry:
    def __init__(self, history_size: int = 200) -> None:
        self._history: deque[ToolCallRecord] = deque(maxlen=history_size)

    def record(self, entry: ToolCallRecord) -> None:
        self._history.append(entry)
        logger.info("tool_call %s", asdict(entry))

    def recent(self, limit: int = 20) -> list[ToolCallRecord]:
        return list(self._history)[-limit:]

    def summary(self) -> dict[str, Any]:
        total = len(self._history)
        if total == 0:
            return {"total": 0}

        ok = sum(1 for item in self._history if item.ok)
        cached = sum(1 for item in self._history if item.cached)
        rate_limited = sum(1 for item in self._history if item.rate_limited)
        by_tool: dict[str, int] = {}
        for item in self._history:
            by_tool[item.tool_name] = by_tool.get(item.tool_name, 0) + 1

        return {
            "total": total,
            "ok": ok,
            "cached": cached,
            "rate_limited": rate_limited,
            "avg_duration_ms": int(sum(item.duration_ms for item in self._history) / total),
            "by_tool": by_tool,
        }

    def format_report(self, *, cache_entries: int = 0, recent_limit: int = 5) -> str:
        summary = self.summary()
        if summary["total"] == 0:
            return (
                "**Tool stats**\n\n"
                "Пока нет вызовов инструментов с момента запуска бота.\n"
                f"Cache entries: {cache_entries}"
            )

        by_tool_lines = "\n".join(
            f"- `{name}`: {count}" for name, count in sorted(summary["by_tool"].items())
        )
        recent = self.recent(recent_limit)
        recent_lines = "\n".join(
            (
                f"- `{item.tool_name}` "
                f"{'ok' if item.ok else 'fail'}"
                f"{' cache' if item.cached else ''}"
                f"{' rate' if item.rate_limited else ''}"
                f" — {item.duration_ms}ms"
                + (f" — {item.error}" if item.error else "")
            )
            for item in recent
        )

        return (
            "**Tool stats**\n\n"
            f"- Total calls: **{summary['total']}**\n"
            f"- OK: **{summary['ok']}**\n"
            f"- Cache hits: **{summary['cached']}**\n"
            f"- Rate limited: **{summary['rate_limited']}**\n"
            f"- Avg latency: **{summary['avg_duration_ms']} ms**\n"
            f"- Cache entries: **{cache_entries}**\n\n"
            "**By tool**\n"
            f"{by_tool_lines}\n\n"
            f"**Last {len(recent)} calls**\n"
            f"{recent_lines}"
        )


class ToolCallTimer:
    def __init__(self) -> None:
        self._started_at = time.perf_counter()

    @property
    def duration_ms(self) -> int:
        return int((time.perf_counter() - self._started_at) * 1000)
