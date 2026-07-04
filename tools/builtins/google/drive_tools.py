from __future__ import annotations

from tools.builtins.google.drive_files import (
    copy_file_handler,
    create_file_handler,
    create_folder_handler,
    create_shortcut_handler,
    delete_file_handler,
    download_file_handler,
    empty_trash_handler,
    export_file_handler,
    generate_file_ids_handler,
    get_about_handler,
    get_file_handler,
    list_files_handler,
    list_folder_handler,
    list_recent_handler,
    list_shared_with_me_handler,
    list_starred_handler,
    list_trash_handler,
    move_file_handler,
    rename_file_handler,
    search_files_handler,
    star_file_handler,
    trash_file_handler,
    unstar_file_handler,
    untrash_file_handler,
    update_file_content_handler,
    update_file_metadata_handler,
    upload_file_handler,
)
from tools.builtins.google.drive_permissions import (
    get_permission_handler,
    list_permissions_handler,
    remove_permission_handler,
    share_file_handler,
    update_permission_handler,
)
from tools.builtins.google.drive_comments import (
    create_comment_handler,
    create_reply_handler,
    delete_comment_handler,
    delete_reply_handler,
    get_comment_handler,
    get_reply_handler,
    list_comments_handler,
    list_replies_handler,
    update_comment_handler,
    update_reply_handler,
)
from tools.builtins.google.drive_revisions import (
    delete_revision_handler,
    get_revision_handler,
    list_revisions_handler,
    update_revision_handler,
)
from tools.builtins.google.drive_changes import (
    get_changes_start_token_handler,
    list_changes_handler,
)
from tools.builtins.google.drive_shared import (
    create_shared_drive_handler,
    delete_shared_drive_handler,
    get_shared_drive_handler,
    hide_shared_drive_handler,
    list_shared_drives_handler,
    unhide_shared_drive_handler,
    update_shared_drive_handler,
)
from tools.builtins.google.drive_labels import (
    list_file_labels_handler,
    modify_file_labels_handler,
)
from tools.builtins.google.drive_apps import (
    get_app_handler,
    list_apps_handler,
)
from tools.builtins.google.drive_workspace import (
    approve_file_handler,
    cancel_approval_handler,
    comment_approval_handler,
    decline_approval_handler,
    get_access_proposal_handler,
    get_approval_handler,
    list_access_proposals_handler,
    list_approvals_handler,
    reassign_approval_handler,
    resolve_access_proposal_handler,
    start_approval_handler,
)
from tools.builtins.google.tool_hints import GOOGLE_DRIVE_OAUTH_HINT
from tools.schema import ToolSpec

_PAGE_SIZE_PARAM = {
    "type": "integer",
    "description": "Maximum number of files to return (default from config, max 100).",
}
_PAGE_TOKEN_PARAM = {
    "type": "string",
    "description": "Pagination token from a previous list/search response.",
}
_FILE_ID_PARAM = {
    "type": "string",
    "description": "Drive file id from search/list results.",
}
_PARENT_ID_PARAM = {
    "type": "string",
    "description": "Parent folder id, or 'root' for My Drive root.",
}
_CONFIRM_PARAM = {
    "type": "boolean",
    "description": "Must be true — operation is irreversible (permanent delete, not trash).",
}
_WRITE_RATE_LIMIT = (30, 60)
_READ_RATE_LIMIT = (60, 60)
_PERMISSION_ROLE_PARAM = {
    "type": "string",
    "enum": ["reader", "writer", "commenter"],
    "description": "Access level for the new permission.",
}
_PERMISSION_TYPE_PARAM = {
    "type": "string",
    "enum": ["user", "group", "domain", "anyone"],
    "description": "Grantee type. Use email for user/group, domain for domain-wide.",
}
_COMMENT_ID_PARAM = {
    "type": "string",
    "description": "Comment id from list_comments.",
}
_REPLY_ID_PARAM = {
    "type": "string",
    "description": "Reply id from list_replies.",
}
_CONTENT_PARAM = {
    "type": "string",
    "description": "Plain text comment or reply body.",
}
_REVISION_ID_PARAM = {
    "type": "string",
    "description": "Revision id from list_revisions.",
}
_CHANGES_RATE_LIMIT = (30, 60)
_SHARED_DRIVE_ID_PARAM = {
    "type": "string",
    "description": "Shared drive id from list_shared_drives.",
}
_PROPOSAL_ID_PARAM = {
    "type": "string",
    "description": "Access proposal id from list_access_proposals.",
}
_APPROVAL_ID_PARAM = {
    "type": "string",
    "description": "Approval id from list_approvals.",
}

GOOGLE_DRIVE_GET_ABOUT = ToolSpec(
    name="google.drive.get_about",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Get Drive account info: user, storage quota, upload limits.",
    parameters={"type": "object", "properties": {}},
    handler=get_about_handler,
    tags=("google", "drive", "settings", "read"),
    cache_ttl_seconds=300,
    parallel_safe=True,
    rate_limit=(30, 60),
    examples=("drive storage quota", "google drive account info"),
)

GOOGLE_DRIVE_SEARCH_FILES = ToolSpec(
    name="google.drive.search_files",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Search Drive files with query syntax (name contains, mimeType, fullText, parents). "
        "Returns metadata only — use get_file, export_file, or download_file for content."
    ),
    parameters={
        "type": "object",
        "properties": {
            "q": {
                "type": "string",
                "description": "Drive search query (required). Example: \"name contains 'report' and mimeType='application/pdf'\".",
            },
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
            "order_by": {
                "type": "string",
                "description": "Sort order, e.g. modifiedTime desc, name, viewedByMeTime desc.",
            },
            "corpora": {
                "type": "string",
                "enum": ["user", "drive", "allDrives"],
                "description": "Which file collection to search.",
            },
            "drive_id": {
                "type": "string",
                "description": "Shared drive id when corpora=drive.",
            },
            "include_trashed": {
                "type": "boolean",
                "description": "Include trashed files in search.",
                "default": False,
            },
        },
        "required": ["q"],
    },
    handler=search_files_handler,
    tags=("google", "drive", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("find pdf invoice in drive", "search drive for budget spreadsheet"),
)

