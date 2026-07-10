from __future__ import annotations

from typing import Any

from agent.run_trace import ToolStep

_SHEETS_WRITE_TOOLS = frozenset(
    {
        "google.sheets.update_values",
        "google.sheets.append_values",
        "google.sheets.batch_update_values",
    },
)

_REBUILD_KEYWORDS = (
    "rebuild",
    "finish",
    "complete",
    "locate and fetch",
    "before proceeding",
    "before moving",
    "first ",
    "redo",
    "still need",
    "not yet",
    "missing",
)


def _tab_from_range(range_a1: str) -> str | None:
    text = str(range_a1 or "").strip()
    if "!" not in text:
        return None
    return text.split("!", 1)[0].strip() or None


def _value_rows(arguments_normalized: dict[str, Any]) -> int:
    values = arguments_normalized.get("values")
    if not isinstance(values, list):
        return 0
    return len(values)


def extract_completed_sheet_tabs(steps: list[ToolStep]) -> dict[str, int]:
    """Tab name -> max data rows written (header-only writes count as 0)."""
    tabs: dict[str, int] = {}
    for step in steps:
        if step.target_tool not in _SHEETS_WRITE_TOOLS or step.result_ok is not True:
            continue
        tab = _tab_from_range(str(step.arguments_normalized.get("range") or ""))
        if not tab:
            continue
        rows = _value_rows(step.arguments_normalized)
        if rows <= 1:
            continue
        tabs[tab] = max(tabs.get(tab, 0), rows)
    return tabs


def _tab_human_name(tab: str) -> str:
    base = tab.split("_", 1)[-1] if "_" in tab else tab
    return base.replace("_", " ").lower()


def _tab_aliases(tab: str) -> set[str]:
    human = _tab_human_name(tab)
    aliases = {human}
    core = human.removesuffix(" gp").strip()
    if core:
        aliases.add(core)
        aliases.add(f"{core} grand prix")
        aliases.add(f"{core} gp")
    return {alias for alias in aliases if len(alias) >= 4}


def coach_mentions_tab_rebuild(coach_text: str, tab: str) -> bool:
    lowered = coach_text.lower()
    for alias in _tab_aliases(tab):
        if alias in lowered and any(keyword in lowered for keyword in _REBUILD_KEYWORDS):
            return True
    return False


def format_sheets_progress(steps: list[ToolStep]) -> str:
    tabs = extract_completed_sheet_tabs(steps)
    if not tabs:
        return ""
    lines = ["Sheets units with data written (from update_values/append in trace):"]
    for tab, rows in sorted(tabs.items()):
        lines.append(f"- {tab}: {rows} rows")
    return "\n".join(lines)
