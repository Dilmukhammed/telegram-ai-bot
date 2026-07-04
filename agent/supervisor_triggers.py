from __future__ import annotations

from dataclasses import dataclass

from agent.run_trace import ToolStep


@dataclass(frozen=True)
class SoftTrigger:
    reason: str
    detail: str


def detect_soft_trigger(
    steps: list[ToolStep],
    *,
    completed_turns: int,
    soft_triggers_enabled: bool,
    periodic_every: int,
    loop_search_min: int = 3,
    loop_window_turns: int = 4,
    loop_fail_min: int = 2,
) -> SoftTrigger | None:
    if not soft_triggers_enabled or completed_turns < 1:
        return None

    loop_fail = _detect_loop_fail(steps, loop_fail_min=loop_fail_min)
    if loop_fail is not None:
        return loop_fail

    loop_search = _detect_loop_search(
        steps,
        completed_turns=completed_turns,
        loop_search_min=loop_search_min,
        loop_window_turns=loop_window_turns,
    )
    if loop_search is not None:
        return loop_search

    if periodic_every > 0 and completed_turns % periodic_every == 0:
        return SoftTrigger("periodic", f"scheduled check at turn {completed_turns}")

    return None


def _window_steps(steps: list[ToolStep], *, completed_turns: int, loop_window_turns: int) -> list[ToolStep]:
    window_start = max(1, completed_turns - loop_window_turns + 1)
    return [step for step in steps if window_start <= step.turn <= completed_turns]


def _detect_loop_search(
    steps: list[ToolStep],
    *,
    completed_turns: int,
    loop_search_min: int,
    loop_window_turns: int,
) -> SoftTrigger | None:
    if completed_turns < loop_search_min:
        return None

    window = _window_steps(steps, completed_turns=completed_turns, loop_window_turns=loop_window_turns)
    search_count = sum(1 for step in window if step.meta_tool == "search_tools")
    if search_count < loop_search_min:
        return None

    successful_use = any(
        step.meta_tool == "use_tool" and step.result_ok is True for step in window
    )
    if successful_use:
        return None

    return SoftTrigger(
        "loop_search",
        f"{search_count} search_tools in last {loop_window_turns} turns without successful use_tool",
    )


def _detect_loop_fail(steps: list[ToolStep], *, loop_fail_min: int) -> SoftTrigger | None:
    failed = [
        step
        for step in steps
        if step.meta_tool == "use_tool" and step.result_ok is False and step.target_tool
    ]
    if len(failed) < loop_fail_min:
        return None

    recent = failed[-loop_fail_min:]
    first = recent[0]
    if not all(
        step.target_tool == first.target_tool and step.result_error == first.result_error
        for step in recent
    ):
        return None

    error_text = first.result_error or "unknown error"
    return SoftTrigger(
        "loop_fail",
        f"{loop_fail_min}× failed {first.target_tool}: {error_text}",
    )
