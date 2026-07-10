from __future__ import annotations

import re
from pathlib import Path

_SECTION = re.compile(
    r"^## (?P<label>P1_unit|P2_surface|P3_hot) \(`(?P<model>[^`]+)`\)\s*$",
    re.MULTILINE,
)


def parse_phase1_bundle(path: Path) -> tuple[str, dict[str, tuple[str, str]]]:
    """Return (user_request, {label: (model, plan_body)})."""
    text = path.read_text(encoding="utf-8")
    req_match = re.search(
        r"## User request\s*\n(.*?)\n\n---",
        text,
        re.DOTALL,
    )
    user_request = req_match.group(1).strip() if req_match else ""

    plans: dict[str, tuple[str, str]] = {}
    matches = list(_SECTION.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        plans[match.group("label")] = (match.group("model"), body)

    return user_request, plans
