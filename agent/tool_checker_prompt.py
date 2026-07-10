from __future__ import annotations

from config import Settings


def build_checker_system_prompt(settings: Settings) -> str:
    return """You are a tool-use checker for an AI agent run.

You verify ONE tool call against specific questions using ONLY the evidence provided.
You also receive the **run cycle log** — compact worker steps and **prior checker verdicts** (pass and fail).
Use it to understand repair loops: delete-then-recreate after a bad create may be valid — do not fail delete solely because the user asked to create if the cycle shows corrective cleanup of a mistaken event.

You judge **ground truth / outcome**, not whether the agent followed a particular tool order.
The agent does not need to have called freebusy first — use live calendar evidence when present.
You do NOT call tools. Do not invent facts missing from evidence.

For each question return:
- pass — evidence supports correct tool usage
- fail — evidence shows a mistake or ignored prior data
- unknown — evidence is insufficient or ambiguous (never treat unknown as pass)
- n_a — question does not apply to this call (e.g. delete is valid repair step)

Output valid JSON only, no markdown fences:
{
  "verdicts": [
    {"question_id": "...", "verdict": "pass|fail|unknown|n_a", "reason": "one line"}
  ],
  "overall": "pass|fail|warn|unknown"
}

Set overall to:
- fail if any critical question fails
- warn if any non-critical question fails
- pass if all applicable questions pass or are n_a
- unknown if you cannot judge the call

Write reasons in the same language as the user goal when obvious.
"""


def build_checker_user_prompt(
    *,
    user_message: str,
    tool_name: str,
    turn: int,
    cycle_log: str,
    resolved_questions: list[tuple[str, str, str, list[tuple[str, str]]]],
) -> str:
    """resolved_questions: (id, severity, text, [(label, content), ...])."""
    lines = [
        f"Goal: {user_message.strip()}",
        "",
        "Run cycle log (worker + prior checker verdicts — read for context):",
        cycle_log.strip(),
        "",
        "Call under review:",
        f"  tool: {tool_name}",
        f"  turn: {turn}",
        "",
        "Questions:",
    ]
    for index, (question_id, severity, text, snippets) in enumerate(resolved_questions, start=1):
        lines.append(f"{index}. [{severity}] {question_id}: {text}")
        if snippets:
            for label, content in snippets:
                lines.append(f"   Evidence {label}:")
                lines.append(f"     {content}")
        else:
            lines.append("   Evidence: (none attached for this question)")
        lines.append("")
    return "\n".join(lines).strip()
