from __future__ import annotations

import fnmatch
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from agent.run_cycle_log import build_cycle_log_for_checker
from agent.run_trace import ToolStep
from agent.verdict_json import extract_json_payload as _extract_json_payload
from agent.tool_checker_evidence import EvidenceResolver, format_bundle_for_debug
from agent.tool_checker_live import (
    fetch_live_evidence_snippets,
    rule_verdict_for_resource_exists,
    rule_verdict_for_slot_conflicts,
)
from agent.tool_checker_prompt import build_checker_system_prompt, build_checker_user_prompt
from config import Settings
from llm import LLMClient
from tools.builtins.google.calendar_checker import SLOT_CONFLICT_QUESTION_IDS
from tools.checker import get_checker_questions
from tools.runtime import ToolRuntime
from tools.schema import ToolSpec
from tools.verification import (
    RULE_CHECK_RESOURCE_EXISTS,
    RULE_CHECK_SLOT_FREE,
    SEVERITY_CRITICAL,
    VERDICT_FAIL,
    VERDICT_NA,
    VERDICT_PASS,
    VERDICT_UNKNOWN,
    CheckerRuntimeContext,
    EvidenceSnippet,
    QuestionVerdict,
    ResolvedQuestion,
    VerificationQuestion,
)

logger = logging.getLogger(__name__)

OVERALL_PASS = "pass"
OVERALL_FAIL = "fail"
OVERALL_WARN = "warn"
OVERALL_UNKNOWN = "unknown"


@dataclass
class ToolCheckerReview:
    tool_name: str
    turn: int
    step_index: int
    overall: str = OVERALL_UNKNOWN
    verdicts: list[QuestionVerdict] = field(default_factory=list)
    checker_input: str = ""
    cycle_log: str = ""
    rule_based_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "turn": self.turn,
            "step_index": self.step_index,
            "overall": self.overall,
            "verdicts": [
                {
                    "question_id": item.question_id,
                    "verdict": item.verdict,
                    "severity": item.severity,
                    "reason": item.reason,
                    "evidence_used": item.evidence_used,
                    "evidence_missing": item.evidence_missing,
                    "rule_based": item.rule_based,
                }
                for item in self.verdicts
            ],
            "checker_input": self.checker_input,
            "cycle_log": self.cycle_log,
            "rule_based_only": self.rule_based_only,
        }


TARGET_EXISTS_QUESTION_IDS = frozenset({"target_resource_exists"})


def _rule_check_kind(question: VerificationQuestion) -> str:
    """Which deterministic rule (if any) resolves this question.

    Prefers the declarative ``rule_check`` field; falls back to the legacy id-based
    sets so existing hand-written calendar questions keep short-circuiting.
    """
    if question.rule_check:
        return question.rule_check
    if question.id in SLOT_CONFLICT_QUESTION_IDS:
        return RULE_CHECK_SLOT_FREE
    if question.id in TARGET_EXISTS_QUESTION_IDS:
        return RULE_CHECK_RESOURCE_EXISTS
    return ""


def _live_snippet_with(resolved: ResolvedQuestion, key: str) -> EvidenceSnippet | None:
    """First live-fetch snippet attached to this question whose JSON has ``key``."""
    for snippet in resolved.snippets:
        content = snippet.content or ""
        if f'"{key}"' in content:
            return snippet
    return None


def should_run_tool_checker(
    *,
    spec: ToolSpec,
    step: ToolStep,
    settings: Settings,
) -> bool:
    return checker_skip_reason(spec=spec, step=step, settings=settings) is None


def checker_skip_reason(
    *,
    spec: ToolSpec,
    step: ToolStep,
    settings: Settings,
) -> str | None:
    if not settings.agent_checker_enabled:
        return "disabled"
    if not get_checker_questions(spec):
        return "no_questions"
    if not spec.checker_enabled:
        return "tool_disabled"
    if step.meta_tool != "use_tool" or not step.target_tool:
        return "not_use_tool"
    if settings.checker_skip_cached and step.result_cached:
        return "cached"
    if step.result_ok is False:
        return "failed_call"
    allowlist = settings.checker_tools_allowlist.strip()
    if allowlist and not _tool_allowed(spec.name, allowlist):
        return "not_allowlisted"
    return None


