from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any

from zoneinfo import ZoneInfo

from agent.run_trace import ToolStep
from tools.builtins.google.datetime_utils import resolve_timezone
from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_LIVE_FETCH,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_RUNTIME,
    EVIDENCE_USER_GOAL,
    CheckerRuntimeContext,
    EvidenceRef,
    EvidenceSnippet,
    QuestionVerdict,
    ResolvedQuestion,
    VerificationQuestion,
)

_CALL_REF_PREFIX = "$call."
_TIME_OVERLAP_RE = re.compile(r"^\$call\.(\w+)\.\.\$call\.(\w+)$")
_MAX_SNIPPET_CHARS = 4000


@dataclass(frozen=True)
class ResolvedCheckerBundle:
    tool_name: str
    turn: int
    step_index: int
    questions: tuple[ResolvedQuestion, ...]

    def rule_based_verdicts(self) -> list[QuestionVerdict]:
        verdicts: list[QuestionVerdict] = []
        for resolved in self.questions:
            verdict = resolved.rule_based_verdict()
            if verdict is not None:
                verdicts.append(verdict)
        return verdicts


class EvidenceResolver:
    def resolve_bundle(
        self,
        *,
        questions: tuple[VerificationQuestion, ...],
        current_step: ToolStep,
        prior_steps: tuple[ToolStep, ...],
        runtime: CheckerRuntimeContext,
        user_message: str,
        live_snippets: dict[str, EvidenceSnippet] | None = None,
    ) -> ResolvedCheckerBundle:
        live_snippets = live_snippets or {}
        resolved_questions = tuple(
            self.resolve_question(
                question=question,
                current_step=current_step,
                prior_steps=prior_steps,
                runtime=runtime,
                user_message=user_message,
                live_snippets=live_snippets,
            )
            for question in questions
        )
        return ResolvedCheckerBundle(
            tool_name=current_step.target_tool or "",
            turn=current_step.turn,
            step_index=len(prior_steps),
            questions=resolved_questions,
        )

    def resolve_question(
        self,
        *,
        question: VerificationQuestion,
        current_step: ToolStep,
        prior_steps: tuple[ToolStep, ...],
        runtime: CheckerRuntimeContext,
        user_message: str,
        live_snippets: dict[str, EvidenceSnippet] | None = None,
    ) -> ResolvedQuestion:
        live_snippets = live_snippets or {}
        snippets: list[EvidenceSnippet] = []
        missing_required: list[str] = []

        for ref in question.evidence:
            resolved = self._resolve_ref(
                ref=ref,
                current_step=current_step,
                prior_steps=prior_steps,
                runtime=runtime,
                user_message=user_message,
                live_snippets=live_snippets,
            )
            if resolved:
                snippets.extend(resolved)
            elif ref.required and not ref.optional:
                missing_required.append(ref.label or ref.kind)

        return ResolvedQuestion(
            question=question,
            snippets=snippets,
            missing_required=missing_required,
        )

    def _resolve_ref(
        self,
        *,
        ref: EvidenceRef,
        current_step: ToolStep,
        prior_steps: tuple[ToolStep, ...],
        runtime: CheckerRuntimeContext,
        user_message: str,
        live_snippets: dict[str, EvidenceSnippet],
    ) -> list[EvidenceSnippet]:
        if ref.kind == EVIDENCE_LIVE_FETCH:
            snippet = live_snippets.get(ref.label or ref.fetch)
            return [snippet] if snippet is not None else []
        if ref.kind == EVIDENCE_CALL:
            return [self._call_snippet(ref, current_step)]
        if ref.kind == EVIDENCE_USER_GOAL:
            if not user_message.strip():
                return []
            return [
                EvidenceSnippet(
                    label=ref.label or EVIDENCE_USER_GOAL,
                    kind=EVIDENCE_USER_GOAL,
                    turn=None,
                    tool_name=None,
                    content=user_message.strip(),
                )
            ]
        if ref.kind == EVIDENCE_RUNTIME:
            return [
                EvidenceSnippet(
                    label=ref.label or EVIDENCE_RUNTIME,
                    kind=EVIDENCE_RUNTIME,
                    turn=None,
                    tool_name=None,
                    content=_compact_json(runtime.to_snippet()),
                )
            ]
        if ref.kind == EVIDENCE_PRIOR_TOOL:
            return self._prior_tool_snippets(ref, current_step, prior_steps)
        return []

    def _call_snippet(self, ref: EvidenceRef, current_step: ToolStep) -> EvidenceSnippet:
        payload = _extract_call_fields(current_step, ref.fields)
        return EvidenceSnippet(
            label=ref.label or EVIDENCE_CALL,
            kind=EVIDENCE_CALL,
            turn=current_step.turn,
            tool_name=current_step.target_tool,
            content=_compact_json(payload),
        )

    def _prior_tool_snippets(
        self,
        ref: EvidenceRef,
        current_step: ToolStep,
        prior_steps: tuple[ToolStep, ...],
    ) -> list[EvidenceSnippet]:
        candidates = [
            step
            for step in prior_steps
            if step.meta_tool == "use_tool"
            and step.target_tool
            and _tool_name_matches(step.target_tool, ref)
            and step.result_ok is not False
        ]
        if ref.max_age_steps is not None:
            candidates = candidates[-ref.max_age_steps :]

        call_values = _call_value_map(current_step)
        matched: list[ToolStep] = []
        for step in reversed(candidates):
            if not _match_step(step, ref.match, call_values):
                continue
            if ref.time_overlap and not _time_overlap_match(step, ref.time_overlap, call_values):
                continue
            matched.append(step)
            break

        if not matched:
            return []

        step = matched[0]
        content = step.result_json.strip() or step.result_preview
        if step.arguments_normalized:
            content = _compact_json(
                {
                    "arguments": step.arguments_normalized,
                    "result": _safe_json_load(content),
                }
            )
        return [
            EvidenceSnippet(
                label=ref.label or step.target_tool or EVIDENCE_PRIOR_TOOL,
                kind=EVIDENCE_PRIOR_TOOL,
                turn=step.turn,
                tool_name=step.target_tool,
                content=_truncate(content),
            )
        ]


