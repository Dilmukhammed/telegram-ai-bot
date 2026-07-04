from __future__ import annotations

from typing import Any

from tools.builtins.google.drive_client import run_drive_call
from tools.builtins.google.drive_serialize import (
    ACCESS_PROPOSAL_FIELDS,
    ACCESS_PROPOSAL_LIST_FIELDS,
    APPROVAL_FIELDS,
    APPROVAL_LIST_FIELDS,
    build_access_proposals_list_response,
    build_approvals_list_response,
    compact_access_proposal,
    compact_approval,
)
from tools.context import get_run_context

_MAX_PAGE_SIZE = 100
_RESOLVE_ACTIONS = frozenset({"ACCEPT", "DENY"})
_SHARE_ROLES = frozenset({"reader", "writer", "commenter"})


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


def _require_proposal_id(arguments: dict[str, Any]) -> str:
    proposal_id = str(arguments.get("proposal_id", "")).strip()
    if not proposal_id:
        raise ValueError("proposal_id is required")
    return proposal_id


def _require_approval_id(arguments: dict[str, Any]) -> str:
    approval_id = str(arguments.get("approval_id", "")).strip()
    if not approval_id:
        raise ValueError("approval_id is required")
    return approval_id


def _email_list(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("Expected an array of email addresses")
    emails: list[str] = []
    for item in values:
        email = str(item).strip()
        if email:
            emails.append(email)
    return emails


def _optional_message(arguments: dict[str, Any]) -> str | None:
    if "message" not in arguments or arguments["message"] is None:
        return None
    message = str(arguments["message"]).strip()
    return message or None


async def list_access_proposals_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    page_size = min(int(arguments.get("page_size", 100)), _MAX_PAGE_SIZE)
    page_token = str(arguments.get("page_token") or "").strip() or None

    def _call(service):
        kwargs: dict[str, Any] = {
            "fileId": file_id,
            "pageSize": page_size,
            "fields": ACCESS_PROPOSAL_LIST_FIELDS,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        return service.accessproposals().list(**kwargs).execute()

    response = await run_drive_call(user_id, _call)
    return {"file_id": file_id, **build_access_proposals_list_response(response)}


async def get_access_proposal_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    proposal_id = _require_proposal_id(arguments)

    def _call(service):
        return (
            service.accessproposals()
            .get(
                fileId=file_id,
                proposalId=proposal_id,
                fields=ACCESS_PROPOSAL_FIELDS,
            )
            .execute()
        )

    proposal = await run_drive_call(user_id, _call)
    return {"file_id": file_id, "access_proposal": compact_access_proposal(proposal)}


async def resolve_access_proposal_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    proposal_id = _require_proposal_id(arguments)
    action = str(arguments.get("action", "")).strip().upper()
    if action not in _RESOLVE_ACTIONS:
        raise ValueError("action must be ACCEPT or DENY")

    body: dict[str, Any] = {"action": action}
    if action == "ACCEPT":
        roles_raw = arguments.get("role") or arguments.get("roles") or ["reader"]
        if isinstance(roles_raw, str):
            roles_raw = [roles_raw]
        roles = [str(role).strip().lower() for role in roles_raw if str(role).strip()]
        if not roles:
            roles = ["reader"]
        invalid = [role for role in roles if role not in _SHARE_ROLES]
        if invalid:
            raise ValueError("role must be reader, writer, or commenter")
        body["role"] = roles
    if "send_notification" in arguments:
        body["sendNotification"] = bool(arguments["send_notification"])
    view = str(arguments.get("view") or "").strip()
    if view:
        body["view"] = view

    def _call(service):
        service.accessproposals().resolve(
            fileId=file_id,
            proposalId=proposal_id,
            body=body,
        ).execute()
        return {
            "resolved": True,
            "file_id": file_id,
            "proposal_id": proposal_id,
            "action": action,
        }

    return await run_drive_call(user_id, _call)


async def list_approvals_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    page_size = min(int(arguments.get("page_size", 100)), _MAX_PAGE_SIZE)
    page_token = str(arguments.get("page_token") or "").strip() or None

    def _call(service):
        kwargs: dict[str, Any] = {
            "fileId": file_id,
            "pageSize": page_size,
            "fields": APPROVAL_LIST_FIELDS,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        return service.approvals().list(**kwargs).execute()

    response = await run_drive_call(user_id, _call)
    return {"file_id": file_id, **build_approvals_list_response(response)}


async def get_approval_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    approval_id = _require_approval_id(arguments)

    def _call(service):
        return (
            service.approvals()
            .get(
                fileId=file_id,
                approvalId=approval_id,
                fields=APPROVAL_FIELDS,
            )
            .execute()
        )

    approval = await run_drive_call(user_id, _call)
    return {"file_id": file_id, "approval": compact_approval(approval)}


async def start_approval_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    reviewer_emails = _email_list(arguments.get("reviewer_emails"))
    if not reviewer_emails:
        raise ValueError("reviewer_emails is required")

    body: dict[str, Any] = {"reviewerEmails": reviewer_emails}
    message = _optional_message(arguments)
    if message:
        body["message"] = message
    if "lock_file" in arguments:
        body["lockFile"] = bool(arguments["lock_file"])
    due_time = str(arguments.get("due_time") or "").strip()
    if due_time:
        body["dueTime"] = due_time

    def _call(service):
        return (
            service.approvals()
            .start(fileId=file_id, body=body, fields=APPROVAL_FIELDS)
            .execute()
        )

    approval = await run_drive_call(user_id, _call)
    return {"started": True, "file_id": file_id, "approval": compact_approval(approval)}


async def approve_file_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    approval_id = _require_approval_id(arguments)
    body: dict[str, Any] = {}
    message = _optional_message(arguments)
    if message:
        body["message"] = message

    def _call(service):
        return (
            service.approvals()
            .approve(
                fileId=file_id,
                approvalId=approval_id,
                body=body,
                fields=APPROVAL_FIELDS,
            )
            .execute()
        )

    approval = await run_drive_call(user_id, _call)
    return {"approved": True, "file_id": file_id, "approval": compact_approval(approval)}


async def decline_approval_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    approval_id = _require_approval_id(arguments)
    body: dict[str, Any] = {}
    message = _optional_message(arguments)
    if message:
        body["message"] = message

    def _call(service):
        return (
            service.approvals()
            .decline(
                fileId=file_id,
                approvalId=approval_id,
                body=body,
                fields=APPROVAL_FIELDS,
            )
            .execute()
        )

    approval = await run_drive_call(user_id, _call)
    return {"declined": True, "file_id": file_id, "approval": compact_approval(approval)}


async def cancel_approval_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    approval_id = _require_approval_id(arguments)
    body: dict[str, Any] = {}
    message = _optional_message(arguments)
    if message:
        body["message"] = message

    def _call(service):
        return (
            service.approvals()
            .cancel(
                fileId=file_id,
                approvalId=approval_id,
                body=body,
                fields=APPROVAL_FIELDS,
            )
            .execute()
        )

    approval = await run_drive_call(user_id, _call)
    return {"cancelled": True, "file_id": file_id, "approval": compact_approval(approval)}


async def comment_approval_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    approval_id = _require_approval_id(arguments)
    message = _optional_message(arguments)
    if not message:
        raise ValueError("message is required")

    def _call(service):
        return (
            service.approvals()
            .comment(
                fileId=file_id,
                approvalId=approval_id,
                body={"message": message},
                fields=APPROVAL_FIELDS,
            )
            .execute()
        )

    approval = await run_drive_call(user_id, _call)
    return {"commented": True, "file_id": file_id, "approval": compact_approval(approval)}


async def reassign_approval_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id()
    file_id = _require_file_id(arguments)
    approval_id = _require_approval_id(arguments)
    body: dict[str, Any] = {}

    add_emails = _email_list(arguments.get("add_reviewer_emails"))
    if add_emails:
        body["addReviewers"] = [{"addedReviewerEmail": email} for email in add_emails]

    replace_reviewers = arguments.get("replace_reviewers") or []
    if replace_reviewers and not isinstance(replace_reviewers, list):
        raise ValueError("replace_reviewers must be an array")
    replacements: list[dict[str, str]] = []
    for item in replace_reviewers:
        if not isinstance(item, dict):
            raise ValueError("replace_reviewers items must be objects")
        removed = str(item.get("removed_reviewer_email") or "").strip()
        added = str(item.get("added_reviewer_email") or "").strip()
        if not removed or not added:
            raise ValueError(
                "replace_reviewers items require removed_reviewer_email and added_reviewer_email"
            )
        replacements.append(
            {
                "removedReviewerEmail": removed,
                "addedReviewerEmail": added,
            }
        )
    if replacements:
        body["replaceReviewers"] = replacements

    if not body:
        raise ValueError("Provide add_reviewer_emails and/or replace_reviewers")

    message = _optional_message(arguments)
    if message:
        body["message"] = message

    def _call(service):
        return (
            service.approvals()
            .reassign(
                fileId=file_id,
                approvalId=approval_id,
                body=body,
                fields=APPROVAL_FIELDS,
            )
            .execute()
        )

    approval = await run_drive_call(user_id, _call)
    return {"reassigned": True, "file_id": file_id, "approval": compact_approval(approval)}
