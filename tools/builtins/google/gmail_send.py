from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from email.utils import getaddresses
from typing import Any

_EMAIL_SPLIT_RE = re.compile(r"[;,]")


def _normalize_addresses(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for part in _EMAIL_SPLIT_RE.split(str(raw)):
            part = part.strip()
            if not part:
                continue
            for _name, addr in getaddresses([part]):
                email = addr.strip()
                if not email:
                    continue
                key = email.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(email)
    return out


def encode_raw_message(message: EmailMessage) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def reply_subject(original_subject: str) -> str:
    subject = str(original_subject or "").strip() or "(no subject)"
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}"


def forward_subject(original_subject: str) -> str:
    subject = str(original_subject or "").strip() or "(no subject)"
    if subject.lower().startswith("fwd:"):
        return subject
    return f"Fwd: {subject}"


def build_forward_body(
    *,
    headers: dict[str, str],
    body_text: str,
    body_prefix: str | None = None,
) -> str:
    prefix = (body_prefix or "").strip()
    lines = [
        "",
        "---------- Forwarded message ---------",
        f"From: {headers.get('from', '')}",
        f"Date: {headers.get('date', '')}",
        f"Subject: {headers.get('subject', '')}",
        f"To: {headers.get('to', '')}",
    ]
    cc = headers.get("cc", "").strip()
    if cc:
        lines.append(f"Cc: {cc}")
    lines.extend(["", body_text.strip()])
    quoted = "\n".join(lines)
    if prefix:
        return f"{prefix}\n{quoted}"
    return quoted.lstrip("\n")


def build_references(original_references: str | None, message_id: str) -> str:
    message_id = str(message_id or "").strip()
    refs = str(original_references or "").strip()
    if not message_id:
        return refs
    if refs:
        return f"{refs} {message_id}".strip()
    return message_id


def build_send_payload(
    *,
    to: list[str],
    subject: str,
    body_text: str | None = None,
    body_html: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    from_send_as: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    thread_id: str | None = None,
    require_recipients: bool = True,
) -> dict[str, Any]:
    recipients = _normalize_addresses(to)
    if not recipients and require_recipients:
        raise ValueError("At least one recipient in to[] is required")

    message = EmailMessage()
    if from_send_as:
        message["From"] = from_send_as.strip()
    if recipients:
        message["To"] = ", ".join(recipients)
    cc_list = _normalize_addresses(cc or [])
    if cc_list:
        message["Cc"] = ", ".join(cc_list)
    bcc_list = _normalize_addresses(bcc or [])
    if bcc_list:
        message["Bcc"] = ", ".join(bcc_list)
    message["Subject"] = subject.strip() or "(no subject)"
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references

    text = (body_text or "").strip()
    html = (body_html or "").strip()
    if html and text:
        message.set_content(text)
        message.add_alternative(html, subtype="html")
    elif html:
        message.set_content(html, subtype="html")
    else:
        message.set_content(text or "")

    payload: dict[str, Any] = {"raw": encode_raw_message(message)}
    if thread_id:
        payload["threadId"] = thread_id
    return payload


def reply_recipients(
    headers: dict[str, str],
    *,
    reply_all: bool,
    exclude_email: str | None = None,
) -> tuple[list[str], list[str]]:
    exclude = (exclude_email or "").strip().lower()
    to_values: list[str] = []
    cc_values: list[str] = []

    sender = headers.get("from", "")
    if sender:
        to_values.append(sender)

    if reply_all:
        to_values.extend(_EMAIL_SPLIT_RE.split(headers.get("to", "")))
        cc_values.extend(_EMAIL_SPLIT_RE.split(headers.get("cc", "")))

    to_list = _normalize_addresses(to_values)
    cc_list = _normalize_addresses(cc_values)

    if exclude:
        to_list = [addr for addr in to_list if addr.lower() != exclude]
        cc_list = [addr for addr in cc_list if addr.lower() != exclude]
        cc_list = [addr for addr in cc_list if addr.lower() not in {a.lower() for a in to_list}]

    if not to_list:
        raise ValueError("Could not determine reply recipient from message headers")
    return to_list, cc_list