GOOGLE_DRIVE_LIST_FILES = ToolSpec(
    name="google.drive.list_files",
    description=GOOGLE_DRIVE_OAUTH_HINT + "List Drive files, optionally filtered by folder_id.",
    parameters={
        "type": "object",
        "properties": {
            "folder_id": {
                "type": "string",
                "description": "Parent folder id. Omit for all non-trashed files.",
            },
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
            "order_by": {"type": "string"},
        },
    },
    handler=list_files_handler,
    tags=("google", "drive", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("list files in folder", "list my drive files"),
)

GOOGLE_DRIVE_GET_FILE = ToolSpec(
    name="google.drive.get_file",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Get one file metadata by file_id.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Drive file id from search/list results."},
        },
        "required": ["file_id"],
    },
    handler=get_file_handler,
    tags=("google", "drive", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("get drive file metadata", "drive file details"),
)

GOOGLE_DRIVE_DOWNLOAD_FILE = ToolSpec(
    name="google.drive.download_file",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Download file by file_id; stores on server and returns file_ref (+ text for small text files). "
        "For Google Docs/Sheets/Slides use export_file instead. "
        "Use telegram.send_file(file_ref) to deliver to the user in chat."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
        },
        "required": ["file_id"],
    },
    handler=download_file_handler,
    tags=("google", "drive", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    rate_limit=(20, 60),
    examples=("download pdf from drive", "read txt file from drive"),
)

GOOGLE_DRIVE_EXPORT_FILE = ToolSpec(
    name="google.drive.export_file",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Export Google Docs/Sheets/Slides; stores on server and returns file_ref "
        "(+ truncated text for text/csv exports). "
        "Use telegram.send_file(file_ref) to deliver to the user in chat."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "mime_type": {
                "type": "string",
                "description": "Export format, e.g. text/plain, text/csv, application/pdf.",
            },
        },
        "required": ["file_id"],
    },
    handler=export_file_handler,
    tags=("google", "drive", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    rate_limit=(20, 60),
    examples=("export google doc as text", "read google sheet csv"),
)

GOOGLE_DRIVE_LIST_FOLDER = ToolSpec(
    name="google.drive.list_folder",
    description=GOOGLE_DRIVE_OAUTH_HINT + "List files inside a folder (default: root).",
    parameters={
        "type": "object",
        "properties": {
            "folder_id": {
                "type": "string",
                "description": "Folder id or 'root'.",
                "default": "root",
            },
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
        },
    },
    handler=list_folder_handler,
    tags=("google", "drive", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("list root drive folder", "files in project folder"),
)

GOOGLE_DRIVE_LIST_STARRED = ToolSpec(
    name="google.drive.list_starred",
    description=GOOGLE_DRIVE_OAUTH_HINT + "List starred Drive files.",
    parameters={
        "type": "object",
        "properties": {
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
        },
    },
    handler=list_starred_handler,
    tags=("google", "drive", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("starred drive files", "my starred documents"),
)

GOOGLE_DRIVE_LIST_TRASH = ToolSpec(
    name="google.drive.list_trash",
    description=GOOGLE_DRIVE_OAUTH_HINT + "List trashed Drive files.",
    parameters={
        "type": "object",
        "properties": {
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
        },
    },
    handler=list_trash_handler,
    tags=("google", "drive", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("files in drive trash", "trashed documents"),
)

GOOGLE_DRIVE_LIST_SHARED_WITH_ME = ToolSpec(
    name="google.drive.list_shared_with_me",
    description=GOOGLE_DRIVE_OAUTH_HINT + "List files shared with the user.",
    parameters={
        "type": "object",
        "properties": {
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
        },
    },
    handler=list_shared_with_me_handler,
    tags=("google", "drive", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("shared with me drive files", "documents shared to me"),
)

GOOGLE_DRIVE_LIST_RECENT = ToolSpec(
    name="google.drive.list_recent",
    description=GOOGLE_DRIVE_OAUTH_HINT + "List recently viewed Drive files.",
    parameters={
        "type": "object",
        "properties": {
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
        },
    },
    handler=list_recent_handler,
    tags=("google", "drive", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=(60, 60),
    examples=("recent drive files", "recently opened documents"),
)

GOOGLE_DRIVE_CREATE_FOLDER = ToolSpec(
    name="google.drive.create_folder",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Create a folder in Drive.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Folder name (required)."},
            "parent_id": _PARENT_ID_PARAM,
        },
        "required": ["name"],
    },
    handler=create_folder_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("create drive folder", "new project folder in drive"),
)

GOOGLE_DRIVE_CREATE_FILE = ToolSpec(
    name="google.drive.create_file",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Create an empty file or Google Workspace doc by mime_type (metadata only, no content upload)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "mime_type": {
                "type": "string",
                "description": "e.g. application/vnd.google-apps.document, application/pdf.",
            },
            "parent_id": _PARENT_ID_PARAM,
            "description": {"type": "string"},
        },
        "required": ["name"],
    },
    handler=create_file_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("create empty google doc", "create drive file metadata"),
)

GOOGLE_DRIVE_UPLOAD_FILE = ToolSpec(
    name="google.drive.upload_file",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Upload a new file with content (text or base64). For Google Docs use create_file + export/edit flow."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "parent_id": _PARENT_ID_PARAM,
            "mime_type": {"type": "string", "description": "Content MIME type."},
            "content_text": {"type": "string", "description": "UTF-8 text content (mutually exclusive with content_base64)."},
            "content_base64": {"type": "string", "description": "Base64-encoded binary content."},
        },
        "required": ["name"],
    },
    handler=upload_file_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("upload txt file to drive", "save pdf to drive folder"),
)

