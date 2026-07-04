from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from agent.run_trace import RunTrace
from agent.supervisor_prompt import SUPERVISOR_SYSTEM_PROMPT
from config import Settings
from llm import LLMClient

logger = logging.getLogger(__name__)

VALID_DECISIONS = frozenset({"CONTINUE", "STOP_GRACEFUL", "STOP_RETRY"})


@dataclass
class SupervisorDecision:
    decision: str
    confidence: float = 0.0
    reasoning: str = ""
    remaining_steps: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    do_not: list[str] = field(default_factory=list)
    bonus_turns: int | None = None
    user_reply_brief: str = ""


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def parse_supervisor_response(text: str, *, default_bonus_turns: int) -> SupervisorDecision:
    raw = _strip_json_fence(text)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid supervisor JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("supervisor response must be a JSON object")

    decision = str(payload.get("decision", "")).strip().upper()
    if decision not in VALID_DECISIONS:
        raise ValueError(f"unknown supervisor decision: {decision!r}")

    bonus_raw = payload.get("bonus_turns")
    bonus_turns = default_bonus_turns
    if bonus_raw is not None:
        try:
            bonus_turns = max(1, int(bonus_raw))
        except (TypeError, ValueError):
            bonus_turns = default_bonus_turns

    confidence = payload.get("confidence", 0.0)
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.0

    return SupervisorDecision(
        decision=decision,
        confidence=confidence_value,
        reasoning=str(payload.get("reasoning", "")).strip(),
        remaining_steps=_as_string_list(payload.get("remaining_steps")),
        hints=_as_string_list(payload.get("hints")),
        do_not=_as_string_list(payload.get("do_not")),
        bonus_turns=bonus_turns if decision in {"CONTINUE", "STOP_RETRY"} else None,
        user_reply_brief=str(payload.get("user_reply_brief", "")).strip(),
    )


def fallback_stop_decision(*, reason: str) -> SupervisorDecision:
    return SupervisorDecision(
        decision="STOP_GRACEFUL",
        reasoning=reason,
        user_reply_brief=(
            "Explain what was accomplished so far, what could not be completed, "
            "and give clear manual next steps if needed."
        ),
    )


def format_supervisor_coaching(decision: SupervisorDecision, bonus_turns: int) -> str:
    lines = [
        "Supervisor review (continue):",
        "",
        "Remaining steps:",
    ]
    if decision.remaining_steps:
        lines.extend(f"{index + 1}. {step}" for index, step in enumerate(decision.remaining_steps))
    else:
        lines.append("1. Finish the user's request with use_tool only.")

    if decision.hints:
        lines.extend(["", "Hints:", *[f"- {hint}" for hint in decision.hints]])

    if decision.do_not:
        lines.extend(["", "Do not:", *[f"- {item}" for item in decision.do_not]])

    lines.extend(
        [
            "",
            f"Continue with use_tool only. You have {bonus_turns} more turns.",
        ]
    )
    return "\n".join(lines)


def format_supervisor_retry(decision: SupervisorDecision, bonus_turns: int) -> str:
    lines = [
        "Supervisor review (retry with revised plan):",
        "",
        "The current approach is not working. Follow this revised plan:",
    ]
    if decision.remaining_steps:
        lines.extend(f"{index + 1}. {step}" for index, step in enumerate(decision.remaining_steps))
    else:
        lines.append("1. Re-read the user goal and finish with a simpler tool sequence.")

    if decision.hints:
        lines.extend(["", "Hints:", *[f"- {hint}" for hint in decision.hints]])

    if decision.do_not:
        lines.extend(["", "Do not:", *[f"- {item}" for item in decision.do_not]])

    lines.extend(
        [
            "",
            f"Start the revised plan now. You have {bonus_turns} more turns.",
        ]
    )
    return "\n".join(lines)


def format_supervisor_stop(decision: SupervisorDecision) -> str:
    brief = decision.user_reply_brief or (
        "Summarize what was done, what was not completed, and any manual steps."
    )
    return (
        "Supervisor review (stop):\n\n"
        "Reply to the user without calling any more tools.\n\n"
        "Include:\n"
        "- What you already accomplished\n"
        "- What you could not complete\n"
        "- Exact manual steps if needed\n\n"
        "Do NOT mention tool limits, supervisor, or internal stop instructions.\n\n"
        f"Brief from supervisor: {brief}"
    )


class AgentSupervisor:
    def __init__(self, llm: LLMClient, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    async def review(
        self,
        trace: RunTrace,
        *,
        trigger: str = "cap_hit",
        trigger_detail: str = "",
    ) -> SupervisorDecision:
        trace_text = trace.to_supervisor_text(
            max_chars=self._settings.agent_supervisor_trace_max_chars
        )
        trigger_line = f"Trigger: {trigger}"
        if trigger_detail:
            trigger_line = f"{trigger_line} — {trigger_detail}"

        messages = [
            {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Review this agent run and decide CONTINUE, STOP_GRACEFUL, or STOP_RETRY.\n"
                    f"{trigger_line}\n\n"
                    f"{trace_text}"
                ),
            },
        ]
        raw = await self._llm.chat(messages)
        try:
            decision = parse_supervisor_response(
                raw,
                default_bonus_turns=self._settings.agent_supervisor_bonus_turns,
            )
        except ValueError as exc:
            logger.warning("Supervisor parse failed, fallback STOP_GRACEFUL: %s", exc)
            return fallback_stop_decision(reason=str(exc))

        logger.info(
            "supervisor_decision decision=%s trigger=%s confidence=%s bonus_turns=%s",
            decision.decision,
            trigger,
            decision.confidence,
            decision.bonus_turns,
        )
        if decision.hints:
            logger.info("supervisor_hints hints=%s", decision.hints)
        if decision.remaining_steps:
            logger.info("supervisor_remaining_steps steps=%s", decision.remaining_steps)
        return decision
