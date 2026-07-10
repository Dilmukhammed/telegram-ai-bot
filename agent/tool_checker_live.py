from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from agent.run_trace import ToolStep
from agent.tool_checker_evidence import (
    _call_value_map,
    _compact_json,
    _handler_result,
    _parse_bound,
    _safe_json_load,
    datetimes_overlap,
)
from tools.context import RunContext
from tools.runtime import ToolRuntime
from tools.verification import (
    EVIDENCE_LIVE_FETCH,
    EvidenceSnippet,
    FETCH_CALENDAR_EVENT_EXISTS,
    FETCH_CALENDAR_SLOT_CONFLICTS,
    FETCH_DRIVE_FILE,
    FETCH_GMAIL_MESSAGE,
    FETCH_GMAIL_SENT_MESSAGE,
    FETCH_PDF_READ_METADATA,
    FETCH_SHEETS_RANGE_VALUES,
    FETCH_TASKS_GET_TASK,
    FETCH_WORKSPACE_STAT,
    FETCH_YANDEX_TRACK,
)

logger = logging.getLogger(__name__)


async def fetch_live_evidence_snippets(
    *,
    evidence_refs: tuple[Any, ...],
    current_step: ToolStep,
    user_id: int | None,
    runtime: ToolRuntime,
) -> dict[str, EvidenceSnippet]:
    if user_id is None:
        return {}

    snippets: dict[str, EvidenceSnippet] = {}
    seen_fetches: set[str] = set()
    for ref in evidence_refs:
        if ref.kind != EVIDENCE_LIVE_FETCH or not ref.fetch:
            continue
        if ref.fetch in seen_fetches:
            continue
        seen_fetches.add(ref.fetch)
        snippet = await _fetch_by_kind(
            ref.fetch,
            current_step=current_step,
            user_id=user_id,
            runtime=runtime,
            label=ref.label or ref.fetch,
        )
        if snippet is not None:
            snippets[snippet.label] = snippet
    return snippets


async def _fetch_by_kind(
    fetch_kind: str,
    *,
    current_step: ToolStep,
    user_id: int,
    runtime: ToolRuntime,
    label: str,
) -> EvidenceSnippet | None:
    if fetch_kind == FETCH_CALENDAR_SLOT_CONFLICTS:
        return await _fetch_calendar_slot_conflicts(
            current_step=current_step,
            user_id=user_id,
            runtime=runtime,
            label=label,
        )
    if fetch_kind == FETCH_CALENDAR_EVENT_EXISTS:
        return await _fetch_calendar_event_exists(
            current_step=current_step,
            user_id=user_id,
            runtime=runtime,
            label=label,
        )
    if fetch_kind == FETCH_GMAIL_MESSAGE:
        return await _fetch_gmail_message(
            current_step=current_step,
            user_id=user_id,
            runtime=runtime,
            label=label,
        )
    if fetch_kind == FETCH_GMAIL_SENT_MESSAGE:
        return await _fetch_gmail_sent_message(
            current_step=current_step,
            user_id=user_id,
            runtime=runtime,
            label=label,
        )
    if fetch_kind == FETCH_SHEETS_RANGE_VALUES:
        return await _fetch_sheets_range_values(
            current_step=current_step,
            user_id=user_id,
            runtime=runtime,
            label=label,
        )
    if fetch_kind == FETCH_DRIVE_FILE:
        return await _fetch_drive_file(
            current_step=current_step,
            user_id=user_id,
            runtime=runtime,
            label=label,
        )
    if fetch_kind == FETCH_TASKS_GET_TASK:
        return await _fetch_tasks_get_task(
            current_step=current_step,
            user_id=user_id,
            runtime=runtime,
            label=label,
        )
    if fetch_kind == FETCH_WORKSPACE_STAT:
        return await _fetch_workspace_stat(
            current_step=current_step,
            user_id=user_id,
            runtime=runtime,
            label=label,
        )
    if fetch_kind == FETCH_PDF_READ_METADATA:
        return await _fetch_pdf_read_metadata(
            current_step=current_step,
            user_id=user_id,
            runtime=runtime,
            label=label,
        )
    if fetch_kind == FETCH_YANDEX_TRACK:
        return await _fetch_yandex_track(
            current_step=current_step,
            user_id=user_id,
            runtime=runtime,
            label=label,
        )
    return None


