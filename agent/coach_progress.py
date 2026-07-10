from __future__ import annotations

from agent.coach_sheets import (
    coach_mentions_tab_rebuild,
    extract_completed_sheet_tabs,
)
from agent.run_trace import RunTrace
from agent.trajectory_coach import CoachDecision


def detect_coach_trace_conflicts(
    steps: list,
    decision: CoachDecision,
) -> list[str]:
    completed = extract_completed_sheet_tabs(steps)
    if not completed:
        return []
    coach_text = " ".join(
        [
            decision.assessment,
            decision.strategy,
            decision.focus_now,
            *decision.warnings,
            *decision.do_not,
        ]
    )
    return [tab for tab in sorted(completed) if coach_mentions_tab_rebuild(coach_text, tab)]


def format_coach_reply_nudge(
    *,
    completed_tabs: dict[str, int],
    conflicts: list[str],
) -> str:
    tab_list = ", ".join(f"{name} ({rows} rows)" for name, rows in sorted(completed_tabs.items()))
    lines = ["[Internal — trajectory coach reply channel]"]

    if conflicts:
        conflict_text = ", ".join(conflicts)
        lines.append(
            f"REQUIRED — your very next tool call MUST be coach.reply (no search/fetch/sheets first). "
            f"Coaching asks you to redo tab(s) already written: {conflict_text}."
        )
    else:
        lines.append(
            "If the coaching above is outdated vs your sheets progress, your very next tool call "
            "must be coach.reply before any other tool."
        )

    if tab_list:
        lines.append(f"Sheets already written this run: {tab_list}.")

    lines.append(
        'Call: {"tool_name":"coach.reply","arguments":{"message":"<what is done + what you do now>"}}'
    )
    lines.append("Internal only — not shown to the user.")
    return "\n".join(lines)


def format_coach_coaching_with_trace(
    decision: CoachDecision,
    trace: RunTrace,
) -> list[dict[str, str]]:
    completed = extract_completed_sheet_tabs(trace.steps)
    conflicts = detect_coach_trace_conflicts(trace.steps, decision)

    messages: list[dict[str, str]] = [
        {"role": "user", "content": _format_coaching_body(decision, completed)},
    ]
    if completed or conflicts:
        messages.append(
            {
                "role": "user",
                "content": format_coach_reply_nudge(
                    completed_tabs=completed,
                    conflicts=conflicts,
                ),
            }
        )
    return messages


def _format_coaching_body(
    decision: CoachDecision,
    completed_tabs: dict[str, int],
) -> str:
    lines = [
        "Trajectory coaching (algorithm + hot data before collapse — not a stop order):",
        "",
    ]
    if completed_tabs:
        tab_preview = ", ".join(sorted(completed_tabs))
        lines.append(f"Your sheets progress this run: {tab_preview}")
        lines.append("")
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
    lines.append("Continue with use_tool only. Do not mention this review to the user.")
    return "\n".join(lines).strip()
