from __future__ import annotations

import asyncio
from typing import Any

from config import get_settings, google_limit_label
from tools.builtins.google.auth import get_gmail_service
from tools.builtins.google.gmail_send import (
    build_forward_body,
    build_references,
    build_send_payload,
    forward_subject,
    reply_recipients,
    reply_subject,
)
from tools.builtins.google.gmail_serialize import (
    compact_draft,
    compact_draft_summary,
    compact_filter,
    compact_label,
    compact_message,
    compact_message_summary,
    compact_send_as,
    compact_thread,
    compact_thread_summary,
    compact_vacation,
    find_attachment_meta,
    message_header,
    plain_body_from_message,
)
from tools.builtins.google.tool_hints import GOOGLE_GMAIL_OAUTH_HINT
from tools.context import get_run_context
from tools.schema import ToolSpec

_MAX_RESULTS_CAP = 50
_GMAIL_WRITE_RATE = (30, 60)
_MAX_BATCH_MODIFY = 1000
_MAX_BATCH_DELETE = 1000
_UNREAD_LABEL = "UNREAD"
_INBOX_LABEL = "INBOX"


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


def _max_results(arguments: dict[str, Any]) -> int:
    settings = get_settings()
    default = settings.gmail_default_max_results
    return min(int(arguments.get("max_results", default)), _MAX_RESULTS_CAP)


async def _run_gmail_call(user_id: int, fn):
    service = await get_gmail_service(user_id)
    return await asyncio.to_thread(fn, service)


async def _get_profile_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()

    def _call(service):
        return service.users().getProfile(userId="me").execute()

    profile = await _run_gmail_call(user_id, _call)
    return {
        "email": profile.get("emailAddress"),
        "messages_total": profile.get("messagesTotal"),
        "threads_total": profile.get("threadsTotal"),
        "history_id": profile.get("historyId"),
    }


async def _list_labels_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()

    def _call(service):
        response = service.users().labels().list(userId="me").execute()
        return response.get("labels") or []

    labels = await _run_gmail_call(user_id, _call)
    compact = [compact_label(label) for label in labels]
    return {"count": len(compact), "labels": compact}


async def _get_label_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    label_id = str(arguments["label_id"]).strip()
    if not label_id:
        raise ValueError("label_id is required")

    def _call(service):
        return service.users().labels().get(userId="me", id=label_id).execute()

    label = await _run_gmail_call(user_id, _call)
    return {"label": compact_label(label)}


def _list_messages_call(service, *, label_ids: list[str] | None, q: str | None, max_results: int, page_token: str | None, include_spam_trash: bool):
    params: dict[str, Any] = {
        "userId": "me",
        "maxResults": max_results,
        "includeSpamTrash": include_spam_trash,
    }
    if label_ids:
        params["labelIds"] = label_ids
    if q:
        params["q"] = q
    if page_token:
        params["pageToken"] = page_token
    response = service.users().messages().list(**params).execute()
    return response


async def _search_messages_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    q = str(arguments.get("q", "")).strip()
    if not q:
        raise ValueError("q is required for Gmail search (Gmail query syntax).")
    max_results = _max_results(arguments)
    page_token = arguments.get("page_token")
    include_spam_trash = bool(arguments.get("include_spam_trash", False))

    def _call(service):
        return _list_messages_call(
            service,
            label_ids=None,
            q=q,
            max_results=max_results,
            page_token=page_token,
            include_spam_trash=include_spam_trash,
        )

    response = await _run_gmail_call(user_id, _call)
    messages = response.get("messages") or []
    return {
        "q": q,
        "count": len(messages),
        "next_page_token": response.get("nextPageToken"),
        "messages": [compact_message_summary(item) for item in messages],
    }


async def _list_messages_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    label_ids = arguments.get("label_ids") or []
    if isinstance(label_ids, str):
        label_ids = [label_ids]
    label_ids = [str(label_id).strip() for label_id in label_ids if str(label_id).strip()]
    max_results = _max_results(arguments)
    page_token = arguments.get("page_token")
    include_spam_trash = bool(arguments.get("include_spam_trash", False))

    def _call(service):
        return _list_messages_call(
            service,
            label_ids=label_ids or None,
            q=None,
            max_results=max_results,
            page_token=page_token,
            include_spam_trash=include_spam_trash,
        )

    response = await _run_gmail_call(user_id, _call)
    messages = response.get("messages") or []
    return {
        "label_ids": label_ids,
        "count": len(messages),
        "next_page_token": response.get("nextPageToken"),
        "messages": [compact_message_summary(item) for item in messages],
    }


async def _get_message_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    message_id = str(arguments["message_id"]).strip()
    if not message_id:
        raise ValueError("message_id is required")
    format_value = str(arguments.get("format", "full")).lower()
    if format_value not in {"full", "metadata", "minimal"}:
        raise ValueError("format must be full, metadata, or minimal")

    def _call(service):
        return (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format=format_value)
            .execute()
        )

    message = await _run_gmail_call(user_id, _call)
    settings = get_settings()
    include_body = format_value == "full"
    return {
        "message": compact_message(
            message,
            max_body_chars=settings.gmail_max_body_chars,
            include_body=include_body,
        )
    }


async def _list_inbox_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = {
        **arguments,
        "label_ids": ["INBOX"],
    }
    result = await _list_messages_handler(payload)
    result["mailbox"] = "INBOX"
    return result


async def _list_unread_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = {
        **arguments,
        "q": "is:unread",
    }
    return await _search_messages_handler(payload)


def _normalize_label_ids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _address_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    return [str(item) for item in raw]


def _compose_message_payload(arguments: dict[str, Any], *, require_recipients: bool) -> dict[str, Any]:
    return build_send_payload(
        to=_address_list(arguments.get("to")),
        subject=str(arguments.get("subject", "")),
        body_text=arguments.get("body_text"),
        body_html=arguments.get("body_html"),
        cc=_address_list(arguments.get("cc")),
        bcc=_address_list(arguments.get("bcc")),
        from_send_as=arguments.get("from_send_as"),
        thread_id=arguments.get("thread_id"),
        require_recipients=require_recipients,
    )


def _modify_body(arguments: dict[str, Any]) -> dict[str, Any]:
    add_label_ids = _normalize_label_ids(arguments.get("add_label_ids"))
    remove_label_ids = _normalize_label_ids(arguments.get("remove_label_ids"))
    body: dict[str, Any] = {}
    if add_label_ids:
        body["addLabelIds"] = add_label_ids
    if remove_label_ids:
        body["removeLabelIds"] = remove_label_ids
    if not body:
        raise ValueError("Provide add_label_ids and/or remove_label_ids")
    return body


def _list_threads_call(
    service,
    *,
    label_ids: list[str] | None,
    q: str | None,
    max_results: int,
    page_token: str | None,
    include_spam_trash: bool,
):
    params: dict[str, Any] = {
        "userId": "me",
        "maxResults": max_results,
        "includeSpamTrash": include_spam_trash,
    }
    if label_ids:
        params["labelIds"] = label_ids
    if q:
        params["q"] = q
    if page_token:
        params["pageToken"] = page_token
    return service.users().threads().list(**params).execute()


