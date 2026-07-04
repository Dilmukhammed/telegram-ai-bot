from __future__ import annotations

import json
import logging
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from tools.coerce import normalize_use_tool_call

logger = logging.getLogger(__name__)

DEFAULT_RESULT_PREVIEW_CHARS = 400
DEFAULT_SUPERVISOR_TEXT_CHARS = 12_000


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

    def to_supervisor_text(self, max_chars: int = DEFAULT_SUPERVISOR_TEXT_CHARS) -> str:
        lines = [
            f"Goal: {self.user_message}",
            "",
            f"Progress: {self.progress_summary or 'unknown'}",
            f"Budget: {self.worker_turns_used}/{self.worker_turns_budget} worker turns used",
        ]
        if self.final_outcome:
            lines.append(f"Outcome: {self.final_outcome}")
        if self.repeated_patterns:
            lines.append(f"Patterns: {'; '.join(self.repeated_patterns)}")
        lines.append("")
        for step in self.steps:
            lines.append(_format_step_line(step))
        text = "\n".join(lines)
        if len(text) <= max_chars:
            return text
        truncated = text[: max_chars - 20].rstrip()
        return f"{truncated}\n… [trace truncated]"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [asdict(step) for step in self.steps]
        return payload


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


def _format_step_line(step: ToolStep) -> str:
    if step.meta_tool == "search_tools":
        args = step.arguments_normalized
        tags = args.get("tags") or []
        tag_text = f" tags={tags}" if tags else ""
        query = str(args.get("query", "")).strip()
        query_text = f' query="{query}"' if query else ""
        summary = _search_summary(step.result_json)
        if summary.get("top_tools"):
            result_text = f" → {summary['top_tools'][:3]}"
        else:
            result_text = f" → count={summary.get('count', 0)}"
        if summary.get("error"):
            result_text = f" → FAIL {summary['error']}"
        return f"Turn {step.turn}: search_tools mode={args.get('mode')}{tag_text}{query_text}{result_text}"

    target = step.target_tool or "use_tool"
    ok_text = "ok" if step.result_ok else "FAIL"
    if step.result_ok is None:
        ok_text = "?"
    err_text = f" — {step.result_error}" if step.result_error else ""
    return f"Turn {step.turn}: use_tool {target} {ok_text}{err_text}"


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

    @property
    def user_id(self) -> int | None:
        return self._user_id

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
    ) -> None:
        step = self._open_steps.pop((turn + 1, call_id), None)
        if step is None and self._steps:
            step = self._steps[-1]

        if step is None:
            return

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
        )
