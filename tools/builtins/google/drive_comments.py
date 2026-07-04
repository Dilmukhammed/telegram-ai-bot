from __future__ import annotations

from typing import Any

from tools.builtins.google.drive_client import drive_support_kwargs, run_drive_call
from tools.builtins.google.drive_serialize import (
    COMMENT_FIELDS,
    COMMENT_LIST_FIELDS,
    REPLY_FIELDS,
    REPLY_LIST_FIELDS,
    build_comments_list_response,
    build_replies_list_response,
    compact_comment,
    compact_reply,
)
from tools.context import get_run_context

_MAX_PAGE_SIZE = 100


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


def _require_file_id(arguments: dict[str, Any]) -> str:
    file_id = str(arguments.get("file_id", "")).strip()
    if not file_id:
        raise ValueError("file_id is required")
    return file_id


def _require_comment_id(arguments: dict[str, Any]) -> str:
    comment_id = str(arguments.get("comment_id", "")).strip()
    if not comment_id:
        raise ValueError("comment_id is required")
    return comment_id


def _require_reply_id(arguments: dict[str, Any]) -> str:
    reply_id = str(arguments.get("reply_id", "")).strip()
    if not reply_id:
        raise ValueError("reply_id is required")
    return reply_id


def _require_content(arguments: dict[str, Any]) -> str:
    content = str(arguments.get("content", "")).strip()
    if not content:
        raise ValueError("content is required")
    return content


async def list_comments_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    page_size = min(int(arguments.get("page_size", 20)), _MAX_PAGE_SIZE)
    page_token = str(arguments.get("page_token") or "").strip() or None
    include_deleted = bool(arguments.get("include_deleted", False))

    def _call(service):
        kwargs: dict[str, Any] = {
            "fileId": file_id,
            "fields": COMMENT_LIST_FIELDS,
            "pageSize": page_size,
            "includeDeleted": include_deleted,
            **drive_support_kwargs(),
        }
        if page_token:
            kwargs["pageToken"] = page_token
        return service.comments().list(**kwargs).execute()

    response = await run_drive_call(user_id, _call)
    return {"file_id": file_id, **build_comments_list_response(response)}


async def get_comment_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    comment_id = _require_comment_id(arguments)

    def _call(service):
        return (
            service.comments()
            .get(
                fileId=file_id,
                commentId=comment_id,
                fields=COMMENT_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    comment = await run_drive_call(user_id, _call)
    return {"file_id": file_id, "comment": compact_comment(comment)}


async def create_comment_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    content = _require_content(arguments)

    def _call(service):
        return (
            service.comments()
            .create(
                fileId=file_id,
                body={"content": content},
                fields=COMMENT_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    comment = await run_drive_call(user_id, _call)
    return {"created": True, "file_id": file_id, "comment": compact_comment(comment)}


async def update_comment_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    comment_id = _require_comment_id(arguments)
    content = _require_content(arguments)

    def _call(service):
        return (
            service.comments()
            .update(
                fileId=file_id,
                commentId=comment_id,
                body={"content": content},
                fields=COMMENT_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    comment = await run_drive_call(user_id, _call)
    return {"updated": True, "file_id": file_id, "comment": compact_comment(comment)}


async def delete_comment_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    comment_id = _require_comment_id(arguments)

    def _call(service):
        service.comments().delete(
            fileId=file_id,
            commentId=comment_id,
            **drive_support_kwargs(),
        ).execute()
        return {"deleted": True, "file_id": file_id, "comment_id": comment_id}

    return await run_drive_call(user_id, _call)


async def list_replies_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    comment_id = _require_comment_id(arguments)
    page_size = min(int(arguments.get("page_size", 20)), _MAX_PAGE_SIZE)
    page_token = str(arguments.get("page_token") or "").strip() or None
    include_deleted = bool(arguments.get("include_deleted", False))

    def _call(service):
        kwargs: dict[str, Any] = {
            "fileId": file_id,
            "commentId": comment_id,
            "fields": REPLY_LIST_FIELDS,
            "pageSize": page_size,
            "includeDeleted": include_deleted,
            **drive_support_kwargs(),
        }
        if page_token:
            kwargs["pageToken"] = page_token
        return service.replies().list(**kwargs).execute()

    response = await run_drive_call(user_id, _call)
    return {
        "file_id": file_id,
        "comment_id": comment_id,
        **build_replies_list_response(response),
    }


async def get_reply_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    comment_id = _require_comment_id(arguments)
    reply_id = _require_reply_id(arguments)

    def _call(service):
        return (
            service.replies()
            .get(
                fileId=file_id,
                commentId=comment_id,
                replyId=reply_id,
                fields=REPLY_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    reply = await run_drive_call(user_id, _call)
    return {
        "file_id": file_id,
        "comment_id": comment_id,
        "reply": compact_reply(reply),
    }


async def create_reply_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    comment_id = _require_comment_id(arguments)
    content = _require_content(arguments)

    def _call(service):
        return (
            service.replies()
            .create(
                fileId=file_id,
                commentId=comment_id,
                body={"content": content},
                fields=REPLY_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    reply = await run_drive_call(user_id, _call)
    return {
        "created": True,
        "file_id": file_id,
        "comment_id": comment_id,
        "reply": compact_reply(reply),
    }


async def update_reply_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    comment_id = _require_comment_id(arguments)
    reply_id = _require_reply_id(arguments)
    content = _require_content(arguments)

    def _call(service):
        return (
            service.replies()
            .update(
                fileId=file_id,
                commentId=comment_id,
                replyId=reply_id,
                body={"content": content},
                fields=REPLY_FIELDS,
                **drive_support_kwargs(),
            )
            .execute()
        )

    reply = await run_drive_call(user_id, _call)
    return {
        "updated": True,
        "file_id": file_id,
        "comment_id": comment_id,
        "reply": compact_reply(reply),
    }


async def delete_reply_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    comment_id = _require_comment_id(arguments)
    reply_id = _require_reply_id(arguments)

    def _call(service):
        service.replies().delete(
            fileId=file_id,
            commentId=comment_id,
            replyId=reply_id,
            **drive_support_kwargs(),
        ).execute()
        return {
            "deleted": True,
            "file_id": file_id,
            "comment_id": comment_id,
            "reply_id": reply_id,
        }

    return await run_drive_call(user_id, _call)