def _tool_name_matches(tool_name: str, ref: EvidenceRef) -> bool:
    if ref.tool_names and tool_name in ref.tool_names:
        return True
    if ref.tool_name_pattern and fnmatch.fnmatchcase(tool_name, ref.tool_name_pattern):
        return True
    return not ref.tool_names and not ref.tool_name_pattern


def _call_value_map(step: ToolStep) -> dict[str, Any]:
    arguments = step.arguments_normalized
    values = dict(arguments)
    values.setdefault("calendar_id", "primary")
    start_bounds = _event_bounds(arguments)
    end_from_args = start_bounds[1]
    start_from_args = start_bounds[0]
    if start_from_args is None or end_from_args is None:
        result_start, result_end = _event_bounds_from_result(
            _handler_result(_safe_json_load(step.result_json))
        )
        if start_from_args is None:
            start_from_args = result_start
        if end_from_args is None:
            end_from_args = result_end
    if start_from_args is not None:
        values["start"] = start_from_args.isoformat()
    if end_from_args is not None:
        values["end"] = end_from_args.isoformat()
    return values


def _event_bounds_from_result(result: Any) -> tuple[datetime | None, datetime | None]:
    if not isinstance(result, dict):
        return None, None
    event = result.get("event")
    if not isinstance(event, dict):
        return None, None
    start = _parse_bound(event.get("start"))
    end = _parse_bound(event.get("end"))
    return start, end


def _resolve_match_value(value: str, call_values: dict[str, Any]) -> Any:
    if value.startswith(_CALL_REF_PREFIX):
        key = value[len(_CALL_REF_PREFIX) :]
        return call_values.get(key)
    return value


def _match_step(
    step: ToolStep,
    match_rules: tuple[tuple[str, str], ...],
    call_values: dict[str, Any],
) -> bool:
    if not match_rules:
        return True

    step_args = step.arguments_normalized
    step_result = _safe_json_load(step.result_json)

    for field_name, expected in match_rules:
        expected_value = _resolve_match_value(expected, call_values)
        if expected_value is None:
            return False

        if field_name == "calendar_id":
            if not _calendar_id_matches(step_args, step_result, str(expected_value)):
                return False
            continue

        actual = step_args.get(field_name)
        if actual is None and isinstance(step_result, dict):
            actual = step_result.get(field_name)
        if str(actual) != str(expected_value):
            return False

    return True


def _calendar_id_matches(
    step_args: dict[str, Any],
    step_result: Any,
    calendar_id: str,
) -> bool:
    calendar_ids = step_args.get("calendar_ids")
    if calendar_ids is None:
        calendar_ids = [step_args.get("calendar_id", "primary")]
    if isinstance(calendar_ids, str):
        calendar_ids = [calendar_ids]

    normalized_ids = {str(item) for item in calendar_ids}
    if calendar_id in normalized_ids:
        return True

    if isinstance(step_result, dict):
        calendars = step_result.get("calendars")
        if isinstance(calendars, dict) and calendar_id in calendars:
            return True
        if step_result.get("calendar_id") == calendar_id:
            return True

    return calendar_id == "primary" and "primary" in normalized_ids