def _tool_allowed(tool_name: str, allowlist: str) -> bool:
    patterns = [item.strip() for item in allowlist.split(",") if item.strip()]
    return any(fnmatch.fnmatchcase(tool_name, pattern) for pattern in patterns)


def compute_overall(verdicts: list[QuestionVerdict]) -> str:
    if not verdicts:
        return OVERALL_UNKNOWN
    if any(
        item.verdict == VERDICT_FAIL and item.severity == SEVERITY_CRITICAL
        for item in verdicts
    ):
        return OVERALL_FAIL
    if any(item.verdict == VERDICT_FAIL for item in verdicts):
        return OVERALL_WARN
    if all(item.verdict in {VERDICT_PASS, VERDICT_NA} for item in verdicts):
        return OVERALL_PASS
    if all(item.verdict == VERDICT_UNKNOWN for item in verdicts):
        return OVERALL_UNKNOWN
    return OVERALL_WARN


def parse_checker_response(text: str, *, question_ids: set[str]) -> tuple[list[QuestionVerdict], str]:
    raw = _extract_json_payload(text)
    if not raw:
        raise ValueError("checker response is empty")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("checker response must be a JSON object")

    verdicts: list[QuestionVerdict] = []
    seen: set[str] = set()
    for item in payload.get("verdicts") or []:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id", "")).strip()
        if not question_id or question_id not in question_ids:
            continue
        verdict = str(item.get("verdict", VERDICT_UNKNOWN)).strip().lower()
        if verdict not in {VERDICT_PASS, VERDICT_FAIL, VERDICT_UNKNOWN, VERDICT_NA}:
            verdict = VERDICT_UNKNOWN
        verdicts.append(
            QuestionVerdict(
                question_id=question_id,
                verdict=verdict,
                severity=str(item.get("severity") or "").strip() or "warn",
                reason=str(item.get("reason", "")).strip(),
                rule_based=False,
            )
        )
        seen.add(question_id)

    overall = str(payload.get("overall", "")).strip().lower()
    if overall not in {OVERALL_PASS, OVERALL_FAIL, OVERALL_WARN, OVERALL_UNKNOWN}:
        overall = compute_overall(verdicts)
    return verdicts, overall


