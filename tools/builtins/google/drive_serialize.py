from __future__ import annotations

from typing import Any

GOOGLE_APPS_MIME_PREFIX = "application/vnd.google-apps."

DEFAULT_EXPORT_MIME_BY_GOOGLE_APP: dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.drawing": "image/png",
}

LIST_FILE_FIELDS = (
    "nextPageToken, files("
    "id, name, mimeType, size, modifiedTime, createdTime, parents, starred, trashed, "
    "webViewLink, webContentLink, owners, shortcutDetails"
    ")"
)

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
CREATE_FILE_FIELDS = "id, name, mimeType, webViewLink, size, parents"

GET_FILE_FIELDS = (
    "id, name, mimeType, size, modifiedTime, createdTime, parents, starred, trashed, "
    "webViewLink, webContentLink, owners, shortcutDetails, description, properties, "
    "capabilities, shared, viewedByMeTime"
)


def is_google_workspace_file(mime_type: str | None) -> bool:
    return bool(mime_type and mime_type.startswith(GOOGLE_APPS_MIME_PREFIX))


def default_export_mime(mime_type: str | None) -> str:
    if not mime_type:
        return "text/plain"
    return DEFAULT_EXPORT_MIME_BY_GOOGLE_APP.get(mime_type, "text/plain")


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


def compact_file_summary(file_obj: dict[str, Any]) -> dict[str, Any]:
    owners = file_obj.get("owners") or []
    owner_emails = [
        str(owner.get("emailAddress") or owner.get("displayName") or "").strip()
        for owner in owners
        if isinstance(owner, dict)
    ]
    shortcut = file_obj.get("shortcutDetails") or {}
    return {
        "id": file_obj.get("id"),
        "name": file_obj.get("name"),
        "mime_type": file_obj.get("mimeType"),
        "size": file_obj.get("size"),
        "modified_time": file_obj.get("modifiedTime"),
        "created_time": file_obj.get("createdTime"),
        "parents": file_obj.get("parents") or [],
        "starred": file_obj.get("starred"),
        "trashed": file_obj.get("trashed"),
        "web_view_link": file_obj.get("webViewLink"),
        "web_content_link": file_obj.get("webContentLink"),
        "owners": [email for email in owner_emails if email],
        "shortcut_target_id": shortcut.get("targetId"),
    }


def compact_file_detail(file_obj: dict[str, Any]) -> dict[str, Any]:
    return {
        **compact_file_summary(file_obj),
        "description": file_obj.get("description"),
        "properties": file_obj.get("properties") or {},
        "shared": file_obj.get("shared"),
        "viewed_by_me_time": file_obj.get("viewedByMeTime"),
        "capabilities": file_obj.get("capabilities") or {},
    }


def compact_about(about: dict[str, Any]) -> dict[str, Any]:
    user = about.get("user") or {}
    quota = about.get("storageQuota") or {}
    return {
        "user": {
            "display_name": user.get("displayName"),
            "email": user.get("emailAddress"),
        },
        "storage_quota": {
            "limit": quota.get("limit"),
            "usage": quota.get("usage"),
            "usage_in_drive": quota.get("usageInDrive"),
            "usage_in_trash": quota.get("usageInTrash"),
        },
        "max_upload_size": about.get("maxUploadSize"),
        "can_create_drives": about.get("canCreateDrives"),
        "import_formats": about.get("importFormats") or {},
        "export_formats": about.get("exportFormats") or {},
    }


def compact_created_file(file_obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": file_obj.get("id"),
        "name": file_obj.get("name"),
        "mime_type": file_obj.get("mimeType"),
        "web_view_link": file_obj.get("webViewLink"),
        "size": file_obj.get("size"),
        "parents": file_obj.get("parents") or [],
    }


def build_list_response(response: dict[str, Any]) -> dict[str, Any]:
    files = response.get("files") or []
    return {
        "count": len(files),
        "files": [compact_file_summary(item) for item in files],
        "next_page_token": response.get("nextPageToken"),
    }


PERMISSION_FIELDS = (
    "id, type, role, emailAddress, domain, displayName, deleted, expirationTime, allowFileDiscovery"
)
PERMISSION_LIST_FIELDS = f"nextPageToken, permissions({PERMISSION_FIELDS})"


def compact_permission(permission: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": permission.get("id"),
        "type": permission.get("type"),
        "role": permission.get("role"),
        "email_address": permission.get("emailAddress"),
        "domain": permission.get("domain"),
        "display_name": permission.get("displayName"),
        "deleted": permission.get("deleted"),
        "allow_file_discovery": permission.get("allowFileDiscovery"),
    }