GOOGLE_DRIVE_UPDATE_FILE_METADATA = ToolSpec(
    name="google.drive.update_file_metadata",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Update file metadata (name, description, starred, properties).",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "name": {"type": "string"},
            "description": {"type": "string"},
            "starred": {"type": "boolean"},
            "properties": {
                "type": "object",
                "description": "Custom key/value properties.",
                "additionalProperties": True,
            },
        },
        "required": ["file_id"],
    },
    handler=update_file_metadata_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("rename drive file", "star a drive document"),
)

GOOGLE_DRIVE_UPDATE_FILE_CONTENT = ToolSpec(
    name="google.drive.update_file_content",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Replace binary/text file content. Not for native Google Docs/Sheets/Slides."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "mime_type": {"type": "string"},
            "content_text": {"type": "string"},
            "content_base64": {"type": "string"},
        },
        "required": ["file_id"],
    },
    handler=update_file_content_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("update txt file in drive", "replace pdf content"),
)

GOOGLE_DRIVE_COPY_FILE = ToolSpec(
    name="google.drive.copy_file",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Copy a file, optionally with new name and parent folder.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "name": {"type": "string", "description": "Name for the copy."},
            "parent_id": _PARENT_ID_PARAM,
        },
        "required": ["file_id"],
    },
    handler=copy_file_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("copy drive file", "duplicate spreadsheet in drive"),
)

GOOGLE_DRIVE_MOVE_FILE = ToolSpec(
    name="google.drive.move_file",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Move a file to another folder (addParents + removeParents).",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "new_parent_id": {"type": "string", "description": "Destination folder id."},
            "remove_parent_id": {
                "type": "string",
                "description": "Parent to remove (default: all current parents).",
            },
        },
        "required": ["file_id", "new_parent_id"],
    },
    handler=move_file_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("move file to folder", "relocate drive document"),
)

GOOGLE_DRIVE_RENAME_FILE = ToolSpec(
    name="google.drive.rename_file",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Rename a file (sugar for update_file_metadata).",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "name": {"type": "string"},
        },
        "required": ["file_id", "name"],
    },
    handler=rename_file_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("rename drive file", "change document title"),
)

GOOGLE_DRIVE_STAR_FILE = ToolSpec(
    name="google.drive.star_file",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Star a file.",
    parameters={
        "type": "object",
        "properties": {"file_id": _FILE_ID_PARAM},
        "required": ["file_id"],
    },
    handler=star_file_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("star drive file", "favorite document"),
)

GOOGLE_DRIVE_UNSTAR_FILE = ToolSpec(
    name="google.drive.unstar_file",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Remove star from a file.",
    parameters={
        "type": "object",
        "properties": {"file_id": _FILE_ID_PARAM},
        "required": ["file_id"],
    },
    handler=unstar_file_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("unstar drive file", "remove star from document"),
)

GOOGLE_DRIVE_TRASH_FILE = ToolSpec(
    name="google.drive.trash_file",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Move a file to trash (recoverable via untrash_file).",
    parameters={
        "type": "object",
        "properties": {"file_id": _FILE_ID_PARAM},
        "required": ["file_id"],
    },
    handler=trash_file_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("trash drive file", "delete file to recycle bin"),
)

GOOGLE_DRIVE_UNTRASH_FILE = ToolSpec(
    name="google.drive.untrash_file",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Restore a file from trash.",
    parameters={
        "type": "object",
        "properties": {"file_id": _FILE_ID_PARAM},
        "required": ["file_id"],
    },
    handler=untrash_file_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("restore file from trash", "untrash drive document"),
)

GOOGLE_DRIVE_DELETE_FILE = ToolSpec(
    name="google.drive.delete_file",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Permanently delete a file (not trash). Requires confirm=true."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "confirm": _CONFIRM_PARAM,
        },
        "required": ["file_id", "confirm"],
    },
    handler=delete_file_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("permanently delete drive file", "erase file forever"),
)

GOOGLE_DRIVE_EMPTY_TRASH = ToolSpec(
    name="google.drive.empty_trash",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Permanently empty Drive trash. Requires confirm=true."
    ),
    parameters={
        "type": "object",
        "properties": {"confirm": _CONFIRM_PARAM},
        "required": ["confirm"],
    },
    handler=empty_trash_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("empty drive trash", "permanently clear trash"),
)

GOOGLE_DRIVE_CREATE_SHORTCUT = ToolSpec(
    name="google.drive.create_shortcut",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Create a shortcut to another Drive file.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "target_file_id": {"type": "string", "description": "File id to link to."},
            "parent_id": _PARENT_ID_PARAM,
        },
        "required": ["name", "target_file_id"],
    },
    handler=create_shortcut_handler,
    tags=("google", "drive", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("create drive shortcut", "link to file in folder"),
)

GOOGLE_DRIVE_GENERATE_FILE_IDS = ToolSpec(
    name="google.drive.generate_file_ids",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Pre-generate Drive file ids (max 10).",
    parameters={
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "Number of ids to generate (1–10, default 1).",
                "default": 1,
            },
        },
    },
    handler=generate_file_ids_handler,
    tags=("google", "drive", "write"),
    parallel_safe=True,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("generate drive file ids", "preallocate file id"),
)

GOOGLE_DRIVE_LIST_PERMISSIONS = ToolSpec(
    name="google.drive.list_permissions",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "List sharing permissions on a file or folder. Use before update/remove."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "page_size": {
                "type": "integer",
                "description": "Max permissions per page (default 100, max 100).",
            },
            "page_token": _PAGE_TOKEN_PARAM,
        },
        "required": ["file_id"],
    },
    handler=list_permissions_handler,
    tags=("google", "drive", "permissions", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("who has access to drive file", "list file sharing permissions"),
)

GOOGLE_DRIVE_GET_PERMISSION = ToolSpec(
    name="google.drive.get_permission",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Get one permission by permission_id.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "permission_id": {
                "type": "string",
                "description": "Permission id from list_permissions.",
            },
        },
        "required": ["file_id", "permission_id"],
    },
    handler=get_permission_handler,
    tags=("google", "drive", "permissions", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("get drive permission details", "check sharing role for user"),
)