async def _list_threads_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    label_ids = _normalize_label_ids(arguments.get("label_ids"))
    q = str(arguments.get("q", "")).strip() or None
    max_results = _max_results(arguments)
    page_token = arguments.get("page_token")
    include_spam_trash = bool(arguments.get("include_spam_trash", False))

    def _call(service):
        return _list_threads_call(
            service,
            label_ids=label_ids or None,
            q=q,
            max_results=max_results,
            page_token=page_token,
            include_spam_trash=include_spam_trash,
        )

    response = await _run_gmail_call(user_id, _call)
    threads = response.get("threads") or []
    return {
        "q": q,
        "label_ids": label_ids,
        "count": len(threads),
        "next_page_token": response.get("nextPageToken"),
        "threads": [compact_thread_summary(item) for item in threads],
    }


async def _get_thread_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    thread_id = str(arguments["thread_id"]).strip()
    if not thread_id:
        raise ValueError("thread_id is required")
    format_value = str(arguments.get("format", "full")).lower()
    if format_value not in {"full", "metadata", "minimal"}:
        raise ValueError("format must be full, metadata, or minimal")

    def _call(service):
        return (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format=format_value)
            .execute()
        )

    thread = await _run_gmail_call(user_id, _call)
    settings = get_settings()
    include_bodies = format_value == "full"
    return {
        "thread": compact_thread(
            thread,
            max_body_chars=settings.gmail_max_body_chars,
            include_bodies=include_bodies,
        )
    }


async def _modify_message_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    message_id = str(arguments["message_id"]).strip()
    body = _modify_body(arguments)

    def _call(service):
        return (
            service.users()
            .messages()
            .modify(userId="me", id=message_id, body=body)
            .execute()
        )

    message = await _run_gmail_call(user_id, _call)
    return {
        "modified": True,
        "message_id": message_id,
        "label_ids": message.get("labelIds") or [],
    }


async def _modify_thread_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    thread_id = str(arguments["thread_id"]).strip()
    body = _modify_body(arguments)

    def _call(service):
        return (
            service.users()
            .threads()
            .modify(userId="me", id=thread_id, body=body)
            .execute()
        )

    thread = await _run_gmail_call(user_id, _call)
    return {
        "modified": True,
        "thread_id": thread_id,
        "label_ids": (thread.get("messages") or [{}])[0].get("labelIds") or [],
    }


async def _mark_read_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    message_id = arguments.get("message_id")
    thread_id = arguments.get("thread_id")
    if message_id and thread_id:
        raise ValueError("Provide message_id or thread_id, not both")
    payload = {"remove_label_ids": [_UNREAD_LABEL]}
    if message_id:
        payload["message_id"] = message_id
        return await _modify_message_handler(payload)
    if thread_id:
        payload["thread_id"] = thread_id
        return await _modify_thread_handler(payload)
    raise ValueError("message_id or thread_id is required")


async def _mark_unread_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    message_id = arguments.get("message_id")
    thread_id = arguments.get("thread_id")
    if message_id and thread_id:
        raise ValueError("Provide message_id or thread_id, not both")
    payload = {"add_label_ids": [_UNREAD_LABEL]}
    if message_id:
        payload["message_id"] = message_id
        return await _modify_message_handler(payload)
    if thread_id:
        payload["thread_id"] = thread_id
        return await _modify_thread_handler(payload)
    raise ValueError("message_id or thread_id is required")


async def _archive_message_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    message_id = arguments.get("message_id")
    thread_id = arguments.get("thread_id")
    if message_id and thread_id:
        raise ValueError("Provide message_id or thread_id, not both")
    payload = {"remove_label_ids": [_INBOX_LABEL]}
    if message_id:
        payload["message_id"] = message_id
        return await _modify_message_handler(payload)
    if thread_id:
        payload["thread_id"] = thread_id
        return await _modify_thread_handler(payload)
    raise ValueError("message_id or thread_id is required")


async def _trash_message_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    message_id = str(arguments["message_id"]).strip()

    def _call(service):
        return service.users().messages().trash(userId="me", id=message_id).execute()

    message = await _run_gmail_call(user_id, _call)
    return {"trashed": True, "message_id": message_id, "label_ids": message.get("labelIds") or []}


async def _untrash_message_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    message_id = str(arguments["message_id"]).strip()

    def _call(service):
        return service.users().messages().untrash(userId="me", id=message_id).execute()

    message = await _run_gmail_call(user_id, _call)
    return {"untrashed": True, "message_id": message_id, "label_ids": message.get("labelIds") or []}


async def _trash_thread_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    thread_id = str(arguments["thread_id"]).strip()

    def _call(service):
        return service.users().threads().trash(userId="me", id=thread_id).execute()

    thread = await _run_gmail_call(user_id, _call)
    return {"trashed": True, "thread_id": thread_id, "snippet": thread.get("snippet")}


async def _untrash_thread_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    thread_id = str(arguments["thread_id"]).strip()

    def _call(service):
        return service.users().threads().untrash(userId="me", id=thread_id).execute()

    thread = await _run_gmail_call(user_id, _call)
    return {"untrashed": True, "thread_id": thread_id, "snippet": thread.get("snippet")}


async def _send_message_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    to = arguments.get("to") or []
    if isinstance(to, str):
        to = [to]
    cc = arguments.get("cc") or []
    if isinstance(cc, str):
        cc = [cc]
    bcc = arguments.get("bcc") or []
    if isinstance(bcc, str):
        bcc = [bcc]

    payload = build_send_payload(
        to=[str(item) for item in to],
        subject=str(arguments.get("subject", "")),
        body_text=arguments.get("body_text"),
        body_html=arguments.get("body_html"),
        cc=[str(item) for item in cc],
        bcc=[str(item) for item in bcc],
        from_send_as=arguments.get("from_send_as"),
    )

    def _call(service):
        return service.users().messages().send(userId="me", body=payload).execute()

    sent = await _run_gmail_call(user_id, _call)
    return {
        "sent": True,
        "message_id": sent.get("id"),
        "thread_id": sent.get("threadId"),
        "label_ids": sent.get("labelIds") or [],
    }


async def _reply_to_message_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    message_id = str(arguments["message_id"]).strip()
    reply_all = bool(arguments.get("reply_all", False))

    def _fetch(service):
        return (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata")
            .execute()
        )

    original = await _run_gmail_call(user_id, _fetch)
    headers = {
        "from": message_header(original, "From") or "",
        "to": message_header(original, "To") or "",
        "cc": message_header(original, "Cc") or "",
        "subject": message_header(original, "Subject") or "",
        "message-id": message_header(original, "Message-ID") or "",
        "references": message_header(original, "References") or "",
    }

    profile = await _get_profile_handler({})
    to_list, cc_list = reply_recipients(
        headers,
        reply_all=reply_all,
        exclude_email=profile.get("email"),
    )
    in_reply_to = headers["message-id"]
    if not in_reply_to:
        raise ValueError("Original message has no Message-ID header; cannot reply via API")

    payload = build_send_payload(
        to=to_list,
        cc=cc_list,
        subject=reply_subject(headers["subject"]),
        body_text=arguments.get("body_text"),
        body_html=arguments.get("body_html"),
        from_send_as=arguments.get("from_send_as"),
        in_reply_to=in_reply_to,
        references=build_references(headers["references"], in_reply_to),
        thread_id=original.get("threadId"),
    )

    def _send(service):
        return service.users().messages().send(userId="me", body=payload).execute()

    sent = await _run_gmail_call(user_id, _send)
    return {
        "sent": True,
        "reply_to_message_id": message_id,
        "message_id": sent.get("id"),
        "thread_id": sent.get("threadId"),
        "label_ids": sent.get("labelIds") or [],
    }