def build_permissions_list_response(response: dict[str, Any]) -> dict[str, Any]:
    permissions = response.get("permissions") or []
    return {
        "count": len(permissions),
        "permissions": [compact_permission(item) for item in permissions],
        "next_page_token": response.get("nextPageToken"),
    }


def _compact_author(author: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(author, dict):
        return {}
    return {
        "display_name": author.get("displayName"),
        "email": author.get("emailAddress"),
    }


COMMENT_FIELDS = (
    "id, content, htmlContent, author, createdTime, modifiedTime, deleted, anchor, replyCount"
)
REPLY_FIELDS = "id, content, htmlContent, author, createdTime, modifiedTime, deleted, action"
COMMENT_LIST_FIELDS = f"nextPageToken, comments({COMMENT_FIELDS})"
REPLY_LIST_FIELDS = f"nextPageToken, replies({REPLY_FIELDS})"


def compact_comment(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": comment.get("id"),
        "content": comment.get("content"),
        "html_content": comment.get("htmlContent"),
        "author": _compact_author(comment.get("author")),
        "created_time": comment.get("createdTime"),
        "modified_time": comment.get("modifiedTime"),
        "deleted": comment.get("deleted"),
        "anchor": comment.get("anchor"),
        "reply_count": comment.get("replyCount"),
    }


def compact_reply(reply: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": reply.get("id"),
        "content": reply.get("content"),
        "html_content": reply.get("htmlContent"),
        "author": _compact_author(reply.get("author")),
        "created_time": reply.get("createdTime"),
        "modified_time": reply.get("modifiedTime"),
        "deleted": reply.get("deleted"),
        "action": reply.get("action"),
    }


def build_comments_list_response(response: dict[str, Any]) -> dict[str, Any]:
    comments = response.get("comments") or []
    return {
        "count": len(comments),
        "comments": [compact_comment(item) for item in comments],
        "next_page_token": response.get("nextPageToken"),
    }


def build_replies_list_response(response: dict[str, Any]) -> dict[str, Any]:
    replies = response.get("replies") or []
    return {
        "count": len(replies),
        "replies": [compact_reply(item) for item in replies],
        "next_page_token": response.get("nextPageToken"),
    }


REVISION_FIELDS = (
    "id, mimeType, modifiedTime, keepForever, originalFilename, size, published, lastModifyingUser"
)
REVISION_LIST_FIELDS = f"nextPageToken, revisions({REVISION_FIELDS})"
CHANGE_FILE_FIELDS = "id, name, mimeType, modifiedTime, trashed, parents, webViewLink"
CHANGE_LIST_FIELDS = (
    f"nextPageToken, newStartPageToken, changes("
    f"changeType, time, removed, fileId, file({CHANGE_FILE_FIELDS}))"
)


def compact_revision(revision: dict[str, Any]) -> dict[str, Any]:
    user = revision.get("lastModifyingUser") or {}
    return {
        "id": revision.get("id"),
        "mime_type": revision.get("mimeType"),
        "modified_time": revision.get("modifiedTime"),
        "keep_forever": revision.get("keepForever"),
        "original_filename": revision.get("originalFilename"),
        "size": revision.get("size"),
        "published": revision.get("published"),
        "last_modified_by": _compact_author(user),
    }


def build_revisions_list_response(response: dict[str, Any]) -> dict[str, Any]:
    revisions = response.get("revisions") or []
    return {
        "count": len(revisions),
        "revisions": [compact_revision(item) for item in revisions],
        "next_page_token": response.get("nextPageToken"),
    }


def compact_change(change: dict[str, Any]) -> dict[str, Any]:
    file_obj = change.get("file")
    payload: dict[str, Any] = {
        "change_type": change.get("changeType"),
        "time": change.get("time"),
        "removed": change.get("removed"),
        "file_id": change.get("fileId"),
    }
    if isinstance(file_obj, dict):
        payload["file"] = compact_file_summary(file_obj)
    return payload


def build_changes_list_response(response: dict[str, Any]) -> dict[str, Any]:
    changes = response.get("changes") or []
    return {
        "count": len(changes),
        "changes": [compact_change(item) for item in changes],
        "next_page_token": response.get("nextPageToken"),
        "new_start_page_token": response.get("newStartPageToken"),
    }


SHARED_DRIVE_FIELDS = "id, name, colorRgb, themeId, createdTime, hidden, capabilities, restrictions"
SHARED_DRIVE_LIST_FIELDS = f"nextPageToken, drives({SHARED_DRIVE_FIELDS})"


def compact_shared_drive(drive: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": drive.get("id"),
        "name": drive.get("name"),
        "color_rgb": drive.get("colorRgb"),
        "theme_id": drive.get("themeId"),
        "created_time": drive.get("createdTime"),
        "hidden": drive.get("hidden"),
        "capabilities": drive.get("capabilities") or {},
        "restrictions": drive.get("restrictions") or {},
    }


def build_shared_drives_list_response(response: dict[str, Any]) -> dict[str, Any]:
    drives = response.get("drives") or []
    return {
        "count": len(drives),
        "shared_drives": [compact_shared_drive(item) for item in drives],
        "next_page_token": response.get("nextPageToken"),
    }


LABEL_FIELDS = "id, revisionId, fields"
LABEL_LIST_FIELDS = f"nextPageToken, labels({LABEL_FIELDS})"
MODIFIED_LABEL_FIELDS = f"modifiedLabels({LABEL_FIELDS})"
APP_FIELDS = (
    "id, name, objectType, productId, productUrl, supportsCreate, supportsImport, "
    "supportsMultiOpen, shortDescription"
)
APP_LIST_FIELDS = f"nextPageToken, items({APP_FIELDS})"


def compact_label(label: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": label.get("id"),
        "revision_id": label.get("revisionId"),
        "fields": label.get("fields") or {},
    }


def build_labels_list_response(response: dict[str, Any]) -> dict[str, Any]:
    labels = response.get("labels") or []
    return {
        "count": len(labels),
        "labels": [compact_label(item) for item in labels],
        "next_page_token": response.get("nextPageToken"),
    }


def compact_app(app: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": app.get("id"),
        "name": app.get("name"),
        "object_type": app.get("objectType"),
        "product_id": app.get("productId"),
        "product_url": app.get("productUrl"),
        "supports_create": app.get("supportsCreate"),
        "supports_import": app.get("supportsImport"),
        "supports_multi_open": app.get("supportsMultiOpen"),
        "short_description": app.get("shortDescription"),
    }


def build_apps_list_response(response: dict[str, Any]) -> dict[str, Any]:
    items = response.get("items") or []
    return {
        "count": len(items),
        "apps": [compact_app(item) for item in items],
        "next_page_token": response.get("nextPageToken"),
    }


ACCESS_PROPOSAL_FIELDS = (
    "fileId, proposalId, requesterEmailAddress, recipientEmailAddress, "
    "rolesAndViews, requestMessage, createTime"
)
ACCESS_PROPOSAL_LIST_FIELDS = f"nextPageToken, accessProposals({ACCESS_PROPOSAL_FIELDS})"
APPROVAL_FIELDS = (
    "approvalId, targetFileId, createTime, modifyTime, completeTime, dueTime, "
    "status, initiator, reviewerResponses"
)
APPROVAL_LIST_FIELDS = f"nextPageToken, items({APPROVAL_FIELDS})"


def compact_access_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    roles_and_views = proposal.get("rolesAndViews") or []
    return {
        "file_id": proposal.get("fileId"),
        "proposal_id": proposal.get("proposalId"),
        "requester_email": proposal.get("requesterEmailAddress"),
        "recipient_email": proposal.get("recipientEmailAddress"),
        "request_message": proposal.get("requestMessage"),
        "create_time": proposal.get("createTime"),
        "roles_and_views": [
            {
                "role": item.get("role"),
                "view": item.get("view"),
            }
            for item in roles_and_views
            if isinstance(item, dict)
        ],
    }


def build_access_proposals_list_response(response: dict[str, Any]) -> dict[str, Any]:
    proposals = response.get("accessProposals") or []
    return {
        "count": len(proposals),
        "access_proposals": [compact_access_proposal(item) for item in proposals],
        "next_page_token": response.get("nextPageToken"),
    }


def compact_approval(approval: dict[str, Any]) -> dict[str, Any]:
    initiator = approval.get("initiator") or {}
    reviewer_responses = approval.get("reviewerResponses") or []
    return {
        "approval_id": approval.get("approvalId"),
        "target_file_id": approval.get("targetFileId"),
        "create_time": approval.get("createTime"),
        "modify_time": approval.get("modifyTime"),
        "complete_time": approval.get("completeTime"),
        "due_time": approval.get("dueTime"),
        "status": approval.get("status"),
        "initiator": _compact_author(initiator),
        "reviewer_responses": [
            {
                "response": item.get("response"),
                "reviewer": _compact_author((item.get("reviewer") or {})),
            }
            for item in reviewer_responses
            if isinstance(item, dict)
        ],
    }


def build_approvals_list_response(response: dict[str, Any]) -> dict[str, Any]:
    items = response.get("items") or []
    return {
        "count": len(items),
        "approvals": [compact_approval(item) for item in items],
        "next_page_token": response.get("nextPageToken"),
    }
