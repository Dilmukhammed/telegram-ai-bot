from __future__ import annotations

import re

_PLAN_ROOT = re.compile(r"^(phase_plan|master_phase_plan)\s*:", re.MULTILINE)
_FENCE = re.compile(r"```(?:yaml|yml)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_THINKING_MARKERS = (
    "Thinking Process:",
    "thinking process:",
    "**Mental Sandbox:**",
)


def extract_plan_yaml(raw: str, *, root: str = "phase_plan") -> str:
    """Drop thinking/reasoning preamble; return YAML starting at plan root, or empty."""
    text = (raw or "").strip()
    if not text:
        return ""

    for match in _FENCE.finditer(text):
        body = match.group(1).strip()
        if _PLAN_ROOT.search(body):
            return body

    match = _PLAN_ROOT.search(text)
    if match:
        return text[match.start() :].strip()

    return ""


def plan_yaml_valid(yaml_text: str, *, root: str) -> bool:
    stripped = (yaml_text or "").strip()
    return stripped.startswith(f"{root}:")


def planner_response_text(message: object) -> str:
    """Use final content only; never surface model reasoning/thinking."""
    return (getattr(message, "content", None) or "").strip()
