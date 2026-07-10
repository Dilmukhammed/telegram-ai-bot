from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent.coach_dialog import COACH_REPLY_TOOL_NAME
from agent.run_trace import RunTrace, ToolStep, _search_summary
from config import Settings

_STEP_SEP = "\n↓\n"

_CALENDAR_WRITE_TOOLS = frozenset(
    {
        "google.calendar.create_event",
        "google.calendar.quick_add_event",
        "google.calendar.patch_event",
        "google.calendar.update_event",
        "google.calendar.delete_event",
        "google.calendar.move_event",
    }
)

_SHEETS_ARG_TOOLS = frozenset(
    {
        "google.sheets.create_spreadsheet",
        "google.sheets.update_values",
        "google.sheets.append_values",
        "google.sheets.batch_update_values",
        "google.sheets.get_values",
        "google.sheets.read_sheet",
    }
)


@dataclass(frozen=True)
class CycleLogOptions:
    step_limit: int = 200
    max_chars: int = 30_000
    include_collapse_tags: bool = True
    worker_through_turn: int | None = None
    checker_through_turn: int | None = None
    include_checker_reviews: bool = True
    exclude_tools: frozenset[str] = frozenset({COACH_REPLY_TOOL_NAME})


def _truncate_text(text: str, limit: int) -> str:
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 1]}…"


def _parse_result_payload(result_json: str | None) -> dict[str, Any]:
    if not result_json:
        return {}
    try:
        payload = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _handler_result(payload: dict[str, Any]) -> dict[str, Any]:
    inner = payload.get("result")
    if isinstance(inner, dict) and ("tool_name" in payload or "ok" in payload):
        return inner
    return payload


def _archived_summary(payload: dict[str, Any], *, limit: int) -> str:
    if payload.get("archived") is not True:
        return ""
    return _truncate_text(str(payload.get("summary") or ""), limit)


# Result keys that carry "what happened" — surfaced before dumping the rest of the blob
# so the coach never loses the outcome/identity to truncation.
_PRIORITY_RESULT_KEYS = (
    "id",
    "spreadsheet_id",
    "spreadsheetId",
    "document_id",
    "documentId",
    "event_id",
    "message_id",
    "messageId",
    "thread_id",
    "file_id",
    "fileId",
    "folder_id",
    "name",
    "title",
    "filename",
    "path",
    "url",
    "webViewLink",
    "link",
    "status",
    "state",
    "deleted",
    "created",
    "updated",
    "sent",
    "count",
    "total",
    "updated_cells",
    "updated_range",
)


def _priority_result_fields(tool_result: dict[str, Any], *, limit: int) -> str:
    """Render identity/outcome keys first, then fill remaining budget with the rest."""
    priority_parts: list[str] = []
    seen: set[str] = set()
    for key in _PRIORITY_RESULT_KEYS:
        if key in tool_result and tool_result[key] not in (None, "", [], {}):
            value = tool_result[key]
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            priority_parts.append(f"{key}={value}")
            seen.add(key)
    priority_text = " ".join(priority_parts)
    rest = {k: v for k, v in tool_result.items() if k not in seen}
    if not priority_text:
        return _truncate_text(json.dumps(tool_result, ensure_ascii=False), limit)
    if not rest or len(priority_text) >= limit:
        return _truncate_text(priority_text, limit)
    rest_budget = limit - len(priority_text) - 1
    rest_text = _truncate_text(json.dumps(rest, ensure_ascii=False), rest_budget)
    return _truncate_text(f"{priority_text} {rest_text}", limit)


def _calendar_args(inner: dict[str, Any]) -> str:
    parts: list[str] = []
    if inner.get("text"):
        parts.append(f'text="{inner["text"]}"')
    if inner.get("event_id"):
        parts.append(f"event_id={inner['event_id']!r}")
    if inner.get("summary"):
        parts.append(f'summary="{inner["summary"]}"')
    for key in ("start", "end"):
        value = inner.get(key)
        if isinstance(value, dict):
            if value.get("datetime"):
                parts.append(f"{key}={value['datetime']}")
            elif value.get("date"):
                parts.append(f"{key}_date={value['date']}")
        elif value:
            parts.append(f"{key}={value!r}")
    return " ".join(parts)