GOOGLE_DRIVE_SHARE_FILE = ToolSpec(
    name="google.drive.share_file",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Share a file or folder (permissions.create). Not email send — use Gmail for that. "
        "type=anyone creates a public link permission."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "role": _PERMISSION_ROLE_PARAM,
            "type": _PERMISSION_TYPE_PARAM,
            "email": {
                "type": "string",
                "description": "Email address when type is user or group.",
            },
            "domain": {
                "type": "string",
                "description": "Domain name when type is domain.",
            },
            "send_notification": {
                "type": "boolean",
                "description": "Send Google notification email to grantee.",
                "default": True,
            },
        },
        "required": ["file_id"],
    },
    handler=share_file_handler,
    tags=("google", "drive", "permissions", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("share drive file read only", "give editor access to document"),
)

GOOGLE_DRIVE_UPDATE_PERMISSION = ToolSpec(
    name="google.drive.update_permission",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Change role on an existing permission.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "permission_id": {
                "type": "string",
                "description": "Permission id from list_permissions.",
            },
            "role": {
                "type": "string",
                "enum": ["reader", "writer", "commenter", "owner", "organizer", "fileOrganizer"],
                "description": "New access level.",
            },
        },
        "required": ["file_id", "permission_id", "role"],
    },
    handler=update_permission_handler,
    tags=("google", "drive", "permissions", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("change drive share to viewer", "upgrade permission to writer"),
)

GOOGLE_DRIVE_REMOVE_PERMISSION = ToolSpec(
    name="google.drive.remove_permission",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Remove a sharing permission from a file.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "permission_id": {
                "type": "string",
                "description": "Permission id from list_permissions.",
            },
        },
        "required": ["file_id", "permission_id"],
    },
    handler=remove_permission_handler,
    tags=("google", "drive", "permissions", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("revoke drive access", "remove user from shared file"),
)

GOOGLE_DRIVE_LIST_COMMENTS = ToolSpec(
    name="google.drive.list_comments",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "List comments on a Drive file (Google Docs/Sheets/Slides and other supported files)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
            "include_deleted": {
                "type": "boolean",
                "description": "Include deleted comments.",
                "default": False,
            },
        },
        "required": ["file_id"],
    },
    handler=list_comments_handler,
    tags=("google", "drive", "comments", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("comments on google doc", "list drive file comments"),
)

GOOGLE_DRIVE_GET_COMMENT = ToolSpec(
    name="google.drive.get_comment",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Get one comment by comment_id.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "comment_id": _COMMENT_ID_PARAM,
        },
        "required": ["file_id", "comment_id"],
    },
    handler=get_comment_handler,
    tags=("google", "drive", "comments", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("get drive comment details", "read comment thread"),
)

GOOGLE_DRIVE_CREATE_COMMENT = ToolSpec(
    name="google.drive.create_comment",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Add a plain-text comment on a Drive file. Works on Google Workspace files."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "content": _CONTENT_PARAM,
        },
        "required": ["file_id", "content"],
    },
    handler=create_comment_handler,
    tags=("google", "drive", "comments", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("comment on google doc", "leave note on drive file"),
)

GOOGLE_DRIVE_UPDATE_COMMENT = ToolSpec(
    name="google.drive.update_comment",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Update comment text (author only).",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "comment_id": _COMMENT_ID_PARAM,
            "content": _CONTENT_PARAM,
        },
        "required": ["file_id", "comment_id", "content"],
    },
    handler=update_comment_handler,
    tags=("google", "drive", "comments", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("edit drive comment", "update comment text"),
)

GOOGLE_DRIVE_DELETE_COMMENT = ToolSpec(
    name="google.drive.delete_comment",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Delete a comment from a file.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "comment_id": _COMMENT_ID_PARAM,
        },
        "required": ["file_id", "comment_id"],
    },
    handler=delete_comment_handler,
    tags=("google", "drive", "comments", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("delete drive comment", "remove comment from doc"),
)

GOOGLE_DRIVE_LIST_REPLIES = ToolSpec(
    name="google.drive.list_replies",
    description=GOOGLE_DRIVE_OAUTH_HINT + "List replies under a comment.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "comment_id": _COMMENT_ID_PARAM,
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
            "include_deleted": {
                "type": "boolean",
                "default": False,
            },
        },
        "required": ["file_id", "comment_id"],
    },
    handler=list_replies_handler,
    tags=("google", "drive", "comments", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("replies to drive comment", "comment thread replies"),
)

GOOGLE_DRIVE_GET_REPLY = ToolSpec(
    name="google.drive.get_reply",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Get one reply by reply_id.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "comment_id": _COMMENT_ID_PARAM,
            "reply_id": _REPLY_ID_PARAM,
        },
        "required": ["file_id", "comment_id", "reply_id"],
    },
    handler=get_reply_handler,
    tags=("google", "drive", "comments", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("get drive reply", "read comment reply"),
)

GOOGLE_DRIVE_CREATE_REPLY = ToolSpec(
    name="google.drive.create_reply",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Reply to an existing comment.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "comment_id": _COMMENT_ID_PARAM,
            "content": _CONTENT_PARAM,
        },
        "required": ["file_id", "comment_id", "content"],
    },
    handler=create_reply_handler,
    tags=("google", "drive", "comments", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("reply to drive comment", "answer comment thread"),
)

GOOGLE_DRIVE_UPDATE_REPLY = ToolSpec(
    name="google.drive.update_reply",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Update reply text (author only).",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "comment_id": _COMMENT_ID_PARAM,
            "reply_id": _REPLY_ID_PARAM,
            "content": _CONTENT_PARAM,
        },
        "required": ["file_id", "comment_id", "reply_id", "content"],
    },
    handler=update_reply_handler,
    tags=("google", "drive", "comments", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("edit drive reply", "update comment reply"),
)

