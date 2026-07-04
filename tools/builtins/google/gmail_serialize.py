from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

_HEADER_WHITESPACE_RE = re.compile(r"\s+")


def _decode_base64url(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)] + "…"


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return _HEADER_WHITESPACE_RE.sub(" ", text).strip()


def _headers_map(payload: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in payload.get("headers") or []:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        headers[name.lower()] = str(item.get("value", "")).strip()
    return headers


def _collect_body_parts(payload: dict[str, Any]) -> tuple[str, str]:
    mime_type = str(payload.get("mimeType") or "").lower()
    body = payload.get("body") or {}
    data = body.get("data")
    text = ""
    html = ""

    if data:
        try:
            decoded = _decode_base64url(str(data)).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            decoded = ""
        if mime_type == "text/plain":
            text = decoded
        elif mime_type == "text/html":
            html = decoded

    for part in payload.get("parts") or []:
        if not isinstance(part, dict):
            continue
        part_text, part_html = _collect_body_parts(part)
        if part_text and not text:
            text = part_text
        if part_html and not html:
            html = part_html

    return text, html


def extract_bodies(payload: dict[str, Any] | None) -> tuple[str, str]:
    if not payload:
        return "", ""
    return _collect_body_parts(payload)


def plain_body_from_message(message: dict[str, Any]) -> str:
    payload = message.get("payload") or {}
    text, html = extract_bodies(payload)
    if text.strip():
        return text.strip()
    if html.strip():
        return _strip_html(html)
    return str(message.get("snippet") or "").strip()


def format_internal_date(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text.isdigit():
        return text or None
    millis = int(text)
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()


def compact_label(label: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": label.get("id"),
        "name": label.get("name"),
        "type": label.get("type"),
        "messages_total": label.get("messagesTotal"),
        "messages_unread": label.get("messagesUnread"),
    }


def compact_message_summary(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "label_ids": message.get("labelIds") or [],
        "snippet": message.get("snippet"),
        "internal_date": format_internal_date(message.get("internalDate")),
    }


def compact_thread_summary(thread: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": thread.get("id"),
        "snippet": thread.get("snippet"),
        "history_id": thread.get("historyId"),
    }


def compact_thread(
    thread: dict[str, Any],
    *,
    max_body_chars: int,
    include_bodies: bool = True,
) -> dict[str, Any]:
    messages = thread.get("messages") or []
    return {
        **compact_thread_summary(thread),
        "count": len(messages),
        "messages": [
            compact_message(
                message,
                max_body_chars=max_body_chars,
                include_body=include_bodies,
            )
            for message in messages
        ],
    }


def message_header(message: dict[str, Any], name: str) -> str | None:
    payload = message.get("payload") or {}
    value = _headers_map(payload).get(name.lower())
    return value or None


def compact_attachment(part: dict[str, Any]) -> dict[str, Any] | None:
    body = part.get("body") or {}
    attachment_id = body.get("attachmentId")
    if not attachment_id:
        return None
    headers = _headers_map(part)
    filename = part.get("filename") or headers.get("content-disposition") or "attachment"
    return {
        "id": attachment_id,
        "filename": filename,
        "mime_type": part.get("mimeType"),
        "size": body.get("size"),
    }


def list_attachments(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []

    attachments: list[dict[str, Any]] = []

    def _walk(node: dict[str, Any]) -> None:
        attachment = compact_attachment(node)
        if attachment:
            attachments.append(attachment)
        for part in node.get("parts") or []:
            if isinstance(part, dict):
                _walk(part)

    _walk(payload)
    return attachments


def compact_draft_summary(draft: dict[str, Any]) -> dict[str, Any]:
    message = draft.get("message") or {}
    return {
        "id": draft.get("id"),
        "message_id": message.get("id"),
        "thread_id": message.get("threadId"),
        "label_ids": message.get("labelIds") or [],
        "snippet": message.get("snippet"),
        "internal_date": format_internal_date(message.get("internalDate")),
    }


def compact_draft(
    draft: dict[str, Any],
    *,
    max_body_chars: int,
    include_body: bool = True,
) -> dict[str, Any]:
    message = draft.get("message") or {}
    result: dict[str, Any] = {
        **compact_draft_summary(draft),
    }
    if message:
        compact = compact_message(
            message,
            max_body_chars=max_body_chars,
            include_body=include_body,
        )
        result.update(
            {
                "from": compact.get("from"),
                "to": compact.get("to"),
                "cc": compact.get("cc"),
                "subject": compact.get("subject"),
                "attachments": compact.get("attachments") or [],
            }
        )
        if include_body:
            result["body_text"] = compact.get("body_text")
    return result


def find_attachment_meta(
    payload: dict[str, Any] | None,
    attachment_id: str,
) -> dict[str, Any] | None:
    if not payload:
        return None
    target = str(attachment_id).strip()

    def _walk(node: dict[str, Any]) -> dict[str, Any] | None:
        body = node.get("body") or {}
        if str(body.get("attachmentId") or "") == target:
            return compact_attachment(node)
        for part in node.get("parts") or []:
            if isinstance(part, dict):
                found = _walk(part)
                if found:
                    return found
        return None

    return _walk(payload)


def compact_filter(filter_obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": filter_obj.get("id"),
        "criteria": filter_obj.get("criteria") or {},
        "action": filter_obj.get("action") or {},
    }


def compact_vacation(settings: dict[str, Any]) -> dict[str, Any]:
    start_time = settings.get("startTime")
    end_time = settings.get("endTime")
    return {
        "enable_auto_reply": settings.get("enableAutoReply"),
        "response_subject": settings.get("responseSubject"),
        "response_body_plain_text": settings.get("responseBodyPlainText"),
        "response_body_html": settings.get("responseBodyHtml"),
        "restrict_to_contacts": settings.get("restrictToContacts"),
        "restrict_to_domain": settings.get("restrictToDomain"),
        "start_time": format_internal_date(str(start_time)) if start_time is not None else None,
        "end_time": format_internal_date(str(end_time)) if end_time is not None else None,
    }


def compact_send_as(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "send_as_email": entry.get("sendAsEmail"),
        "display_name": entry.get("displayName"),
        "reply_to_address": entry.get("replyToAddress"),
        "is_primary": entry.get("isPrimary"),
        "is_default": entry.get("isDefault"),
        "treat_as_alias": entry.get("treatAsAlias"),
        "verification_status": entry.get("verificationStatus"),
    }


def compact_message(
    message: dict[str, Any],
    *,
    max_body_chars: int,
    include_body: bool = True,
) -> dict[str, Any]:
    payload = message.get("payload") or {}
    headers = _headers_map(payload)
    summary = compact_message_summary(message)
    result: dict[str, Any] = {
        **summary,
        "from": headers.get("from"),
        "to": headers.get("to"),
        "cc": headers.get("cc"),
        "subject": headers.get("subject"),
        "date": headers.get("date"),
        "attachments": list_attachments(payload),
    }
    if not include_body:
        return result

    body_text, body_html = extract_bodies(payload)
    if body_text:
        result["body_text"] = _truncate(body_text.strip(), max_body_chars)
    elif body_html:
        plain = _strip_html(body_html)
        result["body_text"] = _truncate(plain, max_body_chars)
        result["body_html_truncated"] = True
    else:
        result["body_text"] = _truncate(str(message.get("snippet") or ""), max_body_chars)

    return result