async def _fetch_calendar_slot_conflicts(
    *,
    current_step: ToolStep,
    user_id: int,
    runtime: ToolRuntime,
    label: str,
) -> EvidenceSnippet | None:
    arguments = current_step.arguments_normalized
    calendar_id = str(arguments.get("calendar_id") or "primary")
    call_values = _call_value_map(current_step)
    start_text = call_values.get("start")
    end_text = call_values.get("end")
    if not start_text or not end_text:
        return EvidenceSnippet(
            label=label,
            kind=EVIDENCE_LIVE_FETCH,
            turn=None,
            tool_name="google.calendar.list_events",
            content=_compact_json(
                {
                    "fetch_ok": False,
                    "error": "could not determine event start/end from tool result",
                }
            ),
        )

    start = _parse_bound(start_text)
    end = _parse_bound(end_text)
    if start is None or end is None:
        return None

    created_event_id = _created_event_id(current_step)
    window_start = start - timedelta(minutes=1)
    window_end = end + timedelta(minutes=1)

    ctx = RunContext(user_id=user_id, turn=0, meta_tool="tool_checker")
    try:
        payload = await runtime.use_tool(
            "google.calendar.list_events",
            {
                "calendar_id": calendar_id,
                "time_min": window_start.isoformat(),
                "time_max": window_end.isoformat(),
                "max_results": 50,
                "single_events": True,
            },
            ctx=ctx,
        )
    except Exception as exc:
        logger.warning("tool_checker live list_events failed: %s", exc)
        return EvidenceSnippet(
            label=label,
            kind=EVIDENCE_LIVE_FETCH,
            turn=None,
            tool_name="google.calendar.list_events",
            content=_compact_json({"fetch_ok": False, "error": str(exc)}),
        )

    if not payload.get("ok"):
        return EvidenceSnippet(
            label=label,
            kind=EVIDENCE_LIVE_FETCH,
            turn=None,
            tool_name="google.calendar.list_events",
            content=_compact_json({"fetch_ok": False, "error": payload.get("error", "unknown")}),
        )

    handler_result = payload.get("result") or {}
    events = handler_result.get("events") if isinstance(handler_result, dict) else []
    conflicts = _find_conflicting_events(
        events if isinstance(events, list) else [],
        slot_start=start,
        slot_end=end,
        exclude_event_id=created_event_id,
    )
    body = {
        "fetch_ok": True,
        "calendar_id": calendar_id,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "created_event_id": created_event_id,
        "conflicting_events": conflicts,
        "conflict_count": len(conflicts),
    }
    return EvidenceSnippet(
        label=label,
        kind=EVIDENCE_LIVE_FETCH,
        turn=None,
        tool_name="google.calendar.list_events",
        content=_compact_json(body),
    )


def _created_event_id(step: ToolStep) -> str | None:
    result = _handler_result(_safe_json_load(step.result_json))
    if not isinstance(result, dict):
        return None
    event = result.get("event")
    if isinstance(event, dict) and event.get("id"):
        return str(event["id"])
    if result.get("event_id"):
        return str(result["event_id"])
    event_obj = result.get("event")
    if isinstance(event_obj, dict) and event_obj.get("id"):
        return str(event_obj["id"])
    arg_event_id = step.arguments_normalized.get("event_id")
    return str(arg_event_id) if arg_event_id else None


def _find_conflicting_events(
    events: list[Any],
    *,
    slot_start: datetime,
    slot_end: datetime,
    exclude_event_id: str | None,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "")
        if exclude_event_id and event_id == exclude_event_id:
            continue
        event_start = _parse_bound(event.get("start"))
        event_end = _parse_bound(event.get("end"))
        if event_start is None or event_end is None:
            continue
        if datetimes_overlap(event_start, event_end, slot_start, slot_end):
            conflicts.append(
                {
                    "id": event_id,
                    "summary": event.get("summary"),
                    "start": event.get("start"),
                    "end": event.get("end"),
                }
            )
    return conflicts