async def _create_label_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    name = str(arguments.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")

    body: dict[str, Any] = {
        "name": name,
        "labelListVisibility": str(arguments.get("label_list_visibility", "labelShow")),
        "messageListVisibility": str(arguments.get("message_list_visibility", "show")),
    }

    def _call(service):
        return service.users().labels().create(userId="me", body=body).execute()

    label = await _run_gmail_call(user_id, _call)
    return {"created": True, "label": compact_label(label)}


async def _update_label_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    label_id = str(arguments["label_id"]).strip()
    body: dict[str, Any] = {}
    if "name" in arguments:
        name = str(arguments.get("name", "")).strip()
        if name:
            body["name"] = name
    if "label_list_visibility" in arguments:
        body["labelListVisibility"] = str(arguments["label_list_visibility"])
    if "message_list_visibility" in arguments:
        body["messageListVisibility"] = str(arguments["message_list_visibility"])
    if not body:
        raise ValueError("Provide name and/or visibility fields to update")

    def _call(service):
        return service.users().labels().update(userId="me", id=label_id, body=body).execute()

    label = await _run_gmail_call(user_id, _call)
    return {"updated": True, "label": compact_label(label)}


async def _delete_label_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    label_id = str(arguments["label_id"]).strip()

    def _call(service):
        return service.users().labels().delete(userId="me", id=label_id).execute()

    await _run_gmail_call(user_id, _call)
    return {"deleted": True, "label_id": label_id}


async def _get_attachment_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    message_id = str(arguments["message_id"]).strip()
    attachment_id = str(arguments["attachment_id"]).strip()
    settings = get_settings()
    max_bytes = settings.gmail_max_attachment_bytes

    def _fetch_message(service):
        return (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

    message = await _run_gmail_call(user_id, _fetch_message)
    payload = message.get("payload") or {}
    meta = find_attachment_meta(payload, attachment_id) or {}

    def _fetch_attachment(service):
        return (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )

    attachment = await _run_gmail_call(user_id, _fetch_attachment)
    size = int(attachment.get("size") or meta.get("size") or 0)
    if size > max_bytes:
        return {
            "ok": False,
            "error": (
                f"Attachment too large ({size} bytes; "
                f"{google_limit_label('gmail_attachment')}: {max_bytes} bytes)"
            ),
            "filename": meta.get("filename"),
            "mime_type": meta.get("mime_type"),
            "size": size,
        }

    from tools.builtins.google.gmail_serialize import _decode_base64url
    from tools.run_files import require_run_file_store

    raw = _decode_base64url(str(attachment.get("data") or ""))
    filename = str(meta.get("filename") or "attachment")
    mime_type = meta.get("mime_type")
    store = require_run_file_store()
    stored = store.save(raw, filename=filename, mime_type=str(mime_type) if mime_type else None)
    return {
        "ok": True,
        "message_id": message_id,
        "attachment_id": attachment_id,
        **stored,
    }


async def _batch_modify_messages_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    message_ids = _normalize_label_ids(arguments.get("message_ids"))
    if not message_ids:
        raise ValueError("message_ids is required")
    if len(message_ids) > _MAX_BATCH_MODIFY:
        raise ValueError(f"message_ids max {_MAX_BATCH_MODIFY}")
    body = _modify_body(arguments)
    body["ids"] = message_ids

    def _call(service):
        return service.users().messages().batchModify(userId="me", body=body).execute()

    await _run_gmail_call(user_id, _call)
    return {"modified": True, "count": len(message_ids)}


async def _forward_message_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    message_id = str(arguments["message_id"]).strip()
    to = _address_list(arguments.get("to"))
    if not to:
        raise ValueError("to[] is required")

    def _fetch(service):
        return (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

    original = await _run_gmail_call(user_id, _fetch)
    headers_map = {
        "from": message_header(original, "From") or "",
        "to": message_header(original, "To") or "",
        "cc": message_header(original, "Cc") or "",
        "subject": message_header(original, "Subject") or "",
        "date": message_header(original, "Date") or "",
    }
    forward_body = build_forward_body(
        headers=headers_map,
        body_text=plain_body_from_message(original),
        body_prefix=arguments.get("body_text"),
    )
    send_payload = build_send_payload(
        to=to,
        cc=_address_list(arguments.get("cc")),
        bcc=_address_list(arguments.get("bcc")),
        subject=forward_subject(headers_map["subject"]),
        body_text=forward_body,
        from_send_as=arguments.get("from_send_as"),
    )

    def _send(service):
        return service.users().messages().send(userId="me", body=send_payload).execute()

    sent = await _run_gmail_call(user_id, _send)
    return {
        "sent": True,
        "forwarded_message_id": message_id,
        "message_id": sent.get("id"),
        "thread_id": sent.get("threadId"),
    }


async def _list_drafts_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    max_results = _max_results(arguments)
    page_token = arguments.get("page_token")

    def _call(service):
        params: dict[str, Any] = {"userId": "me", "maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        return service.users().drafts().list(**params).execute()

    response = await _run_gmail_call(user_id, _call)
    drafts = response.get("drafts") or []
    return {
        "count": len(drafts),
        "next_page_token": response.get("nextPageToken"),
        "drafts": [compact_draft_summary(item) for item in drafts],
    }


async def _get_draft_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    draft_id = str(arguments["draft_id"]).strip()
    format_value = str(arguments.get("format", "full")).lower()
    if format_value not in {"full", "metadata", "minimal"}:
        raise ValueError("format must be full, metadata, or minimal")

    def _call(service):
        return (
            service.users()
            .drafts()
            .get(userId="me", id=draft_id, format=format_value)
            .execute()
        )

    draft = await _run_gmail_call(user_id, _call)
    settings = get_settings()
    include_body = format_value == "full"
    return {
        "draft": compact_draft(
            draft,
            max_body_chars=settings.gmail_max_body_chars,
            include_body=include_body,
        )
    }


async def _create_draft_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    message_payload = _compose_message_payload(arguments, require_recipients=False)
    body = {"message": message_payload}

    def _call(service):
        return service.users().drafts().create(userId="me", body=body).execute()

    draft = await _run_gmail_call(user_id, _call)
    settings = get_settings()
    return {
        "created": True,
        "draft": compact_draft(
            draft,
            max_body_chars=settings.gmail_max_body_chars,
            include_body=True,
        ),
    }


async def _update_draft_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    draft_id = str(arguments["draft_id"]).strip()
    message_payload = _compose_message_payload(arguments, require_recipients=False)
    body = {"message": message_payload}

    def _call(service):
        return service.users().drafts().update(userId="me", id=draft_id, body=body).execute()

    draft = await _run_gmail_call(user_id, _call)
    settings = get_settings()
    return {
        "updated": True,
        "draft": compact_draft(
            draft,
            max_body_chars=settings.gmail_max_body_chars,
            include_body=True,
        ),
    }


async def _delete_draft_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    draft_id = str(arguments["draft_id"]).strip()

    def _call(service):
        return service.users().drafts().delete(userId="me", id=draft_id).execute()

    await _run_gmail_call(user_id, _call)
    return {"deleted": True, "draft_id": draft_id}


async def _send_draft_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    draft_id = str(arguments["draft_id"]).strip()

    def _call(service):
        return service.users().drafts().send(userId="me", body={"id": draft_id}).execute()

    sent = await _run_gmail_call(user_id, _call)
    return {
        "sent": True,
        "draft_id": draft_id,
        "message_id": sent.get("id"),
        "thread_id": sent.get("threadId"),
        "label_ids": sent.get("labelIds") or [],
    }


def _require_permanent_confirm(arguments: dict[str, Any]) -> None:
    if arguments.get("confirm") is not True:
        raise ValueError(
            "confirm=true is required — this permanently deletes message(s), not trash."
        )


def _vacation_update_body(arguments: dict[str, Any]) -> dict[str, Any]:
    field_map = {
        "enable_auto_reply": "enableAutoReply",
        "response_subject": "responseSubject",
        "response_body_plain_text": "responseBodyPlainText",
        "response_body_html": "responseBodyHtml",
        "restrict_to_contacts": "restrictToContacts",
        "restrict_to_domain": "restrictToDomain",
        "start_time": "startTime",
        "end_time": "endTime",
    }
    body: dict[str, Any] = {}
    for arg_key, api_key in field_map.items():
        if arg_key in arguments:
            body[api_key] = arguments[arg_key]
    if not body:
        raise ValueError("Provide at least one vacation setting field to update")
    return body


async def _delete_message_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _require_permanent_confirm(arguments)
    user_id = _require_user_id()
    message_id = str(arguments["message_id"]).strip()

    def _call(service):
        return service.users().messages().delete(userId="me", id=message_id).execute()

    await _run_gmail_call(user_id, _call)
    return {"deleted": True, "permanent": True, "message_id": message_id}


async def _batch_delete_messages_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    _require_permanent_confirm(arguments)
    user_id = _require_user_id()
    message_ids = _normalize_label_ids(arguments.get("message_ids"))
    if not message_ids:
        raise ValueError("message_ids is required")
    if len(message_ids) > _MAX_BATCH_DELETE:
        raise ValueError(f"message_ids max {_MAX_BATCH_DELETE}")

    def _call(service):
        return (
            service.users()
            .messages()
            .batchDelete(userId="me", body={"ids": message_ids})
            .execute()
        )

    await _run_gmail_call(user_id, _call)
    return {"deleted": True, "permanent": True, "count": len(message_ids)}


async def _list_filters_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()

    def _call(service):
        response = service.users().settings().filters().list(userId="me").execute()
        return response.get("filter") or []

    filters = await _run_gmail_call(user_id, _call)
    compact = [compact_filter(item) for item in filters]
    return {"count": len(compact), "filters": compact}


async def _get_filter_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    filter_id = str(arguments["filter_id"]).strip()

    def _call(service):
        return service.users().settings().filters().get(userId="me", id=filter_id).execute()

    filter_obj = await _run_gmail_call(user_id, _call)
    return {"filter": compact_filter(filter_obj)}


async def _create_filter_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    criteria = arguments.get("criteria")
    action = arguments.get("action")
    if not isinstance(criteria, dict) or not criteria:
        raise ValueError("criteria object is required (from, to, subject, query, …)")
    if not isinstance(action, dict) or not action:
        raise ValueError("action object is required (addLabelIds, removeLabelIds, forward, …)")

    body = {"criteria": criteria, "action": action}

    def _call(service):
        return service.users().settings().filters().create(userId="me", body=body).execute()

    filter_obj = await _run_gmail_call(user_id, _call)
    return {"created": True, "filter": compact_filter(filter_obj)}


async def _delete_filter_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    filter_id = str(arguments["filter_id"]).strip()

    def _call(service):
        return service.users().settings().filters().delete(userId="me", id=filter_id).execute()

    await _run_gmail_call(user_id, _call)
    return {"deleted": True, "filter_id": filter_id}


async def _get_vacation_settings_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()

    def _call(service):
        return service.users().settings().vacation().get(userId="me").execute()

    settings = await _run_gmail_call(user_id, _call)
    return {"vacation": compact_vacation(settings)}


async def _update_vacation_settings_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    body = _vacation_update_body(arguments)

    def _call(service):
        return service.users().settings().vacation().update(userId="me", body=body).execute()

    settings = await _run_gmail_call(user_id, _call)
    return {"updated": True, "vacation": compact_vacation(settings)}


async def _list_send_as_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()

    def _call(service):
        response = service.users().settings().sendAs().list(userId="me").execute()
        return response.get("sendAs") or []

    aliases = await _run_gmail_call(user_id, _call)
    compact = [compact_send_as(item) for item in aliases]
    return {"count": len(compact), "send_as": compact}


async def _get_send_as_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    send_as_email = str(arguments["send_as_email"]).strip()

    def _call(service):
        return (
            service.users()
            .settings()
            .sendAs()
            .get(userId="me", sendAsEmail=send_as_email)
            .execute()
        )

    alias = await _run_gmail_call(user_id, _call)
    return {"send_as": compact_send_as(alias)}


def _patch_send_as_body(arguments: dict[str, Any]) -> dict[str, Any]:
    field_map = {
        "display_name": "displayName",
        "reply_to_address": "replyToAddress",
        "signature": "signature",
        "is_default": "isDefault",
        "treat_as_alias": "treatAsAlias",
    }
    body: dict[str, Any] = {}
    for arg_key, api_key in field_map.items():
        if arg_key in arguments:
            body[api_key] = arguments[arg_key]
    if not body:
        raise ValueError(
            "Provide at least one field: display_name, reply_to_address, signature, "
            "is_default, treat_as_alias"
        )
    return body


async def _patch_send_as_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    send_as_email = str(arguments["send_as_email"]).strip()
    body = _patch_send_as_body(arguments)

    def _call(service):
        return (
            service.users()
            .settings()
            .sendAs()
            .patch(userId="me", sendAsEmail=send_as_email, body=body)
            .execute()
        )

    alias = await _run_gmail_call(user_id, _call)
    return {"updated": True, "send_as": compact_send_as(alias)}


async def _import_message_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    raw = str(arguments.get("raw", "")).strip()
    if raw:
        import_body: dict[str, Any] = {"raw": raw}
    else:
        import_body = _compose_message_payload(arguments, require_recipients=False)

    label_ids = _normalize_label_ids(arguments.get("label_ids"))
    if label_ids:
        import_body["labelIds"] = label_ids
    thread_id = arguments.get("thread_id")
    if thread_id:
        import_body["threadId"] = str(thread_id).strip()
    if "never_mark_spam" in arguments:
        import_body["neverMarkSpam"] = bool(arguments["never_mark_spam"])

    internal_date_source = arguments.get("internal_date_source")
    if internal_date_source is not None:
        internal_date_source = str(internal_date_source).strip()
        if internal_date_source not in {"dateHeader", "receivedTime"}:
            raise ValueError("internal_date_source must be dateHeader or receivedTime")

    def _call(service):
        params: dict[str, Any] = {"userId": "me", "body": import_body}
        if internal_date_source:
            params["internalDateSource"] = internal_date_source
        return service.users().messages().import_(**params).execute()

    message = await _run_gmail_call(user_id, _call)
    settings = get_settings()
    return {
        "imported": True,
        "message_id": message.get("id"),
        "thread_id": message.get("threadId"),
        "label_ids": message.get("labelIds") or [],
        "message": compact_message(
            message,
            max_body_chars=settings.gmail_max_body_chars,
            include_body=True,
        ),
    }


_PAGE_TOKEN_PARAM = {
    "type": "string",
    "description": "Pagination token from a previous list/search response.",
}
_MAX_RESULTS_PARAM = {
    "type": "integer",
    "description": "Maximum messages to return (default from bot config, max 50).",
}
_INCLUDE_SPAM_TRASH_PARAM = {
    "type": "boolean",
    "description": "Include spam and trash messages.",
    "default": False,
}
_LABEL_MODIFY_PROPERTIES = {
    "add_label_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Label IDs to add (e.g. STARRED).",
    },
    "remove_label_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Label IDs to remove (e.g. UNREAD, INBOX).",
    },
}
_MESSAGE_OR_THREAD_PROPERTIES = {
    "message_id": {
        "type": "string",
        "description": "Gmail message id.",
    },
    "thread_id": {
        "type": "string",
        "description": "Gmail thread id.",
    },
}
_SEND_BODY_PROPERTIES = {
    "body_text": {"type": "string", "description": "Plain-text body."},
    "body_html": {"type": "string", "description": "Optional HTML body."},
    "from_send_as": {
        "type": "string",
        "description": "Optional send-as alias email (must be configured in Gmail).",
    },
}
_DRAFT_COMPOSE_PROPERTIES = {
    "to": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Recipient email addresses.",
    },
    "subject": {"type": "string"},
    "cc": {"type": "array", "items": {"type": "string"}},
    "bcc": {"type": "array", "items": {"type": "string"}},
    **_SEND_BODY_PROPERTIES,
}
_LABEL_VISIBILITY_PROPERTIES = {
    "label_list_visibility": {
        "type": "string",
        "enum": ["labelShow", "labelShowIfUnread", "labelHide"],
        "description": "Sidebar visibility for the label.",
    },
    "message_list_visibility": {
        "type": "string",
        "enum": ["show", "hide"],
        "description": "Whether messages with this label appear in the message list.",
    },
}
_CONFIRM_PARAM = {
    "type": "boolean",
    "description": "Must be true — operation is irreversible (permanent delete, not trash).",
}
_FILTER_CRITERIA_PARAM = {
    "type": "object",
    "description": "Gmail filter criteria: from, to, subject, query, hasAttachment, …",
    "additionalProperties": True,
}
_FILTER_ACTION_PARAM = {
    "type": "object",
    "description": "Gmail filter action: addLabelIds, removeLabelIds, forward, …",
    "additionalProperties": True,
}
_VACATION_UPDATE_PROPERTIES = {
    "enable_auto_reply": {"type": "boolean"},
    "response_subject": {"type": "string"},
    "response_body_plain_text": {"type": "string"},
    "response_body_html": {"type": "string"},
    "restrict_to_contacts": {"type": "boolean"},
    "restrict_to_domain": {"type": "boolean"},
    "start_time": {
        "type": "integer",
        "description": "Vacation start (epoch milliseconds, UTC).",
    },
    "end_time": {
        "type": "integer",
        "description": "Vacation end (epoch milliseconds, UTC).",
    },
}
_PATCH_SEND_AS_PROPERTIES = {
    "display_name": {"type": "string"},
    "reply_to_address": {"type": "string"},
    "signature": {"type": "string", "description": "HTML signature for this alias."},
    "is_default": {"type": "boolean"},
    "treat_as_alias": {"type": "boolean"},
}
_IMPORT_MESSAGE_PROPERTIES = {
    "raw": {
        "type": "string",
        "description": "Optional base64url RFC2822 raw message. If omitted, use to/subject/body fields.",
    },
    "to": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Recipient emails when building message from fields.",
    },
    "subject": {"type": "string"},
    "cc": {"type": "array", "items": {"type": "string"}},
    "bcc": {"type": "array", "items": {"type": "string"}},
    **_SEND_BODY_PROPERTIES,
    "label_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Labels to apply to imported message.",
    },
    "thread_id": {"type": "string", "description": "Optional thread to attach import to."},
    "never_mark_spam": {
        "type": "boolean",
        "description": "If true, Gmail will not mark imported mail as spam.",
    },
    "internal_date_source": {
        "type": "string",
        "enum": ["dateHeader", "receivedTime"],
        "description": "How to set internalDate on import.",
    },
}

