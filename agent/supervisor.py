from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from agent.meta_reviewer import MetaReviewer, Messages
from agent.run_cycle_log import CycleLogOptions, build_run_cycle_log
from agent.run_trace import RunTrace
from agent.supervisor_prompt import SUPERVISOR_SYSTEM_PROMPT
from agent.verdict_json import as_string_list as _as_string_list
from agent.verdict_json import extract_json_payload as _extract_json_payload
from config import Settings

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


def parse_supervisor_response(text: str, *, default_bonus_turns: int) -> SupervisorDecision:
    raw = _extract_json_payload(text)
    if not raw:
        raise ValueError("supervisor response is empty")
    payload = json.loads(raw)

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


def _supervisor_trace_text(trace: RunTrace, *, settings: Settings) -> str:
    header_extras: list[str] = [f"Progress: {trace.progress_summary or 'unknown'}"]
    if trace.repeated_patterns:
        header_extras.append(f"Repeated patterns: {'; '.join(trace.repeated_patterns)}")
    options = CycleLogOptions(
        step_limit=240,
        max_chars=max(1000, settings.agent_supervisor_trace_max_chars),
        include_checker_reviews=True,
    )
    return build_run_cycle_log(
        trace, settings=settings, options=options, header_extras=header_extras
    )


class AgentSupervisor(MetaReviewer[SupervisorDecision]):
    name = "supervisor"

    async def review(
        self,
        trace: RunTrace,
        *,
        trigger: str = "cap_hit",
        trigger_detail: str = "",
    ) -> SupervisorDecision:
        trace_text = _supervisor_trace_text(trace, settings=self._settings)
        trigger_line = f"Trigger: {trigger}"
        if trigger_detail:
            trigger_line = f"{trigger_line} — {trigger_detail}"

        messages: Messages = [
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
        decision = await self._review(
            messages,
            parse=lambda raw: parse_supervisor_response(
                raw, default_bonus_turns=self._settings.agent_supervisor_bonus_turns
            ),
            fallback=lambda exc, _raw: fallback_stop_decision(reason=str(exc)),
            reasoning=True,
            json_object=False,
        )
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