GOOGLE_DRIVE_DELETE_REPLY = ToolSpec(
    name="google.drive.delete_reply",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Delete a reply from a comment thread.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "comment_id": _COMMENT_ID_PARAM,
            "reply_id": _REPLY_ID_PARAM,
        },
        "required": ["file_id", "comment_id", "reply_id"],
    },
    handler=delete_reply_handler,
    tags=("google", "drive", "comments", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("delete drive reply", "remove comment reply"),
)

GOOGLE_DRIVE_LIST_REVISIONS = ToolSpec(
    name="google.drive.list_revisions",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "List file revision history (best for binary uploads like PDF). "
        "Google Docs native files may have incomplete revision lists."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
        },
        "required": ["file_id"],
    },
    handler=list_revisions_handler,
    tags=("google", "drive", "revisions", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("file version history", "list pdf revisions"),
)

GOOGLE_DRIVE_GET_REVISION = ToolSpec(
    name="google.drive.get_revision",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Get one revision metadata by revision_id.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "revision_id": _REVISION_ID_PARAM,
        },
        "required": ["file_id", "revision_id"],
    },
    handler=get_revision_handler,
    tags=("google", "drive", "revisions", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("get drive revision details", "revision metadata"),
)

GOOGLE_DRIVE_UPDATE_REVISION = ToolSpec(
    name="google.drive.update_revision",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Pin or unpin a revision (keepForever) to prevent automatic pruning."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "revision_id": _REVISION_ID_PARAM,
            "keep_forever": {
                "type": "boolean",
                "description": "True to keep revision forever; false to allow pruning.",
            },
        },
        "required": ["file_id", "revision_id", "keep_forever"],
    },
    handler=update_revision_handler,
    tags=("google", "drive", "revisions", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("pin drive revision", "keep file version forever"),
)

GOOGLE_DRIVE_DELETE_REVISION = ToolSpec(
    name="google.drive.delete_revision",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Permanently delete one file revision. Requires confirm=true."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "revision_id": _REVISION_ID_PARAM,
            "confirm": _CONFIRM_PARAM,
        },
        "required": ["file_id", "revision_id", "confirm"],
    },
    handler=delete_revision_handler,
    tags=("google", "drive", "revisions", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("delete old file revision", "remove drive version"),
)

GOOGLE_DRIVE_GET_CHANGES_START_TOKEN = ToolSpec(
    name="google.drive.get_changes_start_token",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Get a page token to start incremental change tracking via list_changes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "drive_id": {
                "type": "string",
                "description": "Optional shared drive id to track changes for one drive.",
            },
        },
    },
    handler=get_changes_start_token_handler,
    tags=("google", "drive", "changes", "read"),
    cache_ttl_seconds=0,
    parallel_safe=True,
    rate_limit=_CHANGES_RATE_LIMIT,
    examples=("drive sync start token", "changes page token"),
)

GOOGLE_DRIVE_LIST_CHANGES = ToolSpec(
    name="google.drive.list_changes",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "List Drive changes since a page_token. Returns new_start_page_token for the next poll."
    ),
    parameters={
        "type": "object",
        "properties": {
            "page_token": {
                "type": "string",
                "description": "Token from get_changes_start_token or prior list_changes.",
            },
            "page_size": _PAGE_SIZE_PARAM,
            "drive_id": {
                "type": "string",
                "description": "Optional shared drive id to scope changes.",
            },
        },
        "required": ["page_token"],
    },
    handler=list_changes_handler,
    tags=("google", "drive", "changes", "read"),
    cache_ttl_seconds=0,
    parallel_safe=True,
    rate_limit=_CHANGES_RATE_LIMIT,
    examples=("what changed in drive", "incremental drive sync"),
)

GOOGLE_DRIVE_LIST_SHARED_DRIVES = ToolSpec(
    name="google.drive.list_shared_drives",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "List shared drives (Team Drives) the user can access."
    ),
    parameters={
        "type": "object",
        "properties": {
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
            "q": {
                "type": "string",
                "description": "Optional query, e.g. \"name contains 'Engineering'\".",
            },
        },
    },
    handler=list_shared_drives_handler,
    tags=("google", "drive", "shared_drives", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("list team drives", "shared drives in workspace"),
)

GOOGLE_DRIVE_GET_SHARED_DRIVE = ToolSpec(
    name="google.drive.get_shared_drive",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Get one shared drive by drive_id.",
    parameters={
        "type": "object",
        "properties": {
            "drive_id": _SHARED_DRIVE_ID_PARAM,
        },
        "required": ["drive_id"],
    },
    handler=get_shared_drive_handler,
    tags=("google", "drive", "shared_drives", "read"),
    cache_ttl_seconds=120,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("shared drive details", "team drive metadata"),
)

GOOGLE_DRIVE_CREATE_SHARED_DRIVE = ToolSpec(
    name="google.drive.create_shared_drive",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Create a shared drive. Requires Workspace permissions. "
        "request_id is a UUID for idempotency (auto-generated if omitted)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Shared drive name."},
            "request_id": {
                "type": "string",
                "description": "UUID for idempotent create.",
            },
            "color_rgb": {"type": "string", "description": "Theme color, e.g. #FF0000."},
            "theme_id": {"type": "string"},
            "hidden": {"type": "boolean"},
            "restrictions": {
                "type": "object",
                "description": "Shared drive restrictions object.",
                "additionalProperties": True,
            },
        },
        "required": ["name"],
    },
    handler=create_shared_drive_handler,
    tags=("google", "drive", "shared_drives", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("create team drive", "new shared drive"),
)