GOOGLE_GMAIL_GET_PROFILE = ToolSpec(
    name="google.gmail.get_profile",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Get Gmail mailbox profile: email, totals, historyId.",
    parameters={"type": "object", "properties": {}},
    handler=_get_profile_handler,
    tags=("google", "gmail", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    rate_limit=(30, 60),
    examples=("gmail profile", "connected gmail address"),
)

GOOGLE_GMAIL_LIST_LABELS = ToolSpec(
    name="google.gmail.list_labels",
    description=GOOGLE_GMAIL_OAUTH_HINT + "List all Gmail labels (INBOX, UNREAD, user labels).",
    parameters={"type": "object", "properties": {}},
    handler=_list_labels_handler,
    tags=("google", "gmail", "labels", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    rate_limit=(30, 60),
    examples=("list gmail labels", "show mailbox labels"),
)

GOOGLE_GMAIL_GET_LABEL = ToolSpec(
    name="google.gmail.get_label",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "Get one Gmail label by id (e.g. INBOX, UNREAD, or user label id from list_labels)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "label_id": {
                "type": "string",
                "description": "Label id or system name (INBOX, UNREAD, STARRED, …).",
            },
        },
        "required": ["label_id"],
    },
    handler=_get_label_handler,
    tags=("google", "gmail", "labels", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("get inbox label details", "label message counts"),
)

