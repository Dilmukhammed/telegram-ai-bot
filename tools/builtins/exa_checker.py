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

_PRIOR_EXA_SEARCH = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("exa.web_search",),
    optional=True,
    max_age_steps=10,
    label="prior_exa_search",
)

_PRIOR_EXA_CONTEXT = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_name_pattern="exa.*",
    optional=True,
    max_age_steps=10,
    label="prior_exa_context",
)


def _call(label: str, *fields: str) -> EvidenceRef:
    return EvidenceRef(kind=EVIDENCE_CALL, fields=fields, label=label)


EXA_WEB_SEARCH_QUESTIONS = (
    VerificationQuestion(
        id="query_matches_intent",
        text="Does query express what the user asked to find on the live web?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("search_call", "query", "num_results", "type"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="query_timeframe",
        text=(
            "If the user asked about a specific date, year, or recency (today, latest, this week, "
            "2026, yesterday), does the query include that timeframe — not a timeless generic query?"
        ),
        severity=SEVERITY_CRITICAL,
        evidence=(_call("search_call", "query"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="results_recency",
        text=(
            "For time-sensitive queries (news, prices, events), do result published_date values "
            "look plausibly within the period the user asked for?"
        ),
        severity=SEVERITY_WARN,
        evidence=(_call("search_call", "query", "results"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="web_search_not_wrong_tool",
        text=(
            "Did the user need live web/news/docs (Exa), not Yandex Music, "
            "Google Drive/Gmail/Maps/Calendar, or workspace file search?"
        ),
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL, _call("search_call", "query")),
    ),
    VerificationQuestion(
        id="num_results_scope",
        text="Is num_results (1-10) enough to answer without being wastefully broad?",
        severity=SEVERITY_INFO,
        evidence=(_call("search_call", "num_results"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="search_before_fetch",
        text="If full article text is needed, will exa.web_fetch follow on result URLs?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL, _call("search_call", "query")),
    ),
)

EXA_WEB_FETCH_QUESTIONS = (
    VerificationQuestion(
        id="urls_from_trusted_source",
        text="Are urls from exa.web_search results, a user-provided link, or another verified source — not guessed?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("fetch_call", "urls"), _USER_GOAL, _PRIOR_EXA_SEARCH, _PRIOR_EXA_CONTEXT),
    ),
    VerificationQuestion(
        id="fetch_not_search",
        text="Did the user need full page text (web_fetch), not search highlights alone?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL, _PRIOR_EXA_CONTEXT),
    ),
    VerificationQuestion(
        id="fetch_after_search",
        text="If discovering URLs, was exa.web_search called first instead of fetching arbitrary URLs?",
        severity=SEVERITY_INFO,
        evidence=(_call("fetch_call", "urls"), _PRIOR_EXA_SEARCH, _USER_GOAL),
    ),
    VerificationQuestion(
        id="url_count_reasonable",
        text="Is the number of URLs fetched proportional to what the user asked to read?",
        severity=SEVERITY_INFO,
        evidence=(_call("fetch_call", "urls"), _USER_GOAL),
    ),
)

EXA_CHECKER_QUESTIONS_BY_TOOL: dict[str, tuple[VerificationQuestion, ...]] = {
    "exa.web_search": EXA_WEB_SEARCH_QUESTIONS,
    "exa.web_fetch": EXA_WEB_FETCH_QUESTIONS,
}

EXA_CHECKER_ALL_TOOL_NAMES = tuple(EXA_CHECKER_QUESTIONS_BY_TOOL.keys())

EXA_CHECKER_READ_TOOL_NAMES = EXA_CHECKER_ALL_TOOL_NAMES

EXA_CHECKER_WRITE_TOOL_NAMES: tuple[str, ...] = ()
