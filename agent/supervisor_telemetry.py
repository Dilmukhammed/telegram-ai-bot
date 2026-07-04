from __future__ import annotations

import logging
from collections import Counter, deque
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupervisorRecord:
    user_id: int | None
    trigger: str
    decision: str
    bonus_turns: int | None = None


class SupervisorTelemetry:
    def __init__(self, history_size: int = 100) -> None:
        self._history: deque[SupervisorRecord] = deque(maxlen=history_size)

    def record(
        self,
        *,
        user_id: int | None,
        trigger: str,
        decision: str,
        bonus_turns: int | None = None,
    ) -> None:
        entry = SupervisorRecord(
            user_id=user_id,
            trigger=trigger,
            decision=decision,
            bonus_turns=bonus_turns,
        )
        self._history.append(entry)
        logger.info("supervisor_telemetry %s", asdict(entry))

    def summary(self) -> dict[str, Any]:
        total = len(self._history)
        if total == 0:
            return {"total": 0}

        by_decision: Counter[str] = Counter()
        by_trigger: Counter[str] = Counter()
        for item in self._history:
            by_decision[item.decision] += 1
            by_trigger[item.trigger] += 1

        return {
            "total": total,
            "by_decision": dict(by_decision),
            "by_trigger": dict(by_trigger),
        }

    def recent(self, limit: int = 5) -> list[SupervisorRecord]:
        return list(self._history)[-limit:]

    def format_report(self, recent_limit: int = 5) -> str:
        summary = self.summary()
        if summary["total"] == 0:
            return "**Supervisor stats**\n\nПока нет вызовов supervisor."

        decision_lines = "\n".join(
            f"- `{name}`: {count}" for name, count in sorted(summary["by_decision"].items())
        )
        trigger_lines = "\n".join(
            f"- `{name}`: {count}" for name, count in sorted(summary["by_trigger"].items())
        )
        recent = self.recent(recent_limit)
        recent_lines = "\n".join(
            f"- `{item.trigger}` → `{item.decision}`"
            + (f" (+{item.bonus_turns} turns)" if item.bonus_turns else "")
            for item in recent
        )

        return (
            "**Supervisor stats**\n\n"
            f"- Total reviews: **{summary['total']}**\n\n"
            "**By decision**\n"
            f"{decision_lines}\n\n"
            "**By trigger**\n"
            f"{trigger_lines}\n\n"
            f"**Last {len(recent)} reviews**\n"
            f"{recent_lines}"
        )