GOOGLE_GMAIL_SEARCH_MESSAGES = ToolSpec(
    name="google.gmail.search_messages",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "Search Gmail with query syntax (from:, subject:, is:unread, after:YYYY/MM/DD). "
        "Returns message ids and snippets — call get_message for full body."
    ),
    parameters={
        "type": "object",
        "properties": {
            "q": {
                "type": "string",
                "description": "Gmail search query (required).",
            },
            "max_results": _MAX_RESULTS_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
            "include_spam_trash": _INCLUDE_SPAM_TRASH_PARAM,
        },
        "required": ["q"],
    },
    handler=_search_messages_handler,
    tags=("google", "gmail", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("find email from bank", "search gmail for invoice", "unread emails from alex"),
)

GOOGLE_GMAIL_LIST_MESSAGES = ToolSpec(
    name="google.gmail.list_messages",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "List messages by label IDs (e.g. INBOX). Returns ids/snippets only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "label_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Label IDs to filter (e.g. INBOX, STARRED).",
            },
            "max_results": _MAX_RESULTS_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
            "include_spam_trash": _INCLUDE_SPAM_TRASH_PARAM,
        },
    },
    handler=_list_messages_handler,
    tags=("google", "gmail", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("list messages in inbox label", "messages with label work"),
)

GOOGLE_GMAIL_GET_MESSAGE = ToolSpec(
    name="google.gmail.get_message",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "Get one Gmail message by id: headers, truncated body, attachments metadata."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message_id": {
                "type": "string",
                "description": "Gmail message id from search/list results.",
            },
            "format": {
                "type": "string",
                "enum": ["full", "metadata", "minimal"],
                "description": "full includes truncated body_text; metadata/minimal omit body.",
                "default": "full",
            },
        },
        "required": ["message_id"],
    },
    handler=_get_message_handler,
    tags=("google", "gmail", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("read email by id", "open gmail message details"),
)

