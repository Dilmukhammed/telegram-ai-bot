from __future__ import annotations

from typing import Any

from agent.coach_outputs import format_outputs_produced
from agent.coach_sheets import format_sheets_progress
from agent.run_cycle_log import _STEP_SEP, CycleLogOptions, build_run_cycle_log
from agent.run_trace import RunTrace
from config import Settings


_ACTIONABLE_VERDICTS = frozenset({"fail", "warn"})


def format_checker_findings(checker_reviews: list[dict[str, Any]], *, limit: int = 12) -> str:
    """Compact list of open verification concerns (fail/warn) from the tool checker.

    Folded into the coach trace so the coach — the single trajectory reviewer — can
    act on per-call verification results without a separate arbiter LLM pass.
    """
    findings: list[str] = []
    for review in checker_reviews:
        overall = str(review.get("overall") or "").lower()
        if overall not in _ACTIONABLE_VERDICTS:
            continue
        tool = review.get("tool_name") or "?"
        turn = review.get("turn") or "?"
        bits: list[str] = []
        for item in review.get("verdicts") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("verdict") or "").lower() not in _ACTIONABLE_VERDICTS:
                continue
            qid = item.get("question_id") or "?"
            verdict = item.get("verdict") or "?"
            severity = item.get("severity") or ""
            reason = str(item.get("reason") or "").strip()
            tag = f"{qid}={verdict}" + (f"({severity})" if severity else "")
            if reason:
                tag = f"{tag}: {reason}"
            bits.append(tag)
        if not bits:
            continue
        findings.append(f"- [turn {turn}] {tool} — " + " | ".join(bits))
        if len(findings) >= limit:
            break
    if not findings:
        return ""
    return (
        "Verification findings (tool checker — automated post-call checks):\n"
        + "\n".join(findings)
        + "\nIf the worker already fixed these in later steps (delete/patch/retry), do NOT re-flag them."
    )


def _format_worker_coach_replies(replies: list[dict[str, Any]]) -> str:
    if not replies:
        return ""
    lines = ["Worker replies to coach (full text — authoritative over older steps):"]
    for entry in replies:
        lines.append(
            f"[after tool call #{entry.get('tool_calls_at', '?')}, step {entry.get('tool_step_index', '?')}] "
            f"{entry.get('message', '')}"
        )
    return "\n".join(lines)


def build_coach_trace(trace: RunTrace, *, settings: Settings) -> str:
    header_extras: list[str] = []
    header_extras.append(
        (
            f"Collapse rule: tool results >{settings.tool_result_archive_min_chars} chars lose full JSON after "
            f"{settings.tool_result_collapse_stale_steps} worker turns since the call (see `data:` on each step)."
        )
    )

    worker_replies = _format_worker_coach_replies(trace.worker_coach_replies)
    if worker_replies:
        header_extras.append("")
        header_extras.append(worker_replies)

    outputs_produced = format_outputs_produced(trace.steps)
    if outputs_produced:
        header_extras.append("")
        header_extras.append(outputs_produced)

    checker_findings = format_checker_findings(trace.checker_reviews)
    if checker_findings:
        header_extras.append("")
        header_extras.append(checker_findings)

    sheets_progress = format_sheets_progress(trace.steps)
    if sheets_progress:
        header_extras.append("")
        header_extras.append(sheets_progress)

    options = CycleLogOptions(
        step_limit=max(120, settings.coach_max_field_chars),
        max_chars=max(1000, settings.coach_max_trace_chars),
        include_checker_reviews=True,
    )
    return build_run_cycle_log(
        trace,
        settings=settings,
        options=options,
        header_extras=header_extras,
    )