GOOGLE_DRIVE_UPDATE_SHARED_DRIVE = ToolSpec(
    name="google.drive.update_shared_drive",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Update shared drive metadata (name, theme, restrictions).",
    parameters={
        "type": "object",
        "properties": {
            "drive_id": _SHARED_DRIVE_ID_PARAM,
            "name": {"type": "string"},
            "color_rgb": {"type": "string"},
            "theme_id": {"type": "string"},
            "hidden": {"type": "boolean"},
            "restrictions": {
                "type": "object",
                "additionalProperties": True,
            },
        },
        "required": ["drive_id"],
    },
    handler=update_shared_drive_handler,
    tags=("google", "drive", "shared_drives", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("rename team drive", "update shared drive settings"),
)

GOOGLE_DRIVE_DELETE_SHARED_DRIVE = ToolSpec(
    name="google.drive.delete_shared_drive",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Permanently delete a shared drive. Requires confirm=true and admin rights."
    ),
    parameters={
        "type": "object",
        "properties": {
            "drive_id": _SHARED_DRIVE_ID_PARAM,
            "confirm": _CONFIRM_PARAM,
        },
        "required": ["drive_id", "confirm"],
    },
    handler=delete_shared_drive_handler,
    tags=("google", "drive", "shared_drives", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("delete team drive", "remove shared drive permanently"),
)

GOOGLE_DRIVE_HIDE_SHARED_DRIVE = ToolSpec(
    name="google.drive.hide_shared_drive",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Hide a shared drive from the user's default shared drive list."
    ),
    parameters={
        "type": "object",
        "properties": {
            "drive_id": _SHARED_DRIVE_ID_PARAM,
        },
        "required": ["drive_id"],
    },
    handler=hide_shared_drive_handler,
    tags=("google", "drive", "shared_drives", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("hide team drive", "remove shared drive from sidebar"),
)

GOOGLE_DRIVE_UNHIDE_SHARED_DRIVE = ToolSpec(
    name="google.drive.unhide_shared_drive",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Unhide a shared drive in the user's list.",
    parameters={
        "type": "object",
        "properties": {
            "drive_id": _SHARED_DRIVE_ID_PARAM,
        },
        "required": ["drive_id"],
    },
    handler=unhide_shared_drive_handler,
    tags=("google", "drive", "shared_drives", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("unhide team drive", "show shared drive again"),
)

GOOGLE_DRIVE_LIST_FILE_LABELS = ToolSpec(
    name="google.drive.list_file_labels",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "List Drive labels applied to a file (Workspace label policies)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
        },
        "required": ["file_id"],
    },
    handler=list_file_labels_handler,
    tags=("google", "drive", "labels", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("labels on drive file", "file metadata labels"),
)

GOOGLE_DRIVE_MODIFY_FILE_LABELS = ToolSpec(
    name="google.drive.modify_file_labels",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Add or remove label ids on a file via files.modifyLabels."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "add_labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Label ids to apply to the file.",
            },
            "remove_labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Label ids to remove from the file.",
            },
        },
        "required": ["file_id"],
    },
    handler=modify_file_labels_handler,
    tags=("google", "drive", "labels", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("add label to drive file", "remove file label"),
)

GOOGLE_DRIVE_LIST_APPS = ToolSpec(
    name="google.drive.list_apps",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "List connected Drive apps (Open with / Create with integrations)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
            "app_filter_extensions": {
                "type": "string",
                "description": "Comma-separated file extensions filter.",
            },
            "app_filter_mime_types": {
                "type": "string",
                "description": "Comma-separated MIME types filter.",
            },
            "language_code": {
                "type": "string",
                "description": "BCP-47 language code for app descriptions.",
            },
        },
    },
    handler=list_apps_handler,
    tags=("google", "drive", "settings", "read"),
    cache_ttl_seconds=300,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("connected drive apps", "open with apps list"),
)

GOOGLE_DRIVE_GET_APP = ToolSpec(
    name="google.drive.get_app",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Get one connected Drive app by app_id.",
    parameters={
        "type": "object",
        "properties": {
            "app_id": {
                "type": "string",
                "description": "App id from list_apps.",
            },
        },
        "required": ["app_id"],
    },
    handler=get_app_handler,
    tags=("google", "drive", "settings", "read"),
    cache_ttl_seconds=600,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("drive app details", "connected app metadata"),
)

GOOGLE_DRIVE_LIST_ACCESS_PROPOSALS = ToolSpec(
    name="google.drive.list_access_proposals",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "List pending access proposals on a file (Google Workspace). Approver only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
        },
        "required": ["file_id"],
    },
    handler=list_access_proposals_handler,
    tags=("google", "drive", "workspace", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("pending drive access requests", "access proposals on file"),
)

GOOGLE_DRIVE_GET_ACCESS_PROPOSAL = ToolSpec(
    name="google.drive.get_access_proposal",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Get one access proposal by proposal_id.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "proposal_id": _PROPOSAL_ID_PARAM,
        },
        "required": ["file_id", "proposal_id"],
    },
    handler=get_access_proposal_handler,
    tags=("google", "drive", "workspace", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("access proposal details", "pending access request info"),
)

GOOGLE_DRIVE_RESOLVE_ACCESS_PROPOSAL = ToolSpec(
    name="google.drive.resolve_access_proposal",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Accept or deny an access proposal. action=ACCEPT requires role reader/writer/commenter."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "proposal_id": _PROPOSAL_ID_PARAM,
            "action": {
                "type": "string",
                "enum": ["ACCEPT", "DENY"],
                "description": "Accept or deny the proposal.",
            },
            "role": {
                "type": "array",
                "items": {"type": "string", "enum": ["reader", "writer", "commenter"]},
                "description": "Required for ACCEPT. Defaults to reader.",
            },
            "send_notification": {"type": "boolean"},
            "view": {
                "type": "string",
                "description": "Only published is supported when proposal has a view.",
            },
        },
        "required": ["file_id", "proposal_id", "action"],
    },
    handler=resolve_access_proposal_handler,
    tags=("google", "drive", "workspace", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("accept drive access request", "deny file access proposal"),
)

GOOGLE_DRIVE_LIST_APPROVALS = ToolSpec(
    name="google.drive.list_approvals",
    description=GOOGLE_DRIVE_OAUTH_HINT + "List formal approvals on a file (Google Workspace).",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "page_size": _PAGE_SIZE_PARAM,
            "page_token": _PAGE_TOKEN_PARAM,
        },
        "required": ["file_id"],
    },
    handler=list_approvals_handler,
    tags=("google", "drive", "workspace", "read"),
    cache_ttl_seconds=30,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("file approval requests", "drive approval status list"),
)