GOOGLE_GMAIL_LIST_INBOX = ToolSpec(
    name="google.gmail.list_inbox",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "List recent messages in INBOX. Sugar over list_messages(label_ids=[INBOX])."
    ),
    parameters={
        "type": "object",
        "properties": {
            "max_results": _MAX_RESULTS_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
        },
    },
    handler=_list_inbox_handler,
    tags=("google", "gmail", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("show inbox", "latest emails in inbox", "what is in my gmail inbox"),
)

GOOGLE_GMAIL_LIST_UNREAD = ToolSpec(
    name="google.gmail.list_unread",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "List unread Gmail messages (q=is:unread). Sugar over search_messages."
    ),
    parameters={
        "type": "object",
        "properties": {
            "max_results": _MAX_RESULTS_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
            "include_spam_trash": _INCLUDE_SPAM_TRASH_PARAM,
        },
    },
    handler=_list_unread_handler,
    tags=("google", "gmail", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("unread emails", "show unread gmail", "new mail count"),
)

GOOGLE_GMAIL_LIST_THREADS = ToolSpec(
    name="google.gmail.list_threads",
    description=GOOGLE_GMAIL_OAUTH_HINT + "List Gmail threads by optional q and label_ids.",
    parameters={
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "Optional Gmail search query."},
            "label_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional label filter.",
            },
            "max_results": _MAX_RESULTS_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
            "include_spam_trash": _INCLUDE_SPAM_TRASH_PARAM,
        },
    },
    handler=_list_threads_handler,
    tags=("google", "gmail", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("list gmail threads", "conversation threads in inbox"),
)

GOOGLE_GMAIL_GET_THREAD = ToolSpec(
    name="google.gmail.get_thread",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Get one Gmail thread with all messages (truncated bodies).",
    parameters={
        "type": "object",
        "properties": {
            "thread_id": {"type": "string", "description": "Gmail thread id."},
            "format": {
                "type": "string",
                "enum": ["full", "metadata", "minimal"],
                "default": "full",
            },
        },
        "required": ["thread_id"],
    },
    handler=_get_thread_handler,
    tags=("google", "gmail", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("open email conversation", "read gmail thread"),
)

GOOGLE_GMAIL_MODIFY_MESSAGE = ToolSpec(
    name="google.gmail.modify_message",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Add/remove labels on one message.",
    parameters={
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Gmail message id."},
            **_LABEL_MODIFY_PROPERTIES,
        },
        "required": ["message_id"],
    },
    handler=_modify_message_handler,
    tags=("google", "gmail", "labels", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("star gmail message", "add label to email"),
)

GOOGLE_GMAIL_MODIFY_THREAD = ToolSpec(
    name="google.gmail.modify_thread",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Add/remove labels on entire thread.",
    parameters={
        "type": "object",
        "properties": {
            "thread_id": {"type": "string", "description": "Gmail thread id."},
            **_LABEL_MODIFY_PROPERTIES,
        },
        "required": ["thread_id"],
    },
    handler=_modify_thread_handler,
    tags=("google", "gmail", "labels", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("mark thread starred", "label whole conversation"),
)

GOOGLE_GMAIL_MARK_READ = ToolSpec(
    name="google.gmail.mark_read",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Mark message or thread as read (remove UNREAD).",
    parameters={"type": "object", "properties": _MESSAGE_OR_THREAD_PROPERTIES},
    handler=_mark_read_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("mark email as read", "clear unread on thread"),
)

GOOGLE_GMAIL_MARK_UNREAD = ToolSpec(
    name="google.gmail.mark_unread",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Mark message or thread as unread (add UNREAD).",
    parameters={"type": "object", "properties": _MESSAGE_OR_THREAD_PROPERTIES},
    handler=_mark_unread_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("mark email unread", "flag thread unread"),
)

GOOGLE_GMAIL_ARCHIVE_MESSAGE = ToolSpec(
    name="google.gmail.archive_message",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Archive message or thread (remove INBOX label).",
    parameters={"type": "object", "properties": _MESSAGE_OR_THREAD_PROPERTIES},
    handler=_archive_message_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("archive email", "move conversation out of inbox"),
)

GOOGLE_GMAIL_TRASH_MESSAGE = ToolSpec(
    name="google.gmail.trash_message",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Move one message to trash.",
    parameters={
        "type": "object",
        "properties": {"message_id": {"type": "string"}},
        "required": ["message_id"],
    },
    handler=_trash_message_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("delete email to trash", "trash gmail message"),
)

GOOGLE_GMAIL_UNTRASH_MESSAGE = ToolSpec(
    name="google.gmail.untrash_message",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Restore one message from trash.",
    parameters={
        "type": "object",
        "properties": {"message_id": {"type": "string"}},
        "required": ["message_id"],
    },
    handler=_untrash_message_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("restore email from trash", "untrash gmail message"),
)

GOOGLE_GMAIL_TRASH_THREAD = ToolSpec(
    name="google.gmail.trash_thread",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Move entire thread to trash.",
    parameters={
        "type": "object",
        "properties": {"thread_id": {"type": "string"}},
        "required": ["thread_id"],
    },
    handler=_trash_thread_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("trash email conversation", "delete gmail thread"),
)

GOOGLE_GMAIL_UNTRASH_THREAD = ToolSpec(
    name="google.gmail.untrash_thread",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Restore entire thread from trash.",
    parameters={
        "type": "object",
        "properties": {"thread_id": {"type": "string"}},
        "required": ["thread_id"],
    },
    handler=_untrash_thread_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("restore thread from trash", "untrash conversation"),
)

GOOGLE_GMAIL_SEND_MESSAGE = ToolSpec(
    name="google.gmail.send_message",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Send a new email (plain and/or HTML body).",
    parameters={
        "type": "object",
        "properties": {
            "to": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Recipient email addresses.",
            },
            "subject": {"type": "string"},
            "cc": {"type": "array", "items": {"type": "string"}},
            "bcc": {"type": "array", "items": {"type": "string"}},
            **_SEND_BODY_PROPERTIES,
        },
        "required": ["to"],
    },
    handler=_send_message_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("send email", "compose gmail message"),
)

GOOGLE_GMAIL_REPLY_TO_MESSAGE = ToolSpec(
    name="google.gmail.reply_to_message",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "Reply to an existing message (sets thread, In-Reply-To, References)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Message to reply to."},
            "reply_all": {
                "type": "boolean",
                "description": "Include original To/Cc recipients.",
                "default": False,
            },
            **_SEND_BODY_PROPERTIES,
        },
        "required": ["message_id"],
    },
    handler=_reply_to_message_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("reply to email", "answer gmail message"),
)