class ToolChecker:
    def __init__(self, llm: LLMClient, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings
        self._resolver = EvidenceResolver()

    @property
    def enabled(self) -> bool:
        return self._settings.agent_checker_enabled

    async def review_step(
        self,
        *,
        spec: ToolSpec,
        current_step: ToolStep,
        prior_steps: tuple[ToolStep, ...],
        user_message: str,
        user_id: int | None,
        runtime: ToolRuntime,
        all_steps: tuple[ToolStep, ...] | None = None,
        prior_checker_reviews: tuple[dict[str, Any], ...] = (),
        worker_turns_used: int = 0,
        worker_turns_budget: int = 0,
    ) -> ToolCheckerReview:
        steps_for_log = all_steps if all_steps is not None else (*prior_steps, current_step)
        cycle_log = build_cycle_log_for_checker(
            user_message=user_message,
            steps=steps_for_log,
            checker_reviews=prior_checker_reviews,
            current_step=current_step,
            settings=self._settings,
            worker_turns_used=worker_turns_used,
            worker_turns_budget=worker_turns_budget,
        )
        checker_runtime = CheckerRuntimeContext.from_settings(user_message=user_message)
        questions = get_checker_questions(spec)
        all_evidence = tuple(ref for question in questions for ref in question.evidence)
        live_snippets = await fetch_live_evidence_snippets(
            evidence_refs=all_evidence,
            current_step=current_step,
            user_id=user_id,
            runtime=runtime,
        )
        bundle = self._resolver.resolve_bundle(
            questions=questions,
            current_step=current_step,
            prior_steps=prior_steps,
            runtime=checker_runtime,
            user_message=user_message,
            live_snippets=live_snippets,
        )
        if self._settings.agent_checker_debug:
            logger.info(
                "tool_checker debug bundle tool=%s turn=%s payload=%s",
                spec.name,
                current_step.turn,
                format_bundle_for_debug(
                    bundle,
                    live_snippets=live_snippets,
                    max_chars=self._settings.checker_evidence_max_chars,
                ),
            )

        rule_verdicts: dict[str, QuestionVerdict] = {
            item.question_id: item for item in bundle.rule_based_verdicts()
        }
        for resolved in bundle.questions:
            if resolved.question.id in rule_verdicts:
                continue
            kind = _rule_check_kind(resolved.question)
            if not kind:
                continue
            if kind == RULE_CHECK_SLOT_FREE:
                snippet = _live_snippet_with(resolved, "conflicting_events") or live_snippets.get(
                    "slot_conflicts_live"
                )
                verdict = rule_verdict_for_slot_conflicts(
                    question_id=resolved.question.id,
                    severity=resolved.question.severity,
                    snippet=snippet,
                )
            elif kind == RULE_CHECK_RESOURCE_EXISTS:
                snippet = _live_snippet_with(resolved, "exists")
                verdict = rule_verdict_for_resource_exists(
                    question_id=resolved.question.id,
                    severity=resolved.question.severity,
                    snippet=snippet,
                )
            else:
                verdict = None
            if verdict is not None:
                rule_verdicts[resolved.question.id] = verdict

        llm_questions = [
            resolved
            for resolved in bundle.questions
            if resolved.question.id not in rule_verdicts and resolved.question.llm_required
        ]

        checker_input = ""
        llm_verdicts: list[QuestionVerdict] = []
        overall = OVERALL_UNKNOWN

        if llm_questions:
            prompt_questions = [
                (
                    resolved.question.id,
                    resolved.question.severity,
                    resolved.question.text,
                    [(snippet.label, snippet.content) for snippet in resolved.snippets],
                )
                for resolved in llm_questions
            ]
            checker_input = build_checker_user_prompt(
                user_message=user_message,
                tool_name=spec.name,
                turn=current_step.turn,
                cycle_log=cycle_log,
                resolved_questions=prompt_questions,
            )
            llm_verdicts, overall = await self._llm_review(
                checker_input=checker_input,
                question_ids={item[0] for item in prompt_questions},
                severities={item[0]: item[1] for item in prompt_questions},
            )
        else:
            overall = compute_overall(list(rule_verdicts.values()))
            checker_input = build_checker_user_prompt(
                user_message=user_message,
                tool_name=spec.name,
                turn=current_step.turn,
                cycle_log=cycle_log,
                resolved_questions=[
                    (
                        resolved.question.id,
                        resolved.question.severity,
                        resolved.question.text,
                        [(snippet.label, snippet.content) for snippet in resolved.snippets],
                    )
                    for resolved in bundle.questions
                    if resolved.question.id in rule_verdicts
                ],
            )

        merged: dict[str, QuestionVerdict] = dict(rule_verdicts)
        for verdict in llm_verdicts:
            merged[verdict.question_id] = verdict

        for resolved in bundle.questions:
            if resolved.question.id in merged:
                continue
            merged[resolved.question.id] = QuestionVerdict(
                question_id=resolved.question.id,
                verdict=VERDICT_UNKNOWN,
                severity=resolved.question.severity,
                reason="No checker verdict produced",
                evidence_used=[snippet.label for snippet in resolved.snippets if snippet.label],
                evidence_missing=list(resolved.missing_required),
            )

        verdict_list = [merged[resolved.question.id] for resolved in bundle.questions]
        if llm_questions:
            overall = compute_overall(verdict_list)

        return ToolCheckerReview(
            tool_name=spec.name,
            turn=current_step.turn,
            step_index=bundle.step_index,
            overall=overall,
            verdicts=verdict_list,
            checker_input=checker_input,
            cycle_log=cycle_log,
            rule_based_only=not llm_questions,
        )

    async def _llm_review(
        self,
        *,
        checker_input: str,
        question_ids: set[str],
        severities: dict[str, str],
    ) -> tuple[list[QuestionVerdict], str]:
        messages = [
            {"role": "system", "content": build_checker_system_prompt(self._settings)},
            {"role": "user", "content": checker_input},
        ]
        raw = await self._llm.chat_without_reasoning(
            messages,
            max_tokens=self._settings.checker_max_output_tokens,
            response_format={"type": "json_object"},
        )
        try:
            parsed, overall = parse_checker_response(raw, question_ids=question_ids)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("tool_checker parse failed: %s raw_len=%s", exc, len(raw))
            return [], OVERALL_UNKNOWN

        for verdict in parsed:
            if verdict.severity == "warn" and verdict.question_id in severities:
                verdict.severity = severities[verdict.question_id]
        return parsed, overall
