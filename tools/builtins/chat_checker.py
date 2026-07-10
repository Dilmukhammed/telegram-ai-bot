from __future__ import annotations

from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_USER_GOAL,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    EvidenceRef,
    VerificationQuestion,
)

_USER_GOAL = EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal")

_PRIOR_CHAT_SEARCH = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("chat.search", "chat.sessions.list"),
    optional=True,
    max_age_steps=12,
    label="prior_chat_discovery",
)


def _call(label: str, *fields: str) -> EvidenceRef:
    return EvidenceRef(kind=EVIDENCE_CALL, fields=fields, label=label)


CHAT_SEARCH_QUESTIONS = (
    VerificationQuestion(
        id="query_matches_recall_intent",
        text="Does query target what the user asked to recall from past chats?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("search_call", "query", "session_id", "date"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="scope_not_too_broad",
        text=(
            "If the user named a date or session, are session_id/date filters set "
            "instead of searching the whole history blindly?"
        ),
        severity=SEVERITY_WARN,
        evidence=(_call("search_call", "session_id", "date"), _USER_GOAL, _PRIOR_CHAT_SEARCH),
    ),
    VerificationQuestion(
        id="follow_up_read_plan",
        text="After search hits, will chat.turns.read or chat.session.summary follow for needed detail?",
        severity=SEVERITY_INFO,
        evidence=(_call("search_call", "query", "top_k"), _USER_GOAL),
    ),
)

CHAT_TURNS_READ_QUESTIONS = (
    VerificationQuestion(
        id="session_from_prior_hit",
        text="Is session_id taken from chat.search or chat.sessions.list (not invented)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("read_call", "session_id", "turns"), _PRIOR_CHAT_SEARCH, _USER_GOAL),
    ),
    VerificationQuestion(
        id="turns_match_request",
        text="Do requested turns cover the user question (not the whole session dump)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("read_call", "turns"), _USER_GOAL),
    ),
)

CHAT_SESSION_SUMMARY_QUESTIONS = (
    VerificationQuestion(
        id="session_id_known",
        text="Is session_id from prior chat.search/sessions.list for the session being summarized?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("summary_call", "session_id"), _PRIOR_CHAT_SEARCH, _USER_GOAL),
    ),
)

CHAT_SESSIONS_LIST_QUESTIONS = (
    VerificationQuestion(
        id="list_before_deep_read",
        text="Is listing sessions appropriate before reading turns (discovery step)?",
        severity=SEVERITY_INFO,
        evidence=(_call("list_call", "status", "date", "limit"), _USER_GOAL),
    ),
)

CHAT_PERIODS_LIST_QUESTIONS = (
    VerificationQuestion(
        id="period_list_for_overview",
        text="Is listing period digests appropriate for a day/week/month overview request?",
        severity=SEVERITY_INFO,
        evidence=(_call("periods_list", "period_type", "limit"), _USER_GOAL),
    ),
)

CHAT_PERIOD_SUMMARY_QUESTIONS = (
    VerificationQuestion(
        id="period_key_matches_user_time",
        text=(
            "Do period_type and period_key match the user's requested time window "
            "(day=YYYY-MM-DD, week=YYYY-Www ISO, month=YYYY-MM) in bot timezone?"
        ),
        severity=SEVERITY_CRITICAL,
        evidence=(_call("period_summary", "period_type", "period_key"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="period_before_session_dive",
        text=(
            "For broad 'what did we do yesterday/this week/month' questions, "
            "is chat.period.summary used before dumping many session turns?"
        ),
        severity=SEVERITY_WARN,
        evidence=(_call("period_summary", "period_type", "period_key"), _USER_GOAL),
    ),
)

CHAT_CHECKER_QUESTIONS_BY_TOOL: dict[str, tuple[VerificationQuestion, ...]] = {
    "chat.search": CHAT_SEARCH_QUESTIONS,
    "chat.turns.read": CHAT_TURNS_READ_QUESTIONS,
    "chat.session.summary": CHAT_SESSION_SUMMARY_QUESTIONS,
    "chat.sessions.list": CHAT_SESSIONS_LIST_QUESTIONS,
    "chat.periods.list": CHAT_PERIODS_LIST_QUESTIONS,
    "chat.period.summary": CHAT_PERIOD_SUMMARY_QUESTIONS,
}
