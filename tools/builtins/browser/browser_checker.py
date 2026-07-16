from __future__ import annotations

from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_USER_GOAL,
    SEVERITY_CRITICAL,
    SEVERITY_WARN,
    EvidenceRef,
    VerificationQuestion,
)

BROWSER_CHECKER_QUESTIONS_BY_TOOL = {
    "browser.navigate": (
        VerificationQuestion(
            id="browser_url_matches_intent",
            text="Does the navigated URL match what the user asked to open?",
            severity=SEVERITY_CRITICAL,
            evidence=(
                EvidenceRef(kind=EVIDENCE_CALL, fields=("url",), label="navigate_call"),
                EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal"),
            ),
        ),
    ),
    "browser.screenshot": (
        VerificationQuestion(
            id="browser_screenshot_relevant",
            text="Is the screenshot relevant to the user's current browser task?",
            severity=SEVERITY_WARN,
            evidence=(
                EvidenceRef(kind=EVIDENCE_CALL, fields=("url", "file_ref"), label="screenshot_call"),
                EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal"),
            ),
        ),
    ),
    "browser.click": (
        VerificationQuestion(
            id="browser_click_ref_intent",
            text="Was the clicked ref the element implied by the user goal / prior snapshot?",
            severity=SEVERITY_WARN,
            evidence=(
                EvidenceRef(kind=EVIDENCE_CALL, fields=("ref",), label="click_call"),
                EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal"),
            ),
        ),
    ),
}