def _calendar_result(tool_result: dict[str, Any]) -> str:
    event = tool_result.get("event")
    if isinstance(event, dict):
        bits = []
        if event.get("id"):
            bits.append(f"id={event['id']}")
        if event.get("summary"):
            bits.append(f'"{event["summary"]}"')
        if event.get("start"):
            bits.append(f"start={event['start']}")
        if event.get("end"):
            bits.append(f"end={event['end']}")
        if bits:
            return "event " + " ".join(bits)
    if tool_result.get("deleted"):
        return "deleted"
    if tool_result.get("created"):
        return "created"
    if tool_result.get("patched"):
        return "patched"
    return ""


def compact_step_args(step: ToolStep, *, limit: int) -> str:
    if step.meta_tool == "search_tools":
        args = step.arguments_normalized
        tags = args.get("tags") or []
        tag_text = f" tags={tags}" if tags else ""
        query = str(args.get("query", "")).strip()
        return _truncate_text(
            f'query="{query}" mode={args.get("mode")}{tag_text}',
            limit,
        )

    target = step.target_tool or "?"
    inner = step.arguments_normalized
    if target in _CALENDAR_WRITE_TOOLS:
        text = _calendar_args(inner)
        if text:
            return _truncate_text(text, limit)

    if target in _SHEETS_ARG_TOOLS:
        parts: list[str] = []
        title = str(inner.get("title") or "").strip()
        if title:
            parts.append(f'title="{title}"')
        sheet_titles = inner.get("sheet_titles")
        if isinstance(sheet_titles, list) and sheet_titles:
            preview = ", ".join(str(item) for item in sheet_titles[:6])
            suffix = "…" if len(sheet_titles) > 6 else ""
            parts.append(f"tabs=[{preview}{suffix}]")
        range_a1 = str(inner.get("range") or "").strip()
        if range_a1:
            parts.append(f"range={range_a1!r}")
        values = inner.get("values")
        if isinstance(values, list):
            rows = len(values)
            cols = len(values[0]) if values and isinstance(values[0], list) else 0
            parts.append(f"values={rows}x{cols}")
        if parts:
            return _truncate_text(" ".join(parts), limit)

    if target == "exa.web_search":
        query = str(inner.get("query") or "").strip()
        return _truncate_text(f'query="{query}"', limit)

    if target == "exa.web_fetch":
        urls = inner.get("urls")
        if not isinstance(urls, list):
            url = inner.get("url")
            urls = [url] if url else []
        url_text = ", ".join(str(u) for u in urls[:3])
        if len(urls) > 3:
            url_text += "…"
        return _truncate_text(f"urls=[{url_text}]", limit)

    if target == "skills.load":
        return _truncate_text(f'skill_id="{inner.get("skill_id", "")}"', limit)

    compact = json.dumps(inner, ensure_ascii=False, sort_keys=True)
    return _truncate_text(compact, limit)


def compact_step_result(step: ToolStep, *, limit: int) -> str:
    if not step.result_json:
        return ""

    payload = _parse_result_payload(step.result_json)
    target = step.target_tool or ""

    if step.meta_tool == "search_tools":
        summary = _search_summary(step.result_json)
        if summary.get("error"):
            return _truncate_text(f"FAIL: {summary['error']}", limit)
        top = summary.get("top_tools") or []
        if top:
            return _truncate_text(f"tools=[{', '.join(top[:5])}]", limit)
        return _truncate_text(f"count={summary.get('count', 0)}", limit)

    if step.result_ok is False:
        err = step.result_error or payload.get("error") or "failed"
        return _truncate_text(str(err), limit)

    archived = _archived_summary(payload, limit=limit)
    if archived:
        return archived

    tool_result = _handler_result(payload)
    if not isinstance(tool_result, dict):
        if payload.get("ok") is False:
            return _truncate_text(str(payload.get("error") or "failed"), limit)
        return _truncate_text(json.dumps(payload, ensure_ascii=False), limit)

    if target in _CALENDAR_WRITE_TOOLS:
        cal = _calendar_result(tool_result)
        if cal:
            return _truncate_text(cal, limit)

    if target == "exa.web_search":
        results = tool_result.get("results")
        if isinstance(results, list):
            hits = [
                _truncate_text(str(item.get("title") or ""), 60)
                for item in results[:3]
                if isinstance(item, dict) and item.get("title")
            ]
            if hits:
                return _truncate_text(f"hits: {'; '.join(hits)}", limit)

    if target.startswith("google.sheets."):
        bits: list[str] = []
        for key in ("updated_range", "updated_cells", "updated_rows", "table_range"):
            value = tool_result.get(key)
            if value is not None:
                bits.append(f"{key}={value}")
        if bits:
            return _truncate_text(" ".join(bits), limit)

    return _priority_result_fields(tool_result, limit=limit)