GOOGLE_GMAIL_CREATE_LABEL = ToolSpec(
    name="google.gmail.create_label",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Create a user Gmail label.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Label display name."},
            **_LABEL_VISIBILITY_PROPERTIES,
        },
        "required": ["name"],
    },
    handler=_create_label_handler,
    tags=("google", "gmail", "labels", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("create gmail label", "new mail folder label"),
)

GOOGLE_GMAIL_UPDATE_LABEL = ToolSpec(
    name="google.gmail.update_label",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Update a user label name or visibility.",
    parameters={
        "type": "object",
        "properties": {
            "label_id": {"type": "string", "description": "Label id from list_labels."},
            "name": {"type": "string"},
            **_LABEL_VISIBILITY_PROPERTIES,
        },
        "required": ["label_id"],
    },
    handler=_update_label_handler,
    tags=("google", "gmail", "labels", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("rename gmail label", "hide label in sidebar"),
)

GOOGLE_GMAIL_DELETE_LABEL = ToolSpec(
    name="google.gmail.delete_label",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "Delete a user label (system labels like INBOX cannot be deleted)."
    ),
    parameters={
        "type": "object",
        "properties": {"label_id": {"type": "string"}},
        "required": ["label_id"],
    },
    handler=_delete_label_handler,
    tags=("google", "gmail", "labels", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("delete gmail label", "remove custom label"),
)

GOOGLE_GMAIL_GET_ATTACHMENT = ToolSpec(
    name="google.gmail.get_attachment",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "Download attachment by message_id + attachment_id from get_message; "
        "stores on server and returns file_ref. Use telegram.send_file to deliver to the user."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message_id": {"type": "string"},
            "attachment_id": {"type": "string"},
        },
        "required": ["message_id", "attachment_id"],
    },
    handler=_get_attachment_handler,
    tags=("google", "gmail", "read"),
    cache_ttl_seconds=0,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("download email attachment", "get pdf from gmail message"),
)

GOOGLE_GMAIL_BATCH_MODIFY_MESSAGES = ToolSpec(
    name="google.gmail.batch_modify_messages",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Add/remove labels on up to 1000 messages at once.",
    parameters={
        "type": "object",
        "properties": {
            "message_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Gmail message ids (max 1000).",
            },
            **_LABEL_MODIFY_PROPERTIES,
        },
        "required": ["message_ids"],
    },
    handler=_batch_modify_messages_handler,
    tags=("google", "gmail", "labels", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("label many emails at once", "batch mark messages read"),
)

GOOGLE_GMAIL_FORWARD_MESSAGE = ToolSpec(
    name="google.gmail.forward_message",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Forward a message to new recipients with quoted body.",
    parameters={
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Message to forward."},
            "to": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Forward recipients.",
            },
            "body_text": {
                "type": "string",
                "description": "Optional note prepended above the forwarded quote.",
            },
            "cc": {"type": "array", "items": {"type": "string"}},
            "bcc": {"type": "array", "items": {"type": "string"}},
            "from_send_as": _SEND_BODY_PROPERTIES["from_send_as"],
        },
        "required": ["message_id", "to"],
    },
    handler=_forward_message_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("forward email", "send message to colleague"),
)

