from __future__ import annotations

import json
import logging
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from tools.coerce import normalize_use_tool_call
from agent.coach_dialog import get_coach_worker_replies

logger = logging.getLogger(__name__)

DEFAULT_RESULT_PREVIEW_CHARS = 400


@dataclass
class ToolStep:
    turn: int
    meta_tool: str
    target_tool: str | None
    arguments_raw: dict[str, Any]
    arguments_normalized: dict[str, Any]
    result_ok: bool | None = None
    result_cached: bool = False
    result_error: str | None = None
    result_preview: str = ""
    result_json: str = ""
    duration_ms: int = 0
    timestamp: float = 0.0
    collapsed_from_context: bool = False


@dataclass
class RunTrace:
    user_id: int | None
    user_message: str
    started_at: float
    steps: list[ToolStep] = field(default_factory=list)
    worker_turns_used: int = 0
    worker_turns_budget: int = 0
    final_outcome: str | None = None
    search_history: list[dict[str, Any]] = field(default_factory=list)
    successful_tools: list[str] = field(default_factory=list)
    failed_tools: list[str] = field(default_factory=list)
    repeated_patterns: list[str] = field(default_factory=list)
    progress_summary: str = ""
    coach_reviews: list[dict[str, Any]] = field(default_factory=list)
    worker_coach_replies: list[dict[str, Any]] = field(default_factory=list)
    checker_reviews: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [asdict(step) for step in self.steps]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunTrace:
        steps = [
            ToolStep(**step)
            for step in payload.get("steps") or []
            if isinstance(step, dict)
        ]
        return cls(
            user_id=payload.get("user_id"),
            user_message=str(payload.get("user_message") or ""),
            started_at=float(payload.get("started_at") or 0.0),
            steps=steps,
            worker_turns_used=int(payload.get("worker_turns_used") or 0),
            worker_turns_budget=int(payload.get("worker_turns_budget") or 0),
            final_outcome=payload.get("final_outcome"),
            search_history=list(payload.get("search_history") or []),
            successful_tools=list(payload.get("successful_tools") or []),
            failed_tools=list(payload.get("failed_tools") or []),
            repeated_patterns=list(payload.get("repeated_patterns") or []),
            progress_summary=str(payload.get("progress_summary") or ""),
            coach_reviews=list(payload.get("coach_reviews") or []),
            worker_coach_replies=list(payload.get("worker_coach_replies") or []),
            checker_reviews=list(payload.get("checker_reviews") or []),
        )


def _preview_result(result_json: str, max_chars: int = DEFAULT_RESULT_PREVIEW_CHARS) -> str:
    collapsed = " ".join(str(result_json).split())
    if len(collapsed) <= max_chars:
        return collapsed
    return f"{collapsed[: max_chars - 1]}…"


def _parse_result_fields(result_json: str) -> tuple[bool | None, bool, str | None]:
    try:
        payload = json.loads(result_json)
    except json.JSONDecodeError:
        return False, False, "invalid JSON result"

    if not isinstance(payload, dict):
        return False, False, "non-object result"

    ok = payload.get("ok")
    if ok is None and ("tools" in payload or "count" in payload):
        ok = True
    if ok is None and payload.get("error"):
        ok = False

    cached = bool(payload.get("cached"))
    error = payload.get("error")
    return ok, cached, str(error) if error else None