def _collapse_data_tag(
    step: ToolStep,
    *,
    current_turn: int,
    stale_steps: int,
    archive_min: int,
) -> str:
    payload = _parse_result_payload(step.result_json)
    if payload.get("archived") is True or step.collapsed_from_context:
        return " | data: collapsed"

    if step.meta_tool == "search_tools":
        return ""

    raw_len = len(step.result_json or "")
    if raw_len < archive_min:
        return ""

    turns_since = max(0, current_turn - step.turn)
    turns_left = stale_steps - turns_since
    if turns_left <= 0:
        return " | data: collapse due now"
    if turns_left == 1:
        return " | data: full ~1 turn until collapse"
    return f" | data: full ~{turns_left} turns until collapse"


def format_worker_step_line(
    step: ToolStep,
    *,
    step_limit: int,
    current_turn: int,
    stale_steps: int,
    archive_min: int,
    include_collapse_tags: bool,
) -> str:
    args_budget = max(80, step_limit * 2 // 5)
    result_budget = max(80, step_limit - args_budget - 48)

    name = "search_tools" if step.meta_tool == "search_tools" else (step.target_tool or "use_tool")
    status = "OK" if step.result_ok is not False else "FAIL"
    if step.result_ok is None:
        status = "?"

    args_text = compact_step_args(step, limit=args_budget)
    result_text = compact_step_result(step, limit=result_budget)

    line = f"[turn {step.turn}] worker → {name} {status}"
    if step.result_cached:
        line += " (cached)"
    line += f" | args: {args_text}"
    if result_text:
        line += f" → {result_text}"
    if include_collapse_tags:
        line += _collapse_data_tag(
            step,
            current_turn=current_turn,
            stale_steps=stale_steps,
            archive_min=archive_min,
        )
    return _truncate_text(line, step_limit + 80)


def format_checker_review_line(review: dict[str, Any]) -> str:
    tool = review.get("tool_name") or "?"
    turn = review.get("turn") or "?"
    overall = review.get("overall") or "unknown"
    verdicts = review.get("verdicts") or []
    parts: list[str] = []
    for item in verdicts:
        if not isinstance(item, dict):
            continue
        question_id = item.get("question_id") or "?"
        verdict = item.get("verdict") or "?"
        severity = item.get("severity") or ""
        tag = f"{question_id}={verdict}"
        if severity:
            tag = f"{tag}({severity})"
        parts.append(tag)
    verdict_text = " | ".join(parts) if parts else "(no verdicts)"
    return f"[turn {turn}] checker → {tool} | overall={overall} | {verdict_text}"


def _filter_steps(steps: list[ToolStep], options: CycleLogOptions) -> list[ToolStep]:
    filtered: list[ToolStep] = []
    for step in steps:
        if step.target_tool in options.exclude_tools:
            continue
        if options.worker_through_turn is not None and step.turn > options.worker_through_turn:
            continue
        filtered.append(step)
    return filtered


def _filter_checker_reviews(
    reviews: list[dict[str, Any]],
    *,
    options: CycleLogOptions,
) -> list[dict[str, Any]]:
    if not options.include_checker_reviews:
        return []
    filtered: list[dict[str, Any]] = []
    for review in reviews:
        turn = int(review.get("turn") or 0)
        if options.checker_through_turn is not None and turn > options.checker_through_turn:
            continue
        filtered.append(review)
    return filtered


def _interleave_worker_and_checker(
    steps: list[ToolStep],
    checker_reviews: list[dict[str, Any]],
    *,
    options: CycleLogOptions,
    settings: Settings,
) -> list[str]:
    stale_steps = settings.tool_result_collapse_stale_steps
    archive_min = settings.tool_result_archive_min_chars
    current_turn = max((step.turn for step in steps), default=0)

    pending_by_turn: dict[int, list[dict[str, Any]]] = {}
    for review in checker_reviews:
        turn = int(review.get("turn") or 0)
        pending_by_turn.setdefault(turn, []).append(review)
    consumed: dict[int, int] = {}

    lines: list[str] = []
    for step in steps:
        lines.append(
            format_worker_step_line(
                step,
                step_limit=options.step_limit,
                current_turn=current_turn,
                stale_steps=stale_steps,
                archive_min=archive_min,
                include_collapse_tags=options.include_collapse_tags,
            )
        )
        if step.meta_tool != "use_tool" or not step.target_tool:
            continue
        turn = step.turn
        bucket = pending_by_turn.get(turn, [])
        index = consumed.get(turn, 0)
        if index >= len(bucket):
            continue
        review = bucket[index]
        if review.get("tool_name") == step.target_tool:
            lines.append(format_checker_review_line(review))
            consumed[turn] = index + 1
    return lines


def build_cycle_status(
    trace: RunTrace,
    *,
    worker_through_turn: int | None = None,
    checker_through_turn: int | None = None,
) -> str:
    worker_steps = [
        step
        for step in trace.steps
        if step.target_tool != COACH_REPLY_TOOL_NAME
        and (worker_through_turn is None or step.turn <= worker_through_turn)
    ]
    checker_count = sum(
        1
        for review in trace.checker_reviews
        if checker_through_turn is None or int(review.get("turn") or 0) <= checker_through_turn
    )
    outcome = trace.final_outcome or "in_progress"
    return (
        f"status={outcome} | worker_steps={len(worker_steps)} | "
        f"checker_reviews={checker_count} | turns={trace.worker_turns_used}/{trace.worker_turns_budget}"
    )


def build_run_cycle_log(
    trace: RunTrace,
    *,
    settings: Settings,
    options: CycleLogOptions | None = None,
    header_extras: list[str] | None = None,
) -> str:
    options = options or CycleLogOptions(
        step_limit=max(120, settings.coach_max_field_chars),
        max_chars=max(1000, settings.coach_max_trace_chars),
    )
    steps = _filter_steps(trace.steps, options)
    checker_reviews = _filter_checker_reviews(trace.checker_reviews, options=options)

    header_parts = [
        f"User goal: {trace.user_message}",
        build_cycle_status(
            trace,
            worker_through_turn=options.worker_through_turn,
            checker_through_turn=options.checker_through_turn,
        ),
    ]
    if trace.failed_tools:
        header_parts.append(f"Failed tools: {', '.join(trace.failed_tools[-5:])}")
    if header_extras:
        header_parts.extend(header_extras)

    header_text = "\n".join(header_parts) + "\n\nCycle log:\n"
    max_chars = options.max_chars

    def render(selected: list[ToolStep], omitted: int) -> str:
        blocks = _interleave_worker_and_checker(
            selected,
            checker_reviews,
            options=options,
            settings=settings,
        )
        body = _STEP_SEP.join(blocks) if blocks else "(no tool calls yet)"
        note = ""
        if omitted > 0:
            note = (
                f"[… {omitted} earlier step(s) omitted to fit budget — their outcomes are "
                f"summarized in the header above; do NOT ask to redo completed work]\n"
            )
        return header_text + note + body

    text = render(steps, 0)
    if len(text) <= max_chars or not steps:
        if len(text) <= max_chars:
            return text
        return (
            text[: max_chars - 40].rstrip()
            + f"\n… [cycle log truncated at {max_chars} chars]"
        )

    # Keep the NEWEST steps at full detail and drop the oldest — the recent activity
    # ("what the worker is doing now") is what the coach most needs. Binary-search the
    # smallest start index whose suffix fits the budget.
    lo, hi = 0, len(steps)
    while lo < hi:
        mid = (lo + hi) // 2
        if len(render(steps[mid:], mid)) <= max_chars:
            hi = mid
        else:
            lo = mid + 1
    start = lo

    if start >= len(steps):
        # Even the single newest step overflows: show it hard-cut so "now" survives.
        text = render(steps[-1:], len(steps) - 1)
        return (
            text[: max_chars - 40].rstrip()
            + f"\n… [cycle log truncated at {max_chars} chars; {len(trace.steps)} steps total]"
        )
    return render(steps[start:], start)


def build_cycle_log_for_checker(
    *,
    user_message: str,
    steps: tuple[ToolStep, ...],
    checker_reviews: tuple[dict[str, Any], ...],
    current_step: ToolStep,
    settings: Settings,
    worker_turns_used: int = 0,
    worker_turns_budget: int = 0,
) -> str:
    """Snapshot for one checker call: worker through current turn, prior checker verdicts only."""
    partial = RunTrace(
        user_id=None,
        user_message=user_message,
        started_at=0.0,
        steps=list(steps),
        worker_turns_used=worker_turns_used,
        worker_turns_budget=worker_turns_budget,
        checker_reviews=list(checker_reviews),
    )
    options = CycleLogOptions(
        step_limit=max(120, min(settings.coach_max_field_chars, 240)),
        max_chars=min(settings.coach_max_trace_chars, 12_000),
        worker_through_turn=current_step.turn,
        checker_through_turn=max(0, current_step.turn - 1),
        include_checker_reviews=True,
    )
    return build_run_cycle_log(partial, settings=settings, options=options)