GOOGLE_GMAIL_LIST_DRAFTS = ToolSpec(
    name="google.gmail.list_drafts",
    description=GOOGLE_GMAIL_OAUTH_HINT + "List Gmail drafts (ids and snippets).",
    parameters={
        "type": "object",
        "properties": {
            "max_results": _MAX_RESULTS_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
        },
    },
    handler=_list_drafts_handler,
    tags=("google", "gmail", "drafts", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("list gmail drafts", "show unsent emails"),
)

GOOGLE_GMAIL_GET_DRAFT = ToolSpec(
    name="google.gmail.get_draft",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Get one draft with headers and truncated body.",
    parameters={
        "type": "object",
        "properties": {
            "draft_id": {"type": "string"},
            "format": {
                "type": "string",
                "enum": ["full", "metadata", "minimal"],
                "default": "full",
            },
        },
        "required": ["draft_id"],
    },
    handler=_get_draft_handler,
    tags=("google", "gmail", "drafts", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("open gmail draft", "read draft email"),
)

GOOGLE_GMAIL_CREATE_DRAFT = ToolSpec(
    name="google.gmail.create_draft",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Create a draft (same fields as send_message; to optional).",
    parameters={"type": "object", "properties": _DRAFT_COMPOSE_PROPERTIES},
    handler=_create_draft_handler,
    tags=("google", "gmail", "drafts", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("save email draft", "compose draft gmail"),
)

GOOGLE_GMAIL_UPDATE_DRAFT = ToolSpec(
    name="google.gmail.update_draft",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Replace draft content (draft_id + message fields).",
    parameters={
        "type": "object",
        "properties": {
            "draft_id": {"type": "string"},
            **_DRAFT_COMPOSE_PROPERTIES,
        },
        "required": ["draft_id"],
    },
    handler=_update_draft_handler,
    tags=("google", "gmail", "drafts", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("edit gmail draft", "update unsent email"),
)

GOOGLE_GMAIL_DELETE_DRAFT = ToolSpec(
    name="google.gmail.delete_draft",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Delete a draft permanently.",
    parameters={
        "type": "object",
        "properties": {"draft_id": {"type": "string"}},
        "required": ["draft_id"],
    },
    handler=_delete_draft_handler,
    tags=("google", "gmail", "drafts", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("delete gmail draft", "discard unsent email"),
)

GOOGLE_GMAIL_SEND_DRAFT = ToolSpec(
    name="google.gmail.send_draft",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Send an existing draft by draft_id.",
    parameters={
        "type": "object",
        "properties": {"draft_id": {"type": "string"}},
        "required": ["draft_id"],
    },
    handler=_send_draft_handler,
    tags=("google", "gmail", "drafts", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("send gmail draft", "mail draft now"),
)

GOOGLE_GMAIL_DELETE_MESSAGE = ToolSpec(
    name="google.gmail.delete_message",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "Permanently delete one message (NOT trash — irreversible). Requires confirm=true."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message_id": {"type": "string"},
            "confirm": _CONFIRM_PARAM,
        },
        "required": ["message_id", "confirm"],
    },
    handler=_delete_message_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("permanently delete email", "erase gmail message forever"),
)

GOOGLE_GMAIL_BATCH_DELETE_MESSAGES = ToolSpec(
    name="google.gmail.batch_delete_messages",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "Permanently delete up to 1000 messages (NOT trash). Requires confirm=true."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Gmail message ids (max 1000).",
            },
            "confirm": _CONFIRM_PARAM,
        },
        "required": ["message_ids", "confirm"],
    },
    handler=_batch_delete_messages_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("permanently delete many emails", "batch erase gmail messages"),
)

GOOGLE_GMAIL_LIST_FILTERS = ToolSpec(
    name="google.gmail.list_filters",
    description=GOOGLE_GMAIL_OAUTH_HINT + "List Gmail inbox filters.",
    parameters={"type": "object", "properties": {}},
    handler=_list_filters_handler,
    tags=("google", "gmail", "settings", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("list gmail filters", "show mail rules"),
)

GOOGLE_GMAIL_GET_FILTER = ToolSpec(
    name="google.gmail.get_filter",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Get one Gmail filter by id.",
    parameters={
        "type": "object",
        "properties": {"filter_id": {"type": "string"}},
        "required": ["filter_id"],
    },
    handler=_get_filter_handler,
    tags=("google", "gmail", "settings", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("get gmail filter details", "read mail rule"),
)

GOOGLE_GMAIL_CREATE_FILTER = ToolSpec(
    name="google.gmail.create_filter",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Create a Gmail filter (criteria + action).",
    parameters={
        "type": "object",
        "properties": {
            "criteria": _FILTER_CRITERIA_PARAM,
            "action": _FILTER_ACTION_PARAM,
        },
        "required": ["criteria", "action"],
    },
    handler=_create_filter_handler,
    tags=("google", "gmail", "settings", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("create gmail filter", "auto label emails from sender"),
)

GOOGLE_GMAIL_DELETE_FILTER = ToolSpec(
    name="google.gmail.delete_filter",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Delete a Gmail filter by id.",
    parameters={
        "type": "object",
        "properties": {"filter_id": {"type": "string"}},
        "required": ["filter_id"],
    },
    handler=_delete_filter_handler,
    tags=("google", "gmail", "settings", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("delete gmail filter", "remove mail rule"),
)

GOOGLE_GMAIL_GET_VACATION_SETTINGS = ToolSpec(
    name="google.gmail.get_vacation_settings",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Get vacation / out-of-office auto-reply settings.",
    parameters={"type": "object", "properties": {}},
    handler=_get_vacation_settings_handler,
    tags=("google", "gmail", "settings", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("get vacation responder", "check out of office gmail"),
)

GOOGLE_GMAIL_UPDATE_VACATION_SETTINGS = ToolSpec(
    name="google.gmail.update_vacation_settings",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Update vacation / out-of-office auto-reply.",
    parameters={
        "type": "object",
        "properties": _VACATION_UPDATE_PROPERTIES,
    },
    handler=_update_vacation_settings_handler,
    tags=("google", "gmail", "settings", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("enable vacation auto reply", "set out of office message"),
)

GOOGLE_GMAIL_LIST_SEND_AS = ToolSpec(
    name="google.gmail.list_send_as",
    description=GOOGLE_GMAIL_OAUTH_HINT + "List send-as email aliases configured in Gmail.",
    parameters={"type": "object", "properties": {}},
    handler=_list_send_as_handler,
    tags=("google", "gmail", "settings", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("list gmail aliases", "send as addresses"),
)

GOOGLE_GMAIL_GET_SEND_AS = ToolSpec(
    name="google.gmail.get_send_as",
    description=GOOGLE_GMAIL_OAUTH_HINT + "Get one send-as alias by email address.",
    parameters={
        "type": "object",
        "properties": {
            "send_as_email": {
                "type": "string",
                "description": "Alias email from list_send_as.",
            }
        },
        "required": ["send_as_email"],
    },
    handler=_get_send_as_handler,
    tags=("google", "gmail", "settings", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("get gmail alias details", "send as profile"),
)

GOOGLE_GMAIL_PATCH_SEND_AS = ToolSpec(
    name="google.gmail.patch_send_as",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "Update send-as alias fields (display name, signature, reply-to, default)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "send_as_email": {
                "type": "string",
                "description": "Alias email from list_send_as.",
            },
            **_PATCH_SEND_AS_PROPERTIES,
        },
        "required": ["send_as_email"],
    },
    handler=_patch_send_as_handler,
    tags=("google", "gmail", "settings", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("update gmail signature", "change send as display name"),
)

GOOGLE_GMAIL_IMPORT_MESSAGE = ToolSpec(
    name="google.gmail.import_message",
    description=(
        GOOGLE_GMAIL_OAUTH_HINT
        + "Import a message into the mailbox (raw RFC2822 or compose fields). Does not send mail."
    ),
    parameters={
        "type": "object",
        "properties": _IMPORT_MESSAGE_PROPERTIES,
    },
    handler=_import_message_handler,
    tags=("google", "gmail", "write"),
    parallel_safe=False,
    rate_limit=_GMAIL_WRITE_RATE,
    examples=("import email into gmail", "migrate message to mailbox"),
)

GOOGLE_GMAIL_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_GMAIL_GET_PROFILE,
    GOOGLE_GMAIL_LIST_LABELS,
    GOOGLE_GMAIL_GET_LABEL,
    GOOGLE_GMAIL_SEARCH_MESSAGES,
    GOOGLE_GMAIL_LIST_MESSAGES,
    GOOGLE_GMAIL_GET_MESSAGE,
    GOOGLE_GMAIL_LIST_INBOX,
    GOOGLE_GMAIL_LIST_UNREAD,
    GOOGLE_GMAIL_LIST_THREADS,
    GOOGLE_GMAIL_GET_THREAD,
    GOOGLE_GMAIL_MODIFY_MESSAGE,
    GOOGLE_GMAIL_MODIFY_THREAD,
    GOOGLE_GMAIL_MARK_READ,
    GOOGLE_GMAIL_MARK_UNREAD,
    GOOGLE_GMAIL_ARCHIVE_MESSAGE,
    GOOGLE_GMAIL_TRASH_MESSAGE,
    GOOGLE_GMAIL_UNTRASH_MESSAGE,
    GOOGLE_GMAIL_TRASH_THREAD,
    GOOGLE_GMAIL_UNTRASH_THREAD,
    GOOGLE_GMAIL_SEND_MESSAGE,
    GOOGLE_GMAIL_REPLY_TO_MESSAGE,
    GOOGLE_GMAIL_CREATE_LABEL,
    GOOGLE_GMAIL_UPDATE_LABEL,
    GOOGLE_GMAIL_DELETE_LABEL,
    GOOGLE_GMAIL_GET_ATTACHMENT,
    GOOGLE_GMAIL_BATCH_MODIFY_MESSAGES,
    GOOGLE_GMAIL_FORWARD_MESSAGE,
    GOOGLE_GMAIL_LIST_DRAFTS,
    GOOGLE_GMAIL_GET_DRAFT,
    GOOGLE_GMAIL_CREATE_DRAFT,
    GOOGLE_GMAIL_UPDATE_DRAFT,
    GOOGLE_GMAIL_DELETE_DRAFT,
    GOOGLE_GMAIL_SEND_DRAFT,
    GOOGLE_GMAIL_DELETE_MESSAGE,
    GOOGLE_GMAIL_BATCH_DELETE_MESSAGES,
    GOOGLE_GMAIL_LIST_FILTERS,
    GOOGLE_GMAIL_GET_FILTER,
    GOOGLE_GMAIL_CREATE_FILTER,
    GOOGLE_GMAIL_DELETE_FILTER,
    GOOGLE_GMAIL_GET_VACATION_SETTINGS,
    GOOGLE_GMAIL_UPDATE_VACATION_SETTINGS,
    GOOGLE_GMAIL_LIST_SEND_AS,
    GOOGLE_GMAIL_GET_SEND_AS,
    GOOGLE_GMAIL_PATCH_SEND_AS,
    GOOGLE_GMAIL_IMPORT_MESSAGE,
)