def _normalize_arguments(meta_tool: str, arguments_raw: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    if meta_tool == "search_tools":
        tags = arguments_raw.get("tags") or []
        normalized = {
            "query": str(arguments_raw.get("query", "")),
            "mode": str(arguments_raw.get("mode", "rank")),
            "top_k": int(arguments_raw.get("top_k", 5)),
            "tags": [str(tag) for tag in tags] if isinstance(tags, list) else [],
        }
        return None, normalized

    if meta_tool == "use_tool":
        target, inner = normalize_use_tool_call(arguments_raw)
        return target or None, inner

    return None, dict(arguments_raw)


def _search_summary(result_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(result_json)
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid JSON"}

    if not isinstance(payload, dict):
        return {"ok": False, "error": "non-object result"}

    tools = payload.get("tools") or []
    tool_names = [str(item.get("name")) for item in tools if isinstance(item, dict) and item.get("name")]
    return {
        "ok": payload.get("ok", bool(tools or "count" in payload)),
        "count": payload.get("count", len(tools)),
        "top_tools": tool_names[:5],
        "error": payload.get("error"),
    }


def _detect_repeated_patterns(steps: list[ToolStep]) -> list[str]:
    patterns: list[str] = []

    search_keys = [
        (
            step.turn,
            step.arguments_normalized.get("mode"),
            tuple(step.arguments_normalized.get("tags") or []),
            step.arguments_normalized.get("query"),
        )
        for step in steps
        if step.meta_tool == "search_tools"
    ]
    key_counts = Counter(item[1:] for item in search_keys)
    for key, count in key_counts.items():
        if count >= 2:
            mode, tags, query = key
            patterns.append(f"search_tools×{count} mode={mode} tags={list(tags)} query={query!r}")

    consecutive_search = 0
    max_consecutive_search = 0
    for step in steps:
        if step.meta_tool == "search_tools":
            consecutive_search += 1
            max_consecutive_search = max(max_consecutive_search, consecutive_search)
        elif step.meta_tool == "use_tool":
            consecutive_search = 0
    if max_consecutive_search >= 2:
        patterns.append(f"{max_consecutive_search}× consecutive search_tools without use_tool between")

    raw_vs_normalized: list[str] = []
    for step in steps:
        if step.meta_tool != "use_tool" or not step.target_tool:
            continue
        raw = step.arguments_raw.get("arguments") or {}
        if not isinstance(raw, dict):
            continue
        normalized = step.arguments_normalized
        if raw == normalized:
            continue
        raw_keys = set(raw)
        norm_keys = set(normalized)
        if raw_keys - norm_keys:
            raw_vs_normalized.append(
                f"turn {step.turn}: {step.target_tool} raw keys {sorted(raw_keys - norm_keys)} "
                f"→ normalized {sorted(norm_keys)}"
            )
    patterns.extend(raw_vs_normalized[:5])
    return patterns


def _build_progress_summary(successful_tools: list[str]) -> str:
    if not successful_tools:
        return "no successful tools yet"

    parts: list[str] = []
    for name in successful_tools:
        short = name.split(".")[-1] if "." in name else name
        parts.append(f"{short} OK")
    return " | ".join(parts)


class RunTraceCollector:
    def __init__(
        self,
        *,
        user_id: int | None,
        user_message: str,
        worker_turns_budget: int,
        debug_trace: bool = False,
    ) -> None:
        self._user_id = user_id
        self._user_message = user_message
        self._worker_turns_budget = worker_turns_budget
        self._debug_trace = debug_trace
        self._started_at = time.time()
        self._steps: list[ToolStep] = []
        self._worker_turns_used = 0
        self._final_outcome: str | None = None
        self._open_steps: dict[tuple[int, str], ToolStep] = {}
        self._coach_reviews: list[dict[str, Any]] = []
        self._checker_reviews: list[dict[str, Any]] = []
        self._checker_dedup: set[str] = set()

    @property
    def user_id(self) -> int | None:
        return self._user_id

    @property
    def worker_turns_used(self) -> int:
        return self._worker_turns_used

    @property
    def worker_turns_budget(self) -> int:
        return self._worker_turns_budget

    def checker_reviews_snapshot(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._checker_reviews)

    @property
    def checker_review_count(self) -> int:
        return len(self._checker_reviews)

    def record_coach_review(
        self,
        *,
        turn: int,
        tool_calls: int,
        trace_input: str,
        decision: Any,
    ) -> None:
        payload = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision)
        entry = {
            "turn": turn,
            "tool_calls": tool_calls,
            "trace_input": trace_input,
            **payload,
        }
        self._coach_reviews.append(entry)
        logger.info(
            "run_trace_coach turn=%s tool_calls=%s trace_chars=%s intervene=%s on_track=%s focus=%s",
            turn,
            tool_calls,
            len(trace_input),
            payload.get("intervene"),
            payload.get("on_track"),
            payload.get("focus_now") or "-",
        )

    def record_checker_review(self, review: Any) -> None:
        payload = review.to_dict() if hasattr(review, "to_dict") else dict(review)
        self._checker_reviews.append(payload)
        logger.info(
            "run_trace_checker turn=%s tool=%s overall=%s rule_based_only=%s verdicts=%s",
            payload.get("turn"),
            payload.get("tool_name"),
            payload.get("overall"),
            payload.get("rule_based_only"),
            len(payload.get("verdicts") or []),
        )

    def begin_worker_turn(self, turn: int) -> None:
        self._worker_turns_used = max(self._worker_turns_used, turn + 1)

    def on_tool_dispatch(
        self,
        *,
        turn: int,
        meta_tool: str,
        arguments_raw: dict[str, Any],
        call_id: str,
    ) -> None:
        target_tool, arguments_normalized = _normalize_arguments(meta_tool, arguments_raw)
        step = ToolStep(
            turn=turn + 1,
            meta_tool=meta_tool,
            target_tool=target_tool,
            arguments_raw=dict(arguments_raw),
            arguments_normalized=arguments_normalized,
            timestamp=time.time(),
        )
        self._steps.append(step)
        self._open_steps[(turn + 1, call_id)] = step
        logger.info(
            "run_trace_dispatch turn=%s meta=%s target=%s raw=%s normalized=%s",
            step.turn,
            meta_tool,
            target_tool,
            arguments_raw,
            arguments_normalized,
        )

    def on_tool_result(
        self,
        *,
        turn: int,
        call_id: str,
        result_json: str,
        duration_ms: int,
    ) -> ToolStep | None:
        step = self._open_steps.pop((turn + 1, call_id), None)
        if step is None and self._steps:
            step = self._steps[-1]

        if step is None:
            return None

        ok, cached, error = _parse_result_fields(result_json)
        step.result_ok = ok
        step.result_cached = cached
        step.result_error = error
        step.result_json = result_json
        step.result_preview = _preview_result(result_json)
        step.duration_ms = duration_ms

        logger.info(
            "run_trace_step turn=%s meta=%s target=%s ok=%s cached=%s duration_ms=%s error=%s",
            step.turn,
            step.meta_tool,
            step.target_tool,
            ok,
            cached,
            duration_ms,
            error,
        )
        return step

    def steps_before(self, step: ToolStep) -> tuple[ToolStep, ...]:
        """Steps recorded before ``step`` (by identity), for evidence resolution."""
        prior: list[ToolStep] = []
        for candidate in self._steps:
            if candidate is step:
                break
            prior.append(candidate)
        return tuple(prior)

    def register_checker_dedup(self, key: str) -> bool:
        """Return True the first time ``key`` is seen this run (else False)."""
        if key in self._checker_dedup:
            return False
        self._checker_dedup.add(key)
        return True

    def mark_last_search_collapsed(self) -> None:
        for step in reversed(self._steps):
            if step.meta_tool != "search_tools" or step.collapsed_from_context:
                continue
            step.collapsed_from_context = True
            logger.info(
                "run_trace_collapsed turn=%s meta=search_tools (removed from worker context)",
                step.turn,
            )
            return

    def finish(self, outcome: str) -> RunTrace:
        self._final_outcome = outcome
        trace = self._compile_trace(outcome)
        logger.info(
            "run_trace_complete outcome=%s steps=%s turns=%s/%s successful=%s failed=%s searches=%s",
            outcome,
            len(trace.steps),
            trace.worker_turns_used,
            trace.worker_turns_budget,
            trace.successful_tools,
            trace.failed_tools,
            len(trace.search_history),
        )
        if self._debug_trace:
            logger.info("run_trace_json %s", json.dumps(trace.to_dict(), ensure_ascii=False))
        else:
            logger.debug("run_trace_json %s", json.dumps(trace.to_dict(), ensure_ascii=False))
        return trace

    def extend_turn_budget(self, extra_turns: int) -> None:
        self._worker_turns_budget += max(0, extra_turns)

    @property
    def steps(self) -> list[ToolStep]:
        return list(self._steps)

    def build(self) -> RunTrace:
        return self._compile_trace(self._final_outcome or "in_progress")

    def _compile_trace(self, outcome: str) -> RunTrace:
        search_history: list[dict[str, Any]] = []
        successful_tools: list[str] = []
        failed_tools: list[str] = []

        for step in self._steps:
            if step.meta_tool == "search_tools":
                entry = {
                    "turn": step.turn,
                    **step.arguments_normalized,
                    **_search_summary(step.result_json),
                    "collapsed_from_context": step.collapsed_from_context,
                }
                search_history.append(entry)
                continue

            if not step.target_tool:
                continue
            if step.result_ok:
                successful_tools.append(step.target_tool)
            elif step.result_ok is False:
                failed_tools.append(step.target_tool)

        return RunTrace(
            user_id=self._user_id,
            user_message=self._user_message,
            started_at=self._started_at,
            steps=list(self._steps),
            worker_turns_used=self._worker_turns_used,
            worker_turns_budget=self._worker_turns_budget,
            final_outcome=outcome,
            search_history=search_history,
            successful_tools=successful_tools,
            failed_tools=failed_tools,
            repeated_patterns=_detect_repeated_patterns(self._steps),
            progress_summary=_build_progress_summary(successful_tools),
            coach_reviews=list(self._coach_reviews),
            worker_coach_replies=[reply.to_dict() for reply in get_coach_worker_replies()],
            checker_reviews=list(self._checker_reviews),
        )
