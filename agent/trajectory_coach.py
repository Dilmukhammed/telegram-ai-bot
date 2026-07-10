from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from agent.coach_trace import build_coach_trace
from agent.meta_reviewer import MetaReviewer, Messages
from agent.run_trace import RunTrace
from agent.trajectory_coach_prompt import build_coach_system_prompt
from agent.verdict_json import as_string_list as _as_string_list
from agent.verdict_json import extract_json_payload as _extract_json_payload

logger = logging.getLogger(__name__)

COLLAPSE_RISK_LEVELS = frozenset({"low", "medium", "high"})


@dataclass
class CoachDecision:
    intervene: bool = False
    on_track: bool = True
    confidence: float = 0.0
    assessment: str = ""
    strategy: str = ""
    warnings: list[str] = field(default_factory=list)
    focus_now: str = ""
    do_not: list[str] = field(default_factory=list)
    collapse_risk: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "intervene": self.intervene,
            "on_track": self.on_track,
            "confidence": self.confidence,
            "assessment": self.assessment,
            "strategy": self.strategy,
            "warnings": self.warnings,
            "focus_now": self.focus_now,
            "do_not": self.do_not,
            "collapse_risk": self.collapse_risk,
        }

    def should_inject_hint(self) -> bool:
        if not self.intervene:
            return False
        return bool(
            self.assessment
            or self.strategy
            or self.focus_now
            or self.warnings
            or self.do_not
        )


def parse_coach_response(text: str) -> CoachDecision:
    raw = _extract_json_payload(text)
    if not raw:
        raise ValueError("coach response is empty")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("coach response must be a JSON object")

    collapse_risk = str(payload.get("collapse_risk", "low")).strip().lower()
    if collapse_risk not in COLLAPSE_RISK_LEVELS:
        collapse_risk = "low"

    confidence_raw = payload.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0

    return CoachDecision(
        intervene=bool(payload.get("intervene", False)),
        on_track=bool(payload.get("on_track", True)),
        confidence=confidence,
        assessment=str(payload.get("assessment", "")).strip(),
        strategy=str(payload.get("strategy", "")).strip(),
        warnings=_as_string_list(payload.get("warnings")),
        focus_now=str(payload.get("focus_now", "")).strip(),
        do_not=_as_string_list(payload.get("do_not")),
        collapse_risk=collapse_risk,
    )


def format_coach_coaching(decision: CoachDecision) -> str:
    lines = [
        "Trajectory coaching (algorithm + hot data before collapse — not a stop order):",
        "",
    ]
    if decision.assessment:
        lines.extend(["Assessment:", decision.assessment, ""])
    if decision.strategy:
        lines.extend(["Strategy:", decision.strategy, ""])
    if decision.focus_now:
        lines.extend([f"Focus now: {decision.focus_now}", ""])
    if decision.warnings:
        lines.extend(["Warnings:", *[f"- {w}" for w in decision.warnings], ""])
    if decision.do_not:
        lines.extend(["Do not:", *[f"- {item}" for item in decision.do_not], ""])
    if decision.collapse_risk != "low":
        lines.append(f"Collapse risk: {decision.collapse_risk}")
        lines.append("")
    lines.append(
        "If this review misstates your progress, call use_tool coach.reply with "
        '{"message":"..."} before your next action (internal; not shown to user).'
    )
    lines.append("Continue with use_tool only. Do not mention this review to the user.")
    return "\n".join(lines).strip()


def should_run_coach_review(
    *,
    tool_calls_completed: int,
    last_coach_at_tool_count: int,
    every_n: int,
) -> bool:
    if every_n <= 0 or tool_calls_completed <= 0:
        return False
    return tool_calls_completed >= last_coach_at_tool_count + every_n


def format_coach_status(decision: CoachDecision) -> str:
    if not decision.intervene:
        return "Траектория: без вмешательства"
    if decision.on_track:
        status = "Траектория: корректировка"
    else:
        status = "Траектория: сбилась — подсказка"
    if decision.focus_now:
        status = f"{status} · фокус: {decision.focus_now}"
    elif decision.collapse_risk == "high":
        status = f"{status} · риск collapse"
    return status


def _coach_repair(messages: Messages) -> Messages:
    return [
        *messages,
        {
            "role": "user",
            "content": (
                "Your previous JSON was truncated. Reply again with the same schema "
                "(include intervene true/false), but assessment/strategy under 80 chars each, "
                "max 2 warnings."
            ),
        },
    ]


class TrajectoryCoach(MetaReviewer[CoachDecision]):
    name = "trajectory_coach"

    @property
    def enabled(self) -> bool:
        return self._settings.agent_coach_enabled

    async def review(self, trace: RunTrace) -> tuple[CoachDecision, str]:
        coach_text = build_coach_trace(trace, settings=self._settings)
        messages: Messages = [
            {"role": "system", "content": build_coach_system_prompt(self._settings)},
            {"role": "user", "content": coach_text},
        ]
        decision = await self._review(
            messages,
            parse=parse_coach_response,
            fallback=lambda _exc, _raw: CoachDecision(on_track=True, intervene=False),
            max_tokens=self._settings.coach_max_output_tokens,
            repair=_coach_repair,
        )
        logger.info(
            "trajectory_coach intervene=%s on_track=%s risk=%s focus=%s trace_chars=%s",
            decision.intervene,
            decision.on_track,
            decision.collapse_risk,
            decision.focus_now or "-",
            len(coach_text),
        )
        return decision, coach_text

