from __future__ import annotations

import logging
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckerReviewRecord:
    user_id: int | None
    tool_name: str
    overall: str
    rule_based_only: bool


class CheckerTelemetry:
    def __init__(self, history_size: int = 200) -> None:
        self._history: deque[CheckerReviewRecord] = deque(maxlen=history_size)
        self._by_overall: Counter[str] = Counter()
        self._by_tool_overall: dict[str, Counter[str]] = defaultdict(Counter)
        self._skips: Counter[str] = Counter()
        self._skip_by_tool: dict[str, Counter[str]] = defaultdict(Counter)
        self._errors: Counter[str] = Counter()

    def record_review(
        self,
        *,
        user_id: int | None,
        tool_name: str,
        overall: str,
        rule_based_only: bool,
    ) -> None:
        entry = CheckerReviewRecord(
            user_id=user_id,
            tool_name=tool_name,
            overall=overall,
            rule_based_only=rule_based_only,
        )
        self._history.append(entry)
        self._by_overall[overall] += 1
        self._by_tool_overall[tool_name][overall] += 1
        logger.info("checker_telemetry review %s", asdict(entry))

    def record_skip(self, *, tool_name: str, reason: str) -> None:
        self._skips[reason] += 1
        self._skip_by_tool[tool_name][reason] += 1

    def record_error(self, *, tool_name: str) -> None:
        self._errors[tool_name] += 1
        logger.warning("checker_telemetry error tool=%s", tool_name)

    def summary(self) -> dict[str, Any]:
        total_reviews = len(self._history)
        if total_reviews == 0 and not self._skips and not self._errors:
            return {"total_reviews": 0}

        tool_rates: list[dict[str, Any]] = []
        for tool_name, counts in sorted(
            self._by_tool_overall.items(),
            key=lambda item: (-sum(item[1].values()), item[0]),
        ):
            tool_total = sum(counts.values())
            if tool_total == 0:
                continue
            passed = counts.get("pass", 0)
            failed = counts.get("fail", 0)
            tool_rates.append(
                {
                    "tool_name": tool_name,
                    "total": tool_total,
                    "pass": passed,
                    "fail": failed,
                    "warn": counts.get("warn", 0),
                    "unknown": counts.get("unknown", 0),
                    "pass_rate": round(passed / tool_total * 100, 1),
                    "fail_rate": round(failed / tool_total * 100, 1),
                }
            )

        return {
            "total_reviews": total_reviews,
            "by_overall": dict(self._by_overall),
            "skips": dict(self._skips),
            "errors": dict(self._errors),
            "by_tool": tool_rates,
        }

    def recent(self, limit: int = 5) -> list[CheckerReviewRecord]:
        return list(self._history)[-limit:]

    def format_report(self, recent_limit: int = 5) -> str:
        summary = self.summary()
        if summary.get("total_reviews", 0) == 0 and not summary.get("skips") and not summary.get("errors"):
            return "**Checker stats**\n\nПока нет tool checker reviews."

        lines = [
            "**Checker stats**",
            "",
            f"- Reviews: **{summary.get('total_reviews', 0)}**",
        ]
        if summary.get("by_overall"):
            overall_lines = ", ".join(
                f"`{name}` {count}"
                for name, count in sorted(summary["by_overall"].items())
            )
            lines.append(f"- Overall: {overall_lines}")

        if summary.get("skips"):
            skip_lines = ", ".join(
                f"`{name}` {count}" for name, count in sorted(summary["skips"].items())
            )
            lines.append(f"- Skipped: {skip_lines}")

        if summary.get("errors"):
            error_total = sum(summary["errors"].values())
            lines.append(f"- Errors: **{error_total}**")

        by_tool = summary.get("by_tool") or []
        if by_tool:
            lines.extend(["", "**Pass/fail by tool** (top 10)"])
            for item in by_tool[:10]:
                lines.append(
                    f"- `{item['tool_name']}`: {item['total']} reviews — "
                    f"pass {item['pass_rate']}% / fail {item['fail_rate']}% "
                    f"({item['pass']}✓ {item['fail']}✗ {item['warn']}⚠ {item['unknown']}?)"
                )

        recent = self.recent(recent_limit)
        if recent:
            lines.extend(["", f"**Last {len(recent)} reviews**"])
            for item in recent:
                suffix = " (rules)" if item.rule_based_only else ""
                lines.append(
                    f"- `{item.tool_name}` → `{item.overall}`{suffix}"
                )

        return "\n".join(lines)