def _time_overlap_match(
    prior_step: ToolStep,
    overlap_spec: str,
    call_values: dict[str, Any],
) -> bool:
    match = _TIME_OVERLAP_RE.match(overlap_spec.strip())
    if not match:
        return True

    start_key, end_key = match.group(1), match.group(2)
    event_start = _parse_bound(call_values.get(start_key))
    event_end = _parse_bound(call_values.get(end_key))
    if event_start is None or event_end is None:
        return True

    prior_args = prior_step.arguments_normalized
    window_start = _parse_bound(prior_args.get("time_min"))
    window_end = _parse_bound(prior_args.get("time_max"))
    if window_start is None or window_end is None:
        return True

    return window_start <= event_start and window_end >= event_end


def _event_bounds(arguments: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    start = _parse_event_time(arguments.get("start"), arguments.get("time_zone"))
    end = _parse_event_time(arguments.get("end"), arguments.get("time_zone"))
    return start, end


def _parse_event_time(value: Any, default_tz: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _parse_bound(value)
    if not isinstance(value, dict):
        return None

    tz_name = value.get("time_zone") or default_tz
    if value.get("datetime"):
        parsed = _parse_bound(str(value["datetime"]))
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_resolve_tz(tz_name))
            return parsed
    if value.get("date"):
        day = date.fromisoformat(str(value["date"]))
        return datetime.combine(day, time.min, tzinfo=_resolve_tz(tz_name))
    return None


def _resolve_tz(tz_name: Any) -> timezone | ZoneInfo:
    # Falls back to the bot timezone (not UTC) so naive datetimes here mean the
    # same instant as in build_event_time / parse_iso_datetime.
    return resolve_timezone(str(tz_name).strip() if tz_name else None)


def _normalize_for_compare(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=_resolve_tz(None))
    return value.astimezone(timezone.utc)


def datetimes_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    a_start, a_end = _normalize_for_compare(start_a), _normalize_for_compare(end_a)
    b_start, b_end = _normalize_for_compare(start_b), _normalize_for_compare(end_b)
    return a_start < b_end and a_end > b_start


def _parse_bound(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_call_fields(step: ToolStep, fields: tuple[str, ...]) -> dict[str, Any]:
    args = dict(step.arguments_normalized)
    handler_result = _handler_result(_safe_json_load(step.result_json))
    envelope = _safe_json_load(step.result_json)
    payload: dict[str, Any] = {"arguments": {}}
    selected_args: dict[str, Any] = {}
    for field_name in fields:
        if field_name in args:
            selected_args[field_name] = args[field_name]
        elif field_name in handler_result:
            selected_args[field_name] = handler_result[field_name]
        elif field_name == "event" and isinstance(handler_result.get("event"), dict):
            selected_args[field_name] = handler_result["event"]
    payload["arguments"] = selected_args
    if isinstance(envelope, dict):
        payload["result_ok"] = envelope.get("ok", step.result_ok)
        if envelope.get("error"):
            payload["error"] = envelope.get("error")
    else:
        payload["result_ok"] = step.result_ok
    if isinstance(handler_result.get("event"), dict):
        payload["event"] = handler_result["event"]
    return payload


def _safe_json_load(raw: str) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def _handler_result(payload: Any) -> dict[str, Any]:
    """Unwrap use_tool envelope stored in RunTrace tool result JSON."""
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("result")
    if isinstance(inner, dict) and ("tool_name" in payload or "ok" in payload):
        return inner
    return payload


def _compact_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _truncate(text: str, max_chars: int = _MAX_SNIPPET_CHARS) -> str:
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= max_chars:
        return collapsed
    return f"{collapsed[: max_chars - 1]}…"


def format_bundle_for_debug(
    bundle: ResolvedCheckerBundle,
    *,
    live_snippets: dict[str, EvidenceSnippet] | None = None,
    max_chars: int = _MAX_SNIPPET_CHARS,
) -> str:
    live_snippets = live_snippets or {}
    payload = {
        "tool_name": bundle.tool_name,
        "turn": bundle.turn,
        "step_index": bundle.step_index,
        "questions": [
            {
                "id": resolved.question.id,
                "severity": resolved.question.severity,
                "text": resolved.question.text,
                "missing_required": list(resolved.missing_required),
                "snippets": [
                    {
                        "label": snippet.label,
                        "kind": snippet.kind,
                        "turn": snippet.turn,
                        "tool_name": snippet.tool_name,
                        "content": _truncate(snippet.content, max_chars=max_chars),
                    }
                    for snippet in resolved.snippets
                ],
            }
            for resolved in bundle.questions
        ],
        "live_snippets": {
            label: {
                "kind": snippet.kind,
                "tool_name": snippet.tool_name,
                "content": _truncate(snippet.content, max_chars=max_chars),
            }
            for label, snippet in live_snippets.items()
        },
    }
    return _compact_json(payload)