async def _checker_use_tool(
    runtime: ToolRuntime,
    *,
    user_id: int,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    ctx = RunContext(user_id=user_id, turn=0, meta_tool="tool_checker")
    try:
        payload = await runtime.use_tool(tool_name, arguments, ctx=ctx)
    except Exception as exc:
        logger.warning("tool_checker live %s failed: %s", tool_name, exc)
        return {"fetch_ok": False, "error": str(exc), "tool_name": tool_name}
    if not isinstance(payload, dict) or not payload.get("ok"):
        return {
            "fetch_ok": False,
            "error": (payload or {}).get("error", "unknown") if isinstance(payload, dict) else "unknown",
            "tool_name": tool_name,
        }
    return {"fetch_ok": True, "tool_name": tool_name, "result": payload.get("result")}


def _fetch_error_snippet(
    *,
    label: str,
    tool_name: str,
    body: dict[str, Any],
) -> EvidenceSnippet:
    return EvidenceSnippet(
        label=label,
        kind=EVIDENCE_LIVE_FETCH,
        turn=None,
        tool_name=tool_name,
        content=_compact_json(body),
    )


async def _fetch_calendar_event_exists(
    *,
    current_step: ToolStep,
    user_id: int,
    runtime: ToolRuntime,
    label: str,
) -> EvidenceSnippet | None:
    arguments = current_step.arguments_normalized
    event_id = arguments.get("event_id")
    if not event_id:
        return None
    calendar_id = str(arguments.get("calendar_id") or "primary")
    payload = await _checker_use_tool(
        runtime,
        user_id=user_id,
        tool_name="google.calendar.get_event",
        arguments={"calendar_id": calendar_id, "event_id": str(event_id)},
    )
    exists = bool(payload.get("fetch_ok") and isinstance(payload.get("result"), dict))
    body = {
        **payload,
        "calendar_id": calendar_id,
        "event_id": str(event_id),
        "exists": exists,
    }
    return EvidenceSnippet(
        label=label,
        kind=EVIDENCE_LIVE_FETCH,
        turn=None,
        tool_name="google.calendar.get_event",
        content=_compact_json(body),
    )


async def _fetch_gmail_message(
    *,
    current_step: ToolStep,
    user_id: int,
    runtime: ToolRuntime,
    label: str,
) -> EvidenceSnippet | None:
    message_id = current_step.arguments_normalized.get("message_id")
    if not message_id:
        return None
    payload = await _checker_use_tool(
        runtime,
        user_id=user_id,
        tool_name="google.gmail.get_message",
        arguments={"message_id": str(message_id)},
    )
    exists = bool(payload.get("fetch_ok") and isinstance(payload.get("result"), dict))
    body = {**payload, "message_id": str(message_id), "exists": exists}
    return EvidenceSnippet(
        label=label,
        kind=EVIDENCE_LIVE_FETCH,
        turn=None,
        tool_name="google.gmail.get_message",
        content=_compact_json(body),
    )


async def _fetch_gmail_sent_message(
    *,
    current_step: ToolStep,
    user_id: int,
    runtime: ToolRuntime,
    label: str,
) -> EvidenceSnippet | None:
    result = _handler_result(_safe_json_load(current_step.result_json))
    if not isinstance(result, dict):
        return None
    message_id = result.get("message_id")
    if not message_id:
        return EvidenceSnippet(
            label=label,
            kind=EVIDENCE_LIVE_FETCH,
            turn=None,
            tool_name="google.gmail.get_message",
            content=_compact_json(
                {
                    "fetch_ok": False,
                    "error": "no message_id in send result",
                }
            ),
        )
    payload = await _checker_use_tool(
        runtime,
        user_id=user_id,
        tool_name="google.gmail.get_message",
        arguments={"message_id": str(message_id), "format": "metadata"},
    )
    exists = bool(payload.get("fetch_ok") and isinstance(payload.get("result"), dict))
    body = {**payload, "sent_message_id": str(message_id), "exists": exists}
    return EvidenceSnippet(
        label=label,
        kind=EVIDENCE_LIVE_FETCH,
        turn=None,
        tool_name="google.gmail.get_message",
        content=_compact_json(body),
    )


async def _fetch_sheets_range_values(
    *,
    current_step: ToolStep,
    user_id: int,
    runtime: ToolRuntime,
    label: str,
) -> EvidenceSnippet | None:
    arguments = current_step.arguments_normalized
    spreadsheet_id = arguments.get("spreadsheet_id")
    if not spreadsheet_id:
        return None
    range_value = arguments.get("range")
    if not range_value and isinstance(arguments.get("data"), list):
        first = arguments["data"][0] if arguments["data"] else {}
        if isinstance(first, dict):
            range_value = first.get("range")
    if not range_value and isinstance(arguments.get("ranges"), list) and arguments["ranges"]:
        range_value = arguments["ranges"][0]
    if not range_value:
        range_value = "Sheet1!A1:Z100"
    payload = await _checker_use_tool(
        runtime,
        user_id=user_id,
        tool_name="google.sheets.get_values",
        arguments={"spreadsheet_id": str(spreadsheet_id), "range": str(range_value)},
    )
    body = {
        **payload,
        "spreadsheet_id": str(spreadsheet_id),
        "range": str(range_value),
    }
    return EvidenceSnippet(
        label=label,
        kind=EVIDENCE_LIVE_FETCH,
        turn=None,
        tool_name="google.sheets.get_values",
        content=_compact_json(body),
    )


async def _fetch_drive_file(
    *,
    current_step: ToolStep,
    user_id: int,
    runtime: ToolRuntime,
    label: str,
) -> EvidenceSnippet | None:
    file_id = current_step.arguments_normalized.get("file_id")
    if not file_id:
        result = _handler_result(_safe_json_load(current_step.result_json))
        if isinstance(result, dict):
            file_id = result.get("file_id") or result.get("id")
    if not file_id:
        return None
    payload = await _checker_use_tool(
        runtime,
        user_id=user_id,
        tool_name="google.drive.get_file",
        arguments={"file_id": str(file_id)},
    )
    exists = bool(payload.get("fetch_ok") and isinstance(payload.get("result"), dict))
    body = {**payload, "file_id": str(file_id), "exists": exists}
    return EvidenceSnippet(
        label=label,
        kind=EVIDENCE_LIVE_FETCH,
        turn=None,
        tool_name="google.drive.get_file",
        content=_compact_json(body),
    )


async def _fetch_tasks_get_task(
    *,
    current_step: ToolStep,
    user_id: int,
    runtime: ToolRuntime,
    label: str,
) -> EvidenceSnippet | None:
    arguments = current_step.arguments_normalized
    task_id = arguments.get("task_id")
    tasklist_id = arguments.get("tasklist_id")
    if not task_id or not tasklist_id:
        result = _handler_result(_safe_json_load(current_step.result_json))
        if isinstance(result, dict):
            if not tasklist_id:
                tasklist_id = result.get("tasklist_id")
            if not task_id:
                task_obj = result.get("task")
                if isinstance(task_obj, dict):
                    task_id = task_obj.get("id")
                if not task_id:
                    task_id = result.get("task_id")
    if not task_id:
        return None
    fetch_args: dict[str, str] = {"task_id": str(task_id)}
    if tasklist_id:
        fetch_args["tasklist_id"] = str(tasklist_id)
    payload = await _checker_use_tool(
        runtime,
        user_id=user_id,
        tool_name="google.tasks.get_task",
        arguments=fetch_args,
    )
    exists = bool(payload.get("fetch_ok") and isinstance(payload.get("result"), dict))
    body = {
        **payload,
        "task_id": str(task_id),
        "tasklist_id": str(tasklist_id) if tasklist_id else None,
        "exists": exists,
    }
    return EvidenceSnippet(
        label=label,
        kind=EVIDENCE_LIVE_FETCH,
        turn=None,
        tool_name="google.tasks.get_task",
        content=_compact_json(body),
    )


async def _fetch_workspace_stat(
    *,
    current_step: ToolStep,
    user_id: int,
    runtime: ToolRuntime,
    label: str,
) -> EvidenceSnippet | None:
    arguments = current_step.arguments_normalized
    path = arguments.get("path") or arguments.get("to_path")
    if not path:
        result = _handler_result(_safe_json_load(current_step.result_json))
        if isinstance(result, dict):
            path = result.get("path") or result.get("to_path") or result.get("dest")
    if not path:
        return None
    payload = await _checker_use_tool(
        runtime,
        user_id=user_id,
        tool_name="workspace.stat",
        arguments={"path": str(path)},
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    exists = bool(payload.get("fetch_ok") and isinstance(result, dict) and not result.get("error"))
    body = {**payload, "path": str(path), "exists": exists}
    return EvidenceSnippet(
        label=label,
        kind=EVIDENCE_LIVE_FETCH,
        turn=None,
        tool_name="workspace.stat",
        content=_compact_json(body),
    )


async def _fetch_pdf_read_metadata(
    *,
    current_step: ToolStep,
    user_id: int,
    runtime: ToolRuntime,
    label: str,
) -> EvidenceSnippet | None:
    arguments = current_step.arguments_normalized
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    if not file_ref:
        result = _handler_result(_safe_json_load(current_step.result_json))
        if isinstance(result, dict):
            file_ref = result.get("file_ref")
            if not file_ref:
                refs = result.get("file_refs")
                if isinstance(refs, list) and refs:
                    file_ref = refs[0]
    if file_ref:
        fetch_args = {"file_ref": str(file_ref)}
    elif path:
        fetch_args = {"path": str(path)}
    else:
        return None
    payload = await _checker_use_tool(
        runtime,
        user_id=user_id,
        tool_name="pdf.read_metadata",
        arguments=fetch_args,
    )
    exists = bool(payload.get("fetch_ok") and isinstance(payload.get("result"), dict))
    body = {**payload, "file_ref": str(file_ref) if file_ref else None, "path": str(path) if path else None, "exists": exists}
    return EvidenceSnippet(
        label=label,
        kind=EVIDENCE_LIVE_FETCH,
        turn=None,
        tool_name="pdf.read_metadata",
        content=_compact_json(body),
    )


async def _fetch_yandex_track(
    *,
    current_step: ToolStep,
    user_id: int,
    runtime: ToolRuntime,
    label: str,
) -> EvidenceSnippet | None:
    arguments = current_step.arguments_normalized
    track_id = arguments.get("track_id") or arguments.get("track_ids")
    if not track_id:
        result = _handler_result(_safe_json_load(current_step.result_json))
        if isinstance(result, dict):
            track_id = result.get("track_id")
    if not track_id:
        return None
    track_ids = str(track_id).split(":")[0] if ":" in str(track_id) else str(track_id)
    payload = await _checker_use_tool(
        runtime,
        user_id=user_id,
        tool_name="yandex.music.tracks",
        arguments={"track_ids": track_ids},
    )
    exists = bool(payload.get("fetch_ok") and isinstance(payload.get("result"), dict))
    body = {**payload, "track_id": str(track_id), "track_ids": track_ids, "exists": exists}
    return EvidenceSnippet(
        label=label,
        kind=EVIDENCE_LIVE_FETCH,
        turn=None,
        tool_name="yandex.music.tracks",
        content=_compact_json(body),
    )


def rule_verdict_for_resource_exists(
    *,
    question_id: str,
    severity: str,
    snippet: EvidenceSnippet | None,
) -> Any | None:
    from tools.verification import QuestionVerdict, VERDICT_FAIL, VERDICT_PASS, VERDICT_UNKNOWN

    if question_id != "target_resource_exists" or snippet is None:
        return None
    try:
        payload = json.loads(snippet.content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if not payload.get("fetch_ok"):
        return QuestionVerdict(
            question_id=question_id,
            verdict=VERDICT_UNKNOWN,
            severity=severity,
            reason="Could not fetch live state to verify target resource",
            evidence_used=[snippet.label],
            rule_based=True,
        )
    if "exists" not in payload:
        return QuestionVerdict(
            question_id=question_id,
            verdict=VERDICT_UNKNOWN,
            severity=severity,
            reason="Live fetch did not report an existence signal for this resource",
            evidence_used=[snippet.label],
            rule_based=True,
        )
    if payload.get("exists"):
        return QuestionVerdict(
            question_id=question_id,
            verdict=VERDICT_PASS,
            severity=severity,
            reason="Target resource exists according to live fetch",
            evidence_used=[snippet.label],
            rule_based=True,
        )
    return QuestionVerdict(
        question_id=question_id,
        verdict=VERDICT_FAIL,
        severity=severity,
        reason="Target resource not found according to live fetch",
        evidence_used=[snippet.label],
        rule_based=True,
    )


def rule_verdict_for_slot_conflicts(
    *,
    question_id: str,
    severity: str,
    snippet: EvidenceSnippet | None,
) -> Any | None:
    from tools.verification import QuestionVerdict, VERDICT_FAIL, VERDICT_PASS, VERDICT_UNKNOWN

    if snippet is None:
        return None
    try:
        payload = json.loads(snippet.content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if not payload.get("fetch_ok"):
        return QuestionVerdict(
            question_id=question_id,
            verdict=VERDICT_UNKNOWN,
            severity=severity,
            reason="Could not fetch live calendar state to verify slot availability",
            evidence_used=[snippet.label],
            rule_based=True,
        )
    conflicts = payload.get("conflicting_events") or []
    if conflicts:
        summaries = ", ".join(
            str(item.get("summary") or item.get("id") or "?") for item in conflicts[:3]
        )
        return QuestionVerdict(
            question_id=question_id,
            verdict=VERDICT_FAIL,
            severity=severity,
            reason=f"Overlapping events in slot: {summaries}",
            evidence_used=[snippet.label],
            rule_based=True,
        )
    return QuestionVerdict(
        question_id=question_id,
        verdict=VERDICT_PASS,
        severity=severity,
        reason="No overlapping events besides the created/updated one",
        evidence_used=[snippet.label],
        rule_based=True,
    )