GOOGLE_DRIVE_GET_APPROVAL = ToolSpec(
    name="google.drive.get_approval",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Get one approval by approval_id.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "approval_id": _APPROVAL_ID_PARAM,
        },
        "required": ["file_id", "approval_id"],
    },
    handler=get_approval_handler,
    tags=("google", "drive", "workspace", "read"),
    cache_ttl_seconds=60,
    parallel_safe=True,
    rate_limit=_READ_RATE_LIMIT,
    examples=("approval details", "drive approval metadata"),
)

GOOGLE_DRIVE_START_APPROVAL = ToolSpec(
    name="google.drive.start_approval",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Start a formal approval workflow on a file.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "reviewer_emails": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Reviewer email addresses.",
            },
            "message": {"type": "string"},
            "due_time": {
                "type": "string",
                "description": "RFC3339 due time, e.g. 2026-07-10T17:00:00Z.",
            },
            "lock_file": {"type": "boolean"},
        },
        "required": ["file_id", "reviewer_emails"],
    },
    handler=start_approval_handler,
    tags=("google", "drive", "workspace", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("start document approval", "request file review"),
)

GOOGLE_DRIVE_APPROVE_FILE = ToolSpec(
    name="google.drive.approve_file",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Approve an in-progress approval as a reviewer.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "approval_id": _APPROVAL_ID_PARAM,
            "message": {"type": "string"},
        },
        "required": ["file_id", "approval_id"],
    },
    handler=approve_file_handler,
    tags=("google", "drive", "workspace", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("approve drive document", "sign off file approval"),
)

GOOGLE_DRIVE_DECLINE_APPROVAL = ToolSpec(
    name="google.drive.decline_approval",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Decline an in-progress approval as a reviewer.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "approval_id": _APPROVAL_ID_PARAM,
            "message": {"type": "string"},
        },
        "required": ["file_id", "approval_id"],
    },
    handler=decline_approval_handler,
    tags=("google", "drive", "workspace", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("decline file approval", "reject document approval"),
)

GOOGLE_DRIVE_CANCEL_APPROVAL = ToolSpec(
    name="google.drive.cancel_approval",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Cancel an in-progress approval as initiator.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "approval_id": _APPROVAL_ID_PARAM,
            "message": {"type": "string"},
        },
        "required": ["file_id", "approval_id"],
    },
    handler=cancel_approval_handler,
    tags=("google", "drive", "workspace", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("cancel approval request", "stop file approval"),
)

GOOGLE_DRIVE_COMMENT_APPROVAL = ToolSpec(
    name="google.drive.comment_approval",
    description=GOOGLE_DRIVE_OAUTH_HINT + "Comment on an in-progress approval.",
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "approval_id": _APPROVAL_ID_PARAM,
            "message": {"type": "string", "description": "Comment text (required)."},
        },
        "required": ["file_id", "approval_id", "message"],
    },
    handler=comment_approval_handler,
    tags=("google", "drive", "workspace", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("comment on approval", "add approval note"),
)

GOOGLE_DRIVE_REASSIGN_APPROVAL = ToolSpec(
    name="google.drive.reassign_approval",
    description=(
        GOOGLE_DRIVE_OAUTH_HINT
        + "Add or replace reviewers on an in-progress approval."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": _FILE_ID_PARAM,
            "approval_id": _APPROVAL_ID_PARAM,
            "add_reviewer_emails": {
                "type": "array",
                "items": {"type": "string"},
            },
            "replace_reviewers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "removed_reviewer_email": {"type": "string"},
                        "added_reviewer_email": {"type": "string"},
                    },
                    "required": ["removed_reviewer_email", "added_reviewer_email"],
                },
            },
            "message": {"type": "string"},
        },
        "required": ["file_id", "approval_id"],
    },
    handler=reassign_approval_handler,
    tags=("google", "drive", "workspace", "write"),
    parallel_safe=False,
    rate_limit=_WRITE_RATE_LIMIT,
    examples=("reassign approval reviewer", "add reviewer to approval"),
)

