from __future__ import annotations

from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_LIVE_FETCH,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_USER_GOAL,
    FETCH_WORKSPACE_STAT,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    EvidenceRef,
    VerificationQuestion,
)

_USER_GOAL = EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal")

_LIVE_WORKSPACE_STAT = EvidenceRef(
    kind=EVIDENCE_LIVE_FETCH,
    fetch=FETCH_WORKSPACE_STAT,
    label="workspace_path_live",
)

_PRIOR_FILE_REF_SOURCE = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "google.drive.download_file",
        "google.drive.export_file",
        "google.gmail.get_attachment",
        "yandex.music.track_download",
    ),
    match=(("file_ref", "$call.file_ref"),),
    optional=True,
    max_age_steps=10,
    label="prior_file_ref_source",
)

_PRIOR_PDF_FILE_REF = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_name_pattern="pdf.*",
    match=(("file_ref", "$call.file_ref"),),
    optional=True,
    max_age_steps=10,
    label="prior_pdf_file_ref",
)

_PRIOR_WORKSPACE_PATH = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "workspace.stat",
        "workspace.read_file",
        "workspace.write_file",
        "workspace.find",
        "workspace.list_dir",
    ),
    match=(("path", "$call.path"),),
    optional=True,
    max_age_steps=10,
    label="prior_workspace_path",
)


def _call(label: str, *fields: str) -> EvidenceRef:
    return EvidenceRef(kind=EVIDENCE_CALL, fields=fields, label=label)


TELEGRAM_SEND_FILE_QUESTIONS = (
    VerificationQuestion(
        id="delivery_intent",
        text="Did the user ask to receive/send the file in Telegram chat (not just generate or inspect it)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_USER_GOAL, _call("send_call", "file_ref", "path", "caption")),
    ),
    VerificationQuestion(
        id="path_xor_file_ref",
        text="Is exactly one of file_ref or path provided (not both, not neither)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("send_call", "file_ref", "path"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="file_ref_from_prior",
        text=(
            "If file_ref is used, does it come from a prior download/export/attachment/"
            "track_download/pdf output in this run?"
        ),
        severity=SEVERITY_CRITICAL,
        evidence=(
            _call("send_call", "file_ref"),
            _PRIOR_FILE_REF_SOURCE,
            _PRIOR_PDF_FILE_REF,
            _USER_GOAL,
        ),
    ),
    VerificationQuestion(
        id="path_correct",
        text="If path is used, is it the workspace file the user asked to deliver?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("send_call", "path"), _USER_GOAL, _PRIOR_WORKSPACE_PATH),
    ),
    VerificationQuestion(
        id="workspace_path_exists_live",
        text="If sending by path, does live workspace.stat confirm the file exists?",
        severity=SEVERITY_WARN,
        evidence=(_call("send_call", "path"), _LIVE_WORKSPACE_STAT, _USER_GOAL),
    ),
    VerificationQuestion(
        id="as_kind_appropriate",
        text="Is as (auto/document/photo/audio) appropriate for the file type and user intent?",
        severity=SEVERITY_INFO,
        evidence=(_call("send_call", "as", "caption"), _USER_GOAL),
    ),
)

TELEGRAM_CHECKER_QUESTIONS_BY_TOOL: dict[str, tuple[VerificationQuestion, ...]] = {
    "telegram.send_file": TELEGRAM_SEND_FILE_QUESTIONS,
}

TELEGRAM_CHECKER_ALL_TOOL_NAMES = tuple(TELEGRAM_CHECKER_QUESTIONS_BY_TOOL.keys())

TELEGRAM_CHECKER_READ_TOOL_NAMES: tuple[str, ...] = ()

TELEGRAM_CHECKER_WRITE_TOOL_NAMES = TELEGRAM_CHECKER_ALL_TOOL_NAMES
