from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEVERITY_CRITICAL = "critical"
SEVERITY_WARN = "warn"
SEVERITY_INFO = "info"

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_UNKNOWN = "unknown"
VERDICT_NA = "n_a"

# Declarative rule-based short-circuits. A question that sets `rule_check` to one of
# these is resolved deterministically from live evidence instead of (or before) the LLM.
RULE_CHECK_RESOURCE_EXISTS = "resource_exists"
RULE_CHECK_SLOT_FREE = "slot_free"

EVIDENCE_PRIOR_TOOL = "prior_tool_result"
EVIDENCE_LIVE_FETCH = "live_fetch"
EVIDENCE_CALL = "call_under_review"
EVIDENCE_USER_GOAL = "user_goal"
EVIDENCE_RUNTIME = "runtime_context"

FETCH_CALENDAR_SLOT_CONFLICTS = "calendar_slot_conflicts"
FETCH_CALENDAR_EVENT_EXISTS = "calendar_event_exists"
FETCH_GMAIL_MESSAGE = "gmail_message"
FETCH_GMAIL_SENT_MESSAGE = "gmail_sent_message"
FETCH_SHEETS_RANGE_VALUES = "sheets_range_values"
FETCH_DRIVE_FILE = "drive_file"
FETCH_TASKS_GET_TASK = "tasks_get_task"
FETCH_WORKSPACE_STAT = "workspace_stat"
FETCH_PDF_READ_METADATA = "pdf_read_metadata"
FETCH_YANDEX_TRACK = "yandex_track"


@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    tool_names: tuple[str, ...] = ()
    tool_name_pattern: str | None = None
    match: tuple[tuple[str, str], ...] = ()
    time_overlap: str | None = None
    fields: tuple[str, ...] = ()
    required: bool = False
    optional: bool = False
    max_age_steps: int | None = None
    label: str = ""
    fetch: str = ""


@dataclass(frozen=True)
class VerificationQuestion:
    id: str
    text: str
    severity: str = SEVERITY_WARN
    evidence: tuple[EvidenceRef, ...] = ()
    fail_if_evidence_missing: bool = False
    llm_required: bool = True
    rule_check: str = ""


@dataclass(frozen=True)
class EvidenceSnippet:
    label: str
    kind: str
    turn: int | None
    tool_name: str | None
    content: str


@dataclass
class QuestionVerdict:
    question_id: str
    verdict: str
    severity: str
    reason: str
    evidence_used: list[str] = field(default_factory=list)
    evidence_missing: list[str] = field(default_factory=list)
    rule_based: bool = False


@dataclass
class ResolvedQuestion:
    question: VerificationQuestion
    snippets: list[EvidenceSnippet]
    missing_required: list[str]

    def rule_based_verdict(self) -> QuestionVerdict | None:
        if not self.missing_required:
            return None
        if not self.question.fail_if_evidence_missing:
            return QuestionVerdict(
                question_id=self.question.id,
                verdict=VERDICT_UNKNOWN,
                severity=self.question.severity,
                reason="Required evidence missing; cannot verify",
                evidence_used=[snippet.label for snippet in self.snippets if snippet.label],
                evidence_missing=list(self.missing_required),
                rule_based=True,
            )
        return QuestionVerdict(
            question_id=self.question.id,
            verdict=VERDICT_FAIL,
            severity=self.question.severity,
            reason=(
                "Required evidence not found in trace before this call: "
                + ", ".join(self.missing_required)
            ),
            evidence_used=[snippet.label for snippet in self.snippets if snippet.label],
            evidence_missing=list(self.missing_required),
            rule_based=True,
        )


@dataclass(frozen=True)
class CheckerRuntimeContext:
    bot_timezone: str
    user_message: str = ""

    @classmethod
    def from_settings(cls, *, user_message: str = "") -> CheckerRuntimeContext:
        from config import get_settings

        settings = get_settings()
        return cls(
            bot_timezone=settings.bot_timezone or "UTC",
            user_message=user_message,
        )

    def to_snippet(self) -> dict[str, Any]:
        return {
            "bot_timezone": self.bot_timezone,
            "user_message": self.user_message,
        }