GOOGLE_DRIVE_TOOLS: tuple[ToolSpec, ...] = (
    GOOGLE_DRIVE_GET_ABOUT,
    GOOGLE_DRIVE_SEARCH_FILES,
    GOOGLE_DRIVE_LIST_FILES,
    GOOGLE_DRIVE_GET_FILE,
    GOOGLE_DRIVE_DOWNLOAD_FILE,
    GOOGLE_DRIVE_EXPORT_FILE,
    GOOGLE_DRIVE_LIST_FOLDER,
    GOOGLE_DRIVE_LIST_STARRED,
    GOOGLE_DRIVE_LIST_TRASH,
    GOOGLE_DRIVE_LIST_SHARED_WITH_ME,
    GOOGLE_DRIVE_LIST_RECENT,
    GOOGLE_DRIVE_CREATE_FOLDER,
    GOOGLE_DRIVE_CREATE_FILE,
    GOOGLE_DRIVE_UPLOAD_FILE,
    GOOGLE_DRIVE_UPDATE_FILE_METADATA,
    GOOGLE_DRIVE_UPDATE_FILE_CONTENT,
    GOOGLE_DRIVE_COPY_FILE,
    GOOGLE_DRIVE_MOVE_FILE,
    GOOGLE_DRIVE_RENAME_FILE,
    GOOGLE_DRIVE_STAR_FILE,
    GOOGLE_DRIVE_UNSTAR_FILE,
    GOOGLE_DRIVE_TRASH_FILE,
    GOOGLE_DRIVE_UNTRASH_FILE,
    GOOGLE_DRIVE_DELETE_FILE,
    GOOGLE_DRIVE_EMPTY_TRASH,
    GOOGLE_DRIVE_CREATE_SHORTCUT,
    GOOGLE_DRIVE_GENERATE_FILE_IDS,
    GOOGLE_DRIVE_LIST_PERMISSIONS,
    GOOGLE_DRIVE_GET_PERMISSION,
    GOOGLE_DRIVE_SHARE_FILE,
    GOOGLE_DRIVE_UPDATE_PERMISSION,
    GOOGLE_DRIVE_REMOVE_PERMISSION,
    GOOGLE_DRIVE_LIST_COMMENTS,
    GOOGLE_DRIVE_GET_COMMENT,
    GOOGLE_DRIVE_CREATE_COMMENT,
    GOOGLE_DRIVE_UPDATE_COMMENT,
    GOOGLE_DRIVE_DELETE_COMMENT,
    GOOGLE_DRIVE_LIST_REPLIES,
    GOOGLE_DRIVE_GET_REPLY,
    GOOGLE_DRIVE_CREATE_REPLY,
    GOOGLE_DRIVE_UPDATE_REPLY,
    GOOGLE_DRIVE_DELETE_REPLY,
    GOOGLE_DRIVE_LIST_REVISIONS,
    GOOGLE_DRIVE_GET_REVISION,
    GOOGLE_DRIVE_UPDATE_REVISION,
    GOOGLE_DRIVE_DELETE_REVISION,
    GOOGLE_DRIVE_GET_CHANGES_START_TOKEN,
    GOOGLE_DRIVE_LIST_CHANGES,
    GOOGLE_DRIVE_LIST_SHARED_DRIVES,
    GOOGLE_DRIVE_GET_SHARED_DRIVE,
    GOOGLE_DRIVE_CREATE_SHARED_DRIVE,
    GOOGLE_DRIVE_UPDATE_SHARED_DRIVE,
    GOOGLE_DRIVE_DELETE_SHARED_DRIVE,
    GOOGLE_DRIVE_HIDE_SHARED_DRIVE,
    GOOGLE_DRIVE_UNHIDE_SHARED_DRIVE,
    GOOGLE_DRIVE_LIST_FILE_LABELS,
    GOOGLE_DRIVE_MODIFY_FILE_LABELS,
    GOOGLE_DRIVE_LIST_APPS,
    GOOGLE_DRIVE_GET_APP,
    GOOGLE_DRIVE_LIST_ACCESS_PROPOSALS,
    GOOGLE_DRIVE_GET_ACCESS_PROPOSAL,
    GOOGLE_DRIVE_RESOLVE_ACCESS_PROPOSAL,
    GOOGLE_DRIVE_LIST_APPROVALS,
    GOOGLE_DRIVE_GET_APPROVAL,
    GOOGLE_DRIVE_START_APPROVAL,
    GOOGLE_DRIVE_APPROVE_FILE,
    GOOGLE_DRIVE_DECLINE_APPROVAL,
    GOOGLE_DRIVE_CANCEL_APPROVAL,
    GOOGLE_DRIVE_COMMENT_APPROVAL,
    GOOGLE_DRIVE_REASSIGN_APPROVAL,
)

DRIVE_TOOL_NAMES = frozenset(tool.name for tool in GOOGLE_DRIVE_TOOLS)
DRIVE1_TOOL_NAMES = frozenset(
    name for name in DRIVE_TOOL_NAMES if name.endswith(
        (
            ".get_about",
            ".search_files",
            ".list_files",
            ".get_file",
            ".download_file",
            ".export_file",
            ".list_folder",
            ".list_starred",
            ".list_trash",
            ".list_shared_with_me",
            ".list_recent",
        )
    )
)
DRIVE2_TOOL_NAMES = frozenset(
    name for name in DRIVE_TOOL_NAMES if name.endswith(
        (
            ".create_folder",
            ".create_file",
            ".upload_file",
            ".update_file_metadata",
            ".update_file_content",
            ".copy_file",
            ".move_file",
            ".rename_file",
            ".star_file",
            ".unstar_file",
            ".trash_file",
            ".untrash_file",
            ".delete_file",
            ".empty_trash",
            ".create_shortcut",
            ".generate_file_ids",
        )
    )
)
DRIVE3_TOOL_NAMES = frozenset(
    name for name in DRIVE_TOOL_NAMES if name.endswith(
        (
            ".list_permissions",
            ".get_permission",
            ".share_file",
            ".update_permission",
            ".remove_permission",
        )
    )
)
DRIVE4_TOOL_NAMES = frozenset(
    name for name in DRIVE_TOOL_NAMES if name.endswith(
        (
            ".list_comments",
            ".get_comment",
            ".create_comment",
            ".update_comment",
            ".delete_comment",
            ".list_replies",
            ".get_reply",
            ".create_reply",
            ".update_reply",
            ".delete_reply",
        )
    )
)
DRIVE5_TOOL_NAMES = frozenset(
    name for name in DRIVE_TOOL_NAMES if name.endswith(
        (
            ".list_revisions",
            ".get_revision",
            ".update_revision",
            ".delete_revision",
            ".get_changes_start_token",
            ".list_changes",
        )
    )
)
DRIVE6_TOOL_NAMES = frozenset(
    name for name in DRIVE_TOOL_NAMES if name.endswith(
        (
            ".list_shared_drives",
            ".get_shared_drive",
            ".create_shared_drive",
            ".update_shared_drive",
            ".delete_shared_drive",
            ".hide_shared_drive",
            ".unhide_shared_drive",
        )
    )
)
DRIVE7_TOOL_NAMES = frozenset(
    name for name in DRIVE_TOOL_NAMES if name.endswith(
        (
            ".list_file_labels",
            ".modify_file_labels",
            ".list_apps",
            ".get_app",
        )
    )
)
DRIVE8_TOOL_NAMES = frozenset(
    name for name in DRIVE_TOOL_NAMES if name.endswith(
        (
            ".list_access_proposals",
            ".get_access_proposal",
            ".resolve_access_proposal",
            ".list_approvals",
            ".get_approval",
            ".start_approval",
            ".approve_file",
            ".decline_approval",
            ".cancel_approval",
            ".comment_approval",
            ".reassign_approval",
        )
    )
)
