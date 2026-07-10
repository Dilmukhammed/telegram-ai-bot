from __future__ import annotations

from tools.checker.common import (
    _USER_GOAL,
    call_evidence,
    has_confirm,
    is_read_tool,
    is_search_tool,
    is_write_tool,
    prior_calendar_event,
    prior_drive_file,
    prior_family_context,
    prior_gmail_context,
    prior_message_for_call,
    prior_spreadsheet_read,
    prior_task,
    prior_workspace_path,
    target_id_fields,
)
from tools.checker.live_refs import live_fetch_refs_for_spec
from tools.schema import ToolSpec
from tools.verification import SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARN, VerificationQuestion


def template_questions_for(spec: ToolSpec) -> tuple[VerificationQuestion, ...]:
    if is_read_tool(spec) or is_search_tool(spec):
        return _read_template(spec)
    if is_write_tool(spec):
        if has_confirm(spec):
            return _destructive_write_template(spec)
        if target_id_fields(spec):
            return _targeted_write_template(spec)
        return _generic_write_template(spec)
    return _generic_action_template(spec)


def _read_template(spec: ToolSpec) -> tuple[VerificationQuestion, ...]:
    call = call_evidence(spec)
    prior = prior_family_context(spec)
    return (
        VerificationQuestion(
            id="query_matches_intent",
            text="Do the query parameters match what the user asked to find or read?",
            severity=SEVERITY_CRITICAL,
            evidence=(call, _USER_GOAL, prior),
        ),
        VerificationQuestion(
            id="scope_appropriate",
            text="Is the read scope appropriate (not too narrow or overly broad)?",
            severity=SEVERITY_WARN,
            evidence=(call, _USER_GOAL),
        ),
        VerificationQuestion(
            id="result_useful",
            text="Does this read gather the data needed for the user's goal?",
            severity=SEVERITY_INFO,
            evidence=(call, _USER_GOAL, prior),
        ),
    )


def _generic_write_template(spec: ToolSpec) -> tuple[VerificationQuestion, ...]:
    call = call_evidence(spec)
    prior = prior_family_context(spec)
    live = live_fetch_refs_for_spec(spec)
    evidence = (call, _USER_GOAL, prior, *live)
    return (
        VerificationQuestion(
            id="action_matches_intent",
            text="Does this write action match what the user requested?",
            severity=SEVERITY_CRITICAL,
            evidence=evidence,
        ),
        VerificationQuestion(
            id="parameters_match_request",
            text="Are the write parameters aligned with the user's request?",
            severity=SEVERITY_CRITICAL,
            evidence=evidence,
        ),
        VerificationQuestion(
            id="side_effects_acceptable",
            text="Are the likely side effects acceptable for this request?",
            severity=SEVERITY_WARN,
            evidence=(call, _USER_GOAL),
        ),
    )


def _targeted_write_template(spec: ToolSpec) -> tuple[VerificationQuestion, ...]:
    call = call_evidence(spec)
    prior_refs = [_USER_GOAL, prior_family_context(spec)]
    if spec.name.startswith("google.gmail."):
        prior_refs.extend((prior_gmail_context(), prior_message_for_call()))
    elif spec.name.startswith("google.sheets."):
        prior_refs.append(prior_spreadsheet_read())
    elif spec.name.startswith("google.drive."):
        prior_refs.append(prior_drive_file())
    elif spec.name.startswith("google.calendar."):
        prior_refs.append(prior_calendar_event())
    elif spec.name.startswith("google.tasks."):
        prior_refs.append(prior_task())
    elif spec.name.startswith("workspace."):
        prior_refs.append(prior_workspace_path())

    live = live_fetch_refs_for_spec(spec)
    evidence = (call, *prior_refs, *live)
    questions: list[VerificationQuestion] = [
        VerificationQuestion(
            id="correct_target",
            text="Does the targeted resource/id match what the user meant?",
            severity=SEVERITY_CRITICAL,
            evidence=evidence,
        ),
    ]
    if live:
        questions.append(
            VerificationQuestion(
                id="target_resource_exists",
                text="Does the targeted resource exist (or for creates: was outcome verified)?",
                severity=SEVERITY_CRITICAL,
                evidence=evidence,
            )
        )
    questions.extend(
        (
            VerificationQuestion(
                id="action_matches_intent",
                text="Does this mutation match what the user asked to change?",
                severity=SEVERITY_CRITICAL,
                evidence=evidence,
            ),
            VerificationQuestion(
                id="fields_match_request",
                text="Are only the intended fields/parameters being changed?",
                severity=SEVERITY_WARN,
                evidence=(call, _USER_GOAL, *prior_refs),
            ),
        )
    )
    return tuple(questions)


def _destructive_write_template(spec: ToolSpec) -> tuple[VerificationQuestion, ...]:
    base = _targeted_write_template(spec) if target_id_fields(spec) else _generic_write_template(spec)
    call = call_evidence(spec)
    confirm_q = VerificationQuestion(
        id="destructive_confirmed",
        text="Was destructive action explicitly confirmed when required?",
        severity=SEVERITY_CRITICAL,
        evidence=(call, _USER_GOAL),
    )
    intent_q = VerificationQuestion(
        id="user_intent_destructive",
        text="Did the user intend a destructive/permanent action (delete/clear/trash)?",
        severity=SEVERITY_CRITICAL,
        evidence=(call, _USER_GOAL),
    )
    return (intent_q, confirm_q, *base)


def _generic_action_template(spec: ToolSpec) -> tuple[VerificationQuestion, ...]:
    call = call_evidence(spec)
    return (
        VerificationQuestion(
            id="action_matches_intent",
            text="Does this tool call match the user's request?",
            severity=SEVERITY_WARN,
            evidence=(call, _USER_GOAL, prior_family_context(spec)),
        ),
    )
