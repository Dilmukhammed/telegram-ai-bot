from __future__ import annotations

from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_LIVE_FETCH,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_USER_GOAL,
    FETCH_DRIVE_FILE,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    EvidenceRef,
    VerificationQuestion,
)

_USER_GOAL = EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal")

_LIVE_DRIVE_FILE = EvidenceRef(
    kind=EVIDENCE_LIVE_FETCH,
    fetch=FETCH_DRIVE_FILE,
    label="drive_file_live",
)

_PRIOR_FILE_READ = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "google.drive.get_file",
        "google.drive.search_files",
        "google.drive.list_files",
        "google.drive.list_folder",
        "google.drive.download_file",
        "google.drive.export_file",
    ),
    match=(("file_id", "$call.file_id"),),
    optional=True,
    max_age_steps=10,
    label="prior_file_read",
)

_PRIOR_DRIVE_SEARCH = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "google.drive.search_files",
        "google.drive.list_files",
        "google.drive.list_folder",
        "google.drive.list_starred",
        "google.drive.list_shared_with_me",
        "google.drive.list_recent",
    ),
    optional=True,
    max_age_steps=10,
    label="prior_drive_search",
)

_PRIOR_PERMISSIONS = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("google.drive.list_permissions", "google.drive.get_permission"),
    match=(("file_id", "$call.file_id"),),
    optional=True,
    max_age_steps=10,
    label="prior_permissions",
)

_PRIOR_SHARED_DRIVE = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("google.drive.list_shared_drives", "google.drive.get_shared_drive"),
    match=(("drive_id", "$call.drive_id"),),
    optional=True,
    max_age_steps=10,
    label="prior_shared_drive",
)

_PRIOR_DRIVE_CONTEXT = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_name_pattern="google.drive.*",
    optional=True,
    max_age_steps=10,
    label="prior_drive_context",
)


def _call(label: str, *fields: str) -> EvidenceRef:
    return EvidenceRef(kind=EVIDENCE_CALL, fields=fields, label=label)


# --- Settings / account ---

GOOGLE_DRIVE_GET_ABOUT_QUESTIONS = (
    VerificationQuestion(
        id="about_needed",
        text="Did the user ask for quota, storage, or account info that get_about provides?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL, _PRIOR_DRIVE_CONTEXT),
    ),
)

# --- File discovery (read) ---

GOOGLE_DRIVE_SEARCH_FILES_QUESTIONS = (
    VerificationQuestion(
        id="query_matches_intent",
        text="Does q filter for the file name, type, folder, or text the user asked to find?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("search_call", "q", "corpora", "drive_id", "include_trashed"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="scope_correct",
        text="Is corpora/drive_id scope correct (My Drive vs shared drive vs allDrives)?",
        severity=SEVERITY_WARN,
        evidence=(_call("search_call", "corpora", "drive_id"), _USER_GOAL, _PRIOR_DRIVE_CONTEXT),
    ),
    VerificationQuestion(
        id="trash_scope_intentional",
        text="If include_trashed=true, did the user explicitly want trashed files?",
        severity=SEVERITY_INFO,
        evidence=(_call("search_call", "include_trashed"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_LIST_FILES_QUESTIONS = (
    VerificationQuestion(
        id="folder_scope",
        text="Does folder_id limit listing to the folder the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_files_call", "folder_id", "page_size"), _USER_GOAL, _PRIOR_DRIVE_SEARCH),
    ),
    VerificationQuestion(
        id="pagination_sufficient",
        text="Is page_size enough to find the target file without missing it on the first page?",
        severity=SEVERITY_WARN,
        evidence=(_call("list_files_call", "page_size"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_GET_FILE_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Does file_id match the file the user asked about from prior search/list?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_file_call", "file_id"), _USER_GOAL, _PRIOR_DRIVE_SEARCH),
    ),
    VerificationQuestion(
        id="metadata_before_action",
        text="If a write/share/download follows, was metadata read for the right file?",
        severity=SEVERITY_INFO,
        evidence=(_call("get_file_call", "file_id"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_DOWNLOAD_FILE_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file the user asked to download (not a shortcut target unless intended)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("download_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ, _PRIOR_DRIVE_SEARCH),
    ),
    VerificationQuestion(
        id="native_google_format",
        text="For Google Docs/Sheets/Slides, should export_file have been used instead?",
        severity=SEVERITY_WARN,
        evidence=(_call("download_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
)

GOOGLE_DRIVE_EXPORT_FILE_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the Google Workspace file the user asked to export?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("export_call", "file_id", "mime_type"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="export_format_matches",
        text="Does mime_type match the format the user requested (pdf, csv, plain text)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("export_call", "mime_type"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_LIST_FOLDER_QUESTIONS = (
    VerificationQuestion(
        id="folder_id_correct",
        text="Does folder_id (or root default) match the folder the user asked to browse?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_folder_call", "folder_id"), _USER_GOAL, _PRIOR_DRIVE_CONTEXT),
    ),
)

GOOGLE_DRIVE_LIST_STARRED_QUESTIONS = (
    VerificationQuestion(
        id="starred_list_intent",
        text="Did the user ask for starred/favorite files specifically?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL, _PRIOR_DRIVE_CONTEXT),
    ),
)

GOOGLE_DRIVE_LIST_TRASH_QUESTIONS = (
    VerificationQuestion(
        id="trash_list_intent",
        text="Did the user ask to see trashed/deleted files?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

GOOGLE_DRIVE_LIST_SHARED_WITH_ME_QUESTIONS = (
    VerificationQuestion(
        id="shared_with_me_intent",
        text="Did the user ask for files shared with them (not their own Drive)?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

GOOGLE_DRIVE_LIST_RECENT_QUESTIONS = (
    VerificationQuestion(
        id="recent_list_intent",
        text="Did the user ask for recently opened/modified files?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

# --- File CRUD (write) ---

GOOGLE_DRIVE_CREATE_FOLDER_QUESTIONS = (
    VerificationQuestion(
        id="folder_name_matches",
        text="Does name match the folder name the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_folder_call", "name", "parent_id"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="parent_folder_correct",
        text="Is parent_id the destination folder the user specified (or root if omitted)?",
        severity=SEVERITY_WARN,
        evidence=(_call("create_folder_call", "parent_id"), _USER_GOAL, _PRIOR_DRIVE_SEARCH),
    ),
    VerificationQuestion(
        id="folder_created_live",
        text="Does live get_file on the created folder id show expected name and parent?",
        severity=SEVERITY_WARN,
        evidence=(_call("create_folder_call", "name", "parent_id"), _LIVE_DRIVE_FILE, _USER_GOAL),
    ),
)

GOOGLE_DRIVE_CREATE_FILE_QUESTIONS = (
    VerificationQuestion(
        id="name_and_type_match",
        text="Do name and mime_type match what the user asked to create?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_file_call", "name", "mime_type", "parent_id"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="parent_folder_correct",
        text="Is parent_id the folder where the user wanted the new file?",
        severity=SEVERITY_WARN,
        evidence=(_call("create_file_call", "parent_id"), _USER_GOAL, _PRIOR_DRIVE_SEARCH),
    ),
    VerificationQuestion(
        id="file_created_live",
        text="Does live get_file on the created file id show correct name and mimeType?",
        severity=SEVERITY_WARN,
        evidence=(_call("create_file_call", "name", "mime_type"), _LIVE_DRIVE_FILE, _USER_GOAL),
    ),
)

GOOGLE_DRIVE_UPLOAD_FILE_QUESTIONS = (
    VerificationQuestion(
        id="upload_name_and_parent",
        text="Do name and parent_id match where the user asked to save the upload?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("upload_call", "name", "parent_id", "mime_type", "path"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="content_provided",
        text="Was exactly one of path, content_text, or content_base64 provided for the file body?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("upload_call", "path", "content_text", "content_base64"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="workspace_path_from_user",
        text=(
            "If path is used, is it the workspace-relative path from the user upload "
            "(e.g. uploads/…) or a prior workspace tool result — not invented?"
        ),
        severity=SEVERITY_CRITICAL,
        evidence=(_call("upload_call", "path"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="upload_verified_live",
        text="Does live get_file on the uploaded file id confirm name and mimeType?",
        severity=SEVERITY_WARN,
        evidence=(_call("upload_call", "name", "mime_type", "path"), _LIVE_DRIVE_FILE, _USER_GOAL),
    ),
)

GOOGLE_DRIVE_UPDATE_FILE_METADATA_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file whose metadata the user asked to change?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_meta_call", "file_id", "name", "description", "starred"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="fields_match_intent",
        text="Do the changed fields (name, description, starred, properties) match user intent?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_meta_call", "name", "description", "starred", "properties"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="metadata_live_match",
        text="Does live get_file show the metadata changes applied?",
        severity=SEVERITY_WARN,
        evidence=(_call("update_meta_call", "file_id", "name", "starred"), _LIVE_DRIVE_FILE, _USER_GOAL),
    ),
)

GOOGLE_DRIVE_UPDATE_FILE_CONTENT_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the non-Google-native file the user asked to overwrite?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_content_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="content_provided",
        text="Was exactly one of path, content_text, or content_base64 provided for the new body?",
        severity=SEVERITY_CRITICAL,
        evidence=(
            _call("update_content_call", "path", "content_text", "content_base64", "mime_type"),
            _USER_GOAL,
        ),
    ),
    VerificationQuestion(
        id="not_google_native",
        text="Should this have been a Sheets/Docs edit flow instead of binary content replace?",
        severity=SEVERITY_WARN,
        evidence=(_call("update_content_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
)

GOOGLE_DRIVE_COPY_FILE_QUESTIONS = (
    VerificationQuestion(
        id="source_file_correct",
        text="Is file_id the source file the user asked to duplicate?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("copy_call", "file_id", "name", "parent_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="copy_destination",
        text="Do name and parent_id match where the user wanted the copy?",
        severity=SEVERITY_WARN,
        evidence=(_call("copy_call", "name", "parent_id"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_MOVE_FILE_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file the user asked to move?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("move_call", "file_id", "new_parent_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="destination_folder",
        text="Is new_parent_id the destination folder the user specified?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("move_call", "new_parent_id", "remove_parent_id"), _USER_GOAL, _PRIOR_DRIVE_SEARCH),
    ),
    VerificationQuestion(
        id="move_live_parents",
        text="Does live get_file show parents including new_parent_id?",
        severity=SEVERITY_WARN,
        evidence=(_call("move_call", "file_id", "new_parent_id"), _LIVE_DRIVE_FILE, _USER_GOAL),
    ),
)

GOOGLE_DRIVE_RENAME_FILE_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file the user asked to rename?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("rename_call", "file_id", "name"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="new_name_matches",
        text="Does name match the title the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("rename_call", "name"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="rename_live_match",
        text="Does live get_file show the new name?",
        severity=SEVERITY_WARN,
        evidence=(_call("rename_call", "file_id", "name"), _LIVE_DRIVE_FILE, _USER_GOAL),
    ),
)

GOOGLE_DRIVE_STAR_FILE_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file the user asked to star?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("star_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
)

GOOGLE_DRIVE_UNSTAR_FILE_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file the user asked to unstar?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("unstar_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
)

GOOGLE_DRIVE_TRASH_FILE_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file the user asked to delete/move to trash?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("trash_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="trash_not_permanent",
        text="Did the user want recoverable trash, not permanent delete (delete_file)?",
        severity=SEVERITY_WARN,
        evidence=(_call("trash_call", "file_id"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_UNTRASH_FILE_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the trashed file the user asked to restore?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("untrash_call", "file_id"), _USER_GOAL, _PRIOR_DRIVE_CONTEXT),
    ),
)

GOOGLE_DRIVE_DELETE_FILE_QUESTIONS = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Is confirm=true set for this irreversible permanent delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_call", "file_id", "confirm"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file the user explicitly asked to permanently delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="permanent_not_trash",
        text="Did the user want permanent delete, not recoverable trash?",
        severity=SEVERITY_WARN,
        evidence=(_call("delete_call", "file_id", "confirm"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_EMPTY_TRASH_QUESTIONS = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Is confirm=true set for emptying all trash permanently?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("empty_trash_call", "confirm"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="empty_trash_intent",
        text="Did the user explicitly ask to empty trash, not delete one file?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

GOOGLE_DRIVE_CREATE_SHORTCUT_QUESTIONS = (
    VerificationQuestion(
        id="target_file_correct",
        text="Is target_file_id the file/folder the shortcut should point to?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("shortcut_call", "target_file_id", "name", "parent_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="shortcut_location",
        text="Is parent_id where the user wanted the shortcut placed?",
        severity=SEVERITY_WARN,
        evidence=(_call("shortcut_call", "parent_id", "name"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_GENERATE_FILE_IDS_QUESTIONS = (
    VerificationQuestion(
        id="count_matches_need",
        text="Does count match how many preallocated ids the workflow needs?",
        severity=SEVERITY_WARN,
        evidence=(_call("generate_ids_call", "count"), _USER_GOAL),
    ),
)

# --- Permissions ---

GOOGLE_DRIVE_LIST_PERMISSIONS_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the shared file whose permissions the user asked to inspect?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_permissions_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
)

GOOGLE_DRIVE_GET_PERMISSION_QUESTIONS = (
    VerificationQuestion(
        id="permission_target",
        text="Do file_id and permission_id match the grant the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_permission_call", "file_id", "permission_id"), _USER_GOAL, _PRIOR_PERMISSIONS),
    ),
)

GOOGLE_DRIVE_SHARE_FILE_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file/folder the user asked to share?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("share_call", "file_id", "role", "type", "email"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="role_and_grantee_match",
        text="Do role, type, email/domain match who gets what access the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("share_call", "role", "type", "email", "domain"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="anyone_link_intentional",
        text="If type=anyone, did the user explicitly want a public link?",
        severity=SEVERITY_WARN,
        evidence=(_call("share_call", "type"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="share_live_file_exists",
        text="Does live get_file confirm the shared file still exists with expected metadata?",
        severity=SEVERITY_INFO,
        evidence=(_call("share_call", "file_id"), _LIVE_DRIVE_FILE, _USER_GOAL),
    ),
)

GOOGLE_DRIVE_UPDATE_PERMISSION_QUESTIONS = (
    VerificationQuestion(
        id="permission_target",
        text="Are file_id and permission_id the grant the user asked to change?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_permission_call", "file_id", "permission_id", "role"), _USER_GOAL, _PRIOR_PERMISSIONS),
    ),
    VerificationQuestion(
        id="new_role_matches",
        text="Does role match the access level the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_permission_call", "role"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_REMOVE_PERMISSION_QUESTIONS = (
    VerificationQuestion(
        id="permission_target",
        text="Are file_id and permission_id the access the user asked to revoke?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("remove_permission_call", "file_id", "permission_id"), _USER_GOAL, _PRIOR_PERMISSIONS),
    ),
    VerificationQuestion(
        id="revoke_not_gmail",
        text="Did the user want Drive permission removed, not an email notification?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
)

# --- Comments ---

GOOGLE_DRIVE_LIST_COMMENTS_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the document whose comments the user asked to list?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_comments_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
)

GOOGLE_DRIVE_GET_COMMENT_QUESTIONS = (
    VerificationQuestion(
        id="comment_target",
        text="Do file_id and comment_id match the comment the user asked to read?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_comment_call", "file_id", "comment_id"), _USER_GOAL, _PRIOR_DRIVE_CONTEXT),
    ),
)

GOOGLE_DRIVE_CREATE_COMMENT_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file the user asked to comment on?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_comment_call", "file_id", "content"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="content_matches",
        text="Does content reflect what the user asked to post?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_comment_call", "content"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_UPDATE_COMMENT_QUESTIONS = (
    VerificationQuestion(
        id="comment_target",
        text="Are file_id and comment_id the comment the user asked to edit?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_comment_call", "file_id", "comment_id", "content"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="content_matches",
        text="Does updated content match what the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_comment_call", "content"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_DELETE_COMMENT_QUESTIONS = (
    VerificationQuestion(
        id="comment_target",
        text="Are file_id and comment_id the comment the user asked to delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_comment_call", "file_id", "comment_id"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_LIST_REPLIES_QUESTIONS = (
    VerificationQuestion(
        id="thread_target",
        text="Do file_id and comment_id identify the comment thread the user asked to read?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_replies_call", "file_id", "comment_id"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_GET_REPLY_QUESTIONS = (
    VerificationQuestion(
        id="reply_target",
        text="Do file_id, comment_id, and reply_id match the reply the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_reply_call", "file_id", "comment_id", "reply_id"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_CREATE_REPLY_QUESTIONS = (
    VerificationQuestion(
        id="thread_target",
        text="Are file_id and comment_id the thread the user asked to reply in?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_reply_call", "file_id", "comment_id", "content"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="content_matches",
        text="Does reply content match what the user asked to send?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_reply_call", "content"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_UPDATE_REPLY_QUESTIONS = (
    VerificationQuestion(
        id="reply_target",
        text="Are file_id, comment_id, and reply_id the reply the user asked to edit?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_reply_call", "file_id", "comment_id", "reply_id", "content"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_DELETE_REPLY_QUESTIONS = (
    VerificationQuestion(
        id="reply_target",
        text="Are file_id, comment_id, and reply_id the reply the user asked to delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_reply_call", "file_id", "comment_id", "reply_id"), _USER_GOAL),
    ),
)

# --- Revisions ---

GOOGLE_DRIVE_LIST_REVISIONS_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file whose revision history the user asked to see?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_revisions_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
)

GOOGLE_DRIVE_GET_REVISION_QUESTIONS = (
    VerificationQuestion(
        id="revision_target",
        text="Do file_id and revision_id match the revision the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_revision_call", "file_id", "revision_id"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_UPDATE_REVISION_QUESTIONS = (
    VerificationQuestion(
        id="revision_target",
        text="Are file_id and revision_id the revision the user asked to update (keep forever)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_revision_call", "file_id", "revision_id", "keep_forever"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_DELETE_REVISION_QUESTIONS = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Is confirm=true set for permanently deleting this revision?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_revision_call", "file_id", "revision_id", "confirm"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="revision_target",
        text="Are file_id and revision_id the revision the user asked to delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_revision_call", "file_id", "revision_id"), _USER_GOAL),
    ),
)

# --- Changes feed ---

GOOGLE_DRIVE_GET_CHANGES_START_TOKEN_QUESTIONS = (
    VerificationQuestion(
        id="sync_bootstrap",
        text="Is this call part of an incremental sync the user or workflow requested?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL, _PRIOR_DRIVE_CONTEXT),
    ),
)

GOOGLE_DRIVE_LIST_CHANGES_QUESTIONS = (
    VerificationQuestion(
        id="page_token_valid",
        text="Is page_token from a prior get_changes_start_token or list_changes response?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_changes_call", "page_token", "drive_id"), _PRIOR_DRIVE_CONTEXT),
    ),
    VerificationQuestion(
        id="drive_scope",
        text="If drive_id is set, does it scope changes to the shared drive the user cares about?",
        severity=SEVERITY_WARN,
        evidence=(_call("list_changes_call", "drive_id"), _USER_GOAL),
    ),
)

# --- Shared drives ---

GOOGLE_DRIVE_LIST_SHARED_DRIVES_QUESTIONS = (
    VerificationQuestion(
        id="query_matches_intent",
        text="If q is set, does it filter for the team drive name the user asked for?",
        severity=SEVERITY_WARN,
        evidence=(_call("list_shared_drives_call", "q"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_GET_SHARED_DRIVE_QUESTIONS = (
    VerificationQuestion(
        id="drive_id_correct",
        text="Does drive_id match the shared drive the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_shared_drive_call", "drive_id"), _USER_GOAL, _PRIOR_SHARED_DRIVE),
    ),
)

GOOGLE_DRIVE_CREATE_SHARED_DRIVE_QUESTIONS = (
    VerificationQuestion(
        id="name_matches",
        text="Does name match the team drive the user asked to create?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_shared_drive_call", "name"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_UPDATE_SHARED_DRIVE_QUESTIONS = (
    VerificationQuestion(
        id="drive_id_correct",
        text="Is drive_id the shared drive the user asked to update?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_shared_drive_call", "drive_id", "name"), _USER_GOAL, _PRIOR_SHARED_DRIVE),
    ),
    VerificationQuestion(
        id="fields_match_intent",
        text="Do changed fields (name, theme, restrictions) match user intent?",
        severity=SEVERITY_WARN,
        evidence=(_call("update_shared_drive_call", "name", "hidden", "restrictions"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_DELETE_SHARED_DRIVE_QUESTIONS = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Is confirm=true set for permanently deleting the shared drive?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_shared_drive_call", "drive_id", "confirm"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="drive_id_correct",
        text="Is drive_id the team drive the user explicitly asked to delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_shared_drive_call", "drive_id"), _USER_GOAL, _PRIOR_SHARED_DRIVE),
    ),
)

GOOGLE_DRIVE_HIDE_SHARED_DRIVE_QUESTIONS = (
    VerificationQuestion(
        id="drive_id_correct",
        text="Is drive_id the shared drive the user asked to hide from their list?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("hide_shared_drive_call", "drive_id"), _USER_GOAL, _PRIOR_SHARED_DRIVE),
    ),
)

GOOGLE_DRIVE_UNHIDE_SHARED_DRIVE_QUESTIONS = (
    VerificationQuestion(
        id="drive_id_correct",
        text="Is drive_id the shared drive the user asked to show again?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("unhide_shared_drive_call", "drive_id"), _USER_GOAL, _PRIOR_SHARED_DRIVE),
    ),
)

# --- Labels ---

GOOGLE_DRIVE_LIST_FILE_LABELS_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file whose labels the user asked to inspect?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_labels_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
)

GOOGLE_DRIVE_MODIFY_FILE_LABELS_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file whose labels the user asked to add or remove?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("modify_labels_call", "file_id", "add_label_ids", "remove_label_ids"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="label_ids_match_intent",
        text="Do add_label_ids/remove_label_ids match the label changes the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("modify_labels_call", "add_label_ids", "remove_label_ids"), _USER_GOAL),
    ),
)

# --- Apps ---

GOOGLE_DRIVE_LIST_APPS_QUESTIONS = (
    VerificationQuestion(
        id="apps_list_intent",
        text="Did the user ask for installed Drive apps or open-with options?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

GOOGLE_DRIVE_GET_APP_QUESTIONS = (
    VerificationQuestion(
        id="app_id_correct",
        text="Is app_id the Drive app the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_app_call", "app_id"), _USER_GOAL),
    ),
)

# --- Access proposals ---

GOOGLE_DRIVE_LIST_ACCESS_PROPOSALS_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file whose pending access requests the user asked to list?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_proposals_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
)

GOOGLE_DRIVE_GET_ACCESS_PROPOSAL_QUESTIONS = (
    VerificationQuestion(
        id="proposal_target",
        text="Do file_id and proposal_id match the access request the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_proposal_call", "file_id", "proposal_id"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_RESOLVE_ACCESS_PROPOSAL_QUESTIONS = (
    VerificationQuestion(
        id="proposal_target",
        text="Are file_id and proposal_id the access request the user asked to approve/deny?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("resolve_proposal_call", "file_id", "proposal_id", "action"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="action_matches_intent",
        text="Does action (accept/deny) match what the user decided?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("resolve_proposal_call", "action"), _USER_GOAL),
    ),
)

# --- Approvals ---

GOOGLE_DRIVE_LIST_APPROVALS_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the file whose approval workflow the user asked to inspect?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_approvals_call", "file_id"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
)

GOOGLE_DRIVE_GET_APPROVAL_QUESTIONS = (
    VerificationQuestion(
        id="approval_target",
        text="Do file_id and approval_id match the approval the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_approval_call", "file_id", "approval_id"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_START_APPROVAL_QUESTIONS = (
    VerificationQuestion(
        id="file_id_correct",
        text="Is file_id the document the user asked to send for approval?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("start_approval_call", "file_id", "reviewer_emails"), _USER_GOAL, _PRIOR_FILE_READ),
    ),
    VerificationQuestion(
        id="reviewers_match",
        text="Do reviewer_emails match who the user asked to review?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("start_approval_call", "reviewer_emails"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_APPROVE_FILE_QUESTIONS = (
    VerificationQuestion(
        id="approval_target",
        text="Are file_id and approval_id the approval the user asked to approve?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("approve_call", "file_id", "approval_id"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_DECLINE_APPROVAL_QUESTIONS = (
    VerificationQuestion(
        id="approval_target",
        text="Are file_id and approval_id the approval the user asked to decline?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("decline_call", "file_id", "approval_id"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_CANCEL_APPROVAL_QUESTIONS = (
    VerificationQuestion(
        id="approval_target",
        text="Are file_id and approval_id the in-progress approval the user asked to cancel?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("cancel_approval_call", "file_id", "approval_id"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_COMMENT_APPROVAL_QUESTIONS = (
    VerificationQuestion(
        id="approval_target",
        text="Are file_id and approval_id the approval the user asked to comment on?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("comment_approval_call", "file_id", "approval_id", "comment"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="comment_matches",
        text="Does comment text match what the user asked to post?",
        severity=SEVERITY_WARN,
        evidence=(_call("comment_approval_call", "comment"), _USER_GOAL),
    ),
)

GOOGLE_DRIVE_REASSIGN_APPROVAL_QUESTIONS = (
    VerificationQuestion(
        id="approval_target",
        text="Are file_id and approval_id the approval whose reviewers the user asked to change?",
        severity=SEVERITY_CRITICAL,
        evidence=(
            _call(
                "reassign_call",
                "file_id",
                "approval_id",
                "add_reviewer_emails",
                "replace_reviewers",
            ),
            _USER_GOAL,
        ),
    ),
    VerificationQuestion(
        id="reviewer_changes_match",
        text="Do add_reviewer_emails/replace_reviewers match the reassignment the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("reassign_call", "add_reviewer_emails", "replace_reviewers"), _USER_GOAL),
    ),
)

DRIVE_CHECKER_QUESTIONS_BY_TOOL: dict[str, tuple[VerificationQuestion, ...]] = {
    "google.drive.get_about": GOOGLE_DRIVE_GET_ABOUT_QUESTIONS,
    "google.drive.search_files": GOOGLE_DRIVE_SEARCH_FILES_QUESTIONS,
    "google.drive.list_files": GOOGLE_DRIVE_LIST_FILES_QUESTIONS,
    "google.drive.get_file": GOOGLE_DRIVE_GET_FILE_QUESTIONS,
    "google.drive.download_file": GOOGLE_DRIVE_DOWNLOAD_FILE_QUESTIONS,
    "google.drive.export_file": GOOGLE_DRIVE_EXPORT_FILE_QUESTIONS,
    "google.drive.list_folder": GOOGLE_DRIVE_LIST_FOLDER_QUESTIONS,
    "google.drive.list_starred": GOOGLE_DRIVE_LIST_STARRED_QUESTIONS,
    "google.drive.list_trash": GOOGLE_DRIVE_LIST_TRASH_QUESTIONS,
    "google.drive.list_shared_with_me": GOOGLE_DRIVE_LIST_SHARED_WITH_ME_QUESTIONS,
    "google.drive.list_recent": GOOGLE_DRIVE_LIST_RECENT_QUESTIONS,
    "google.drive.create_folder": GOOGLE_DRIVE_CREATE_FOLDER_QUESTIONS,
    "google.drive.create_file": GOOGLE_DRIVE_CREATE_FILE_QUESTIONS,
    "google.drive.upload_file": GOOGLE_DRIVE_UPLOAD_FILE_QUESTIONS,
    "google.drive.update_file_metadata": GOOGLE_DRIVE_UPDATE_FILE_METADATA_QUESTIONS,
    "google.drive.update_file_content": GOOGLE_DRIVE_UPDATE_FILE_CONTENT_QUESTIONS,
    "google.drive.copy_file": GOOGLE_DRIVE_COPY_FILE_QUESTIONS,
    "google.drive.move_file": GOOGLE_DRIVE_MOVE_FILE_QUESTIONS,
    "google.drive.rename_file": GOOGLE_DRIVE_RENAME_FILE_QUESTIONS,
    "google.drive.star_file": GOOGLE_DRIVE_STAR_FILE_QUESTIONS,
    "google.drive.unstar_file": GOOGLE_DRIVE_UNSTAR_FILE_QUESTIONS,
    "google.drive.trash_file": GOOGLE_DRIVE_TRASH_FILE_QUESTIONS,
    "google.drive.untrash_file": GOOGLE_DRIVE_UNTRASH_FILE_QUESTIONS,
    "google.drive.delete_file": GOOGLE_DRIVE_DELETE_FILE_QUESTIONS,
    "google.drive.empty_trash": GOOGLE_DRIVE_EMPTY_TRASH_QUESTIONS,
    "google.drive.create_shortcut": GOOGLE_DRIVE_CREATE_SHORTCUT_QUESTIONS,
    "google.drive.generate_file_ids": GOOGLE_DRIVE_GENERATE_FILE_IDS_QUESTIONS,
    "google.drive.list_permissions": GOOGLE_DRIVE_LIST_PERMISSIONS_QUESTIONS,
    "google.drive.get_permission": GOOGLE_DRIVE_GET_PERMISSION_QUESTIONS,
    "google.drive.share_file": GOOGLE_DRIVE_SHARE_FILE_QUESTIONS,
    "google.drive.update_permission": GOOGLE_DRIVE_UPDATE_PERMISSION_QUESTIONS,
    "google.drive.remove_permission": GOOGLE_DRIVE_REMOVE_PERMISSION_QUESTIONS,
    "google.drive.list_comments": GOOGLE_DRIVE_LIST_COMMENTS_QUESTIONS,
    "google.drive.get_comment": GOOGLE_DRIVE_GET_COMMENT_QUESTIONS,
    "google.drive.create_comment": GOOGLE_DRIVE_CREATE_COMMENT_QUESTIONS,
    "google.drive.update_comment": GOOGLE_DRIVE_UPDATE_COMMENT_QUESTIONS,
    "google.drive.delete_comment": GOOGLE_DRIVE_DELETE_COMMENT_QUESTIONS,
    "google.drive.list_replies": GOOGLE_DRIVE_LIST_REPLIES_QUESTIONS,
    "google.drive.get_reply": GOOGLE_DRIVE_GET_REPLY_QUESTIONS,
    "google.drive.create_reply": GOOGLE_DRIVE_CREATE_REPLY_QUESTIONS,
    "google.drive.update_reply": GOOGLE_DRIVE_UPDATE_REPLY_QUESTIONS,
    "google.drive.delete_reply": GOOGLE_DRIVE_DELETE_REPLY_QUESTIONS,
    "google.drive.list_revisions": GOOGLE_DRIVE_LIST_REVISIONS_QUESTIONS,
    "google.drive.get_revision": GOOGLE_DRIVE_GET_REVISION_QUESTIONS,
    "google.drive.update_revision": GOOGLE_DRIVE_UPDATE_REVISION_QUESTIONS,
    "google.drive.delete_revision": GOOGLE_DRIVE_DELETE_REVISION_QUESTIONS,
    "google.drive.get_changes_start_token": GOOGLE_DRIVE_GET_CHANGES_START_TOKEN_QUESTIONS,
    "google.drive.list_changes": GOOGLE_DRIVE_LIST_CHANGES_QUESTIONS,
    "google.drive.list_shared_drives": GOOGLE_DRIVE_LIST_SHARED_DRIVES_QUESTIONS,
    "google.drive.get_shared_drive": GOOGLE_DRIVE_GET_SHARED_DRIVE_QUESTIONS,
    "google.drive.create_shared_drive": GOOGLE_DRIVE_CREATE_SHARED_DRIVE_QUESTIONS,
    "google.drive.update_shared_drive": GOOGLE_DRIVE_UPDATE_SHARED_DRIVE_QUESTIONS,
    "google.drive.delete_shared_drive": GOOGLE_DRIVE_DELETE_SHARED_DRIVE_QUESTIONS,
    "google.drive.hide_shared_drive": GOOGLE_DRIVE_HIDE_SHARED_DRIVE_QUESTIONS,
    "google.drive.unhide_shared_drive": GOOGLE_DRIVE_UNHIDE_SHARED_DRIVE_QUESTIONS,
    "google.drive.list_file_labels": GOOGLE_DRIVE_LIST_FILE_LABELS_QUESTIONS,
    "google.drive.modify_file_labels": GOOGLE_DRIVE_MODIFY_FILE_LABELS_QUESTIONS,
    "google.drive.list_apps": GOOGLE_DRIVE_LIST_APPS_QUESTIONS,
    "google.drive.get_app": GOOGLE_DRIVE_GET_APP_QUESTIONS,
    "google.drive.list_access_proposals": GOOGLE_DRIVE_LIST_ACCESS_PROPOSALS_QUESTIONS,
    "google.drive.get_access_proposal": GOOGLE_DRIVE_GET_ACCESS_PROPOSAL_QUESTIONS,
    "google.drive.resolve_access_proposal": GOOGLE_DRIVE_RESOLVE_ACCESS_PROPOSAL_QUESTIONS,
    "google.drive.list_approvals": GOOGLE_DRIVE_LIST_APPROVALS_QUESTIONS,
    "google.drive.get_approval": GOOGLE_DRIVE_GET_APPROVAL_QUESTIONS,
    "google.drive.start_approval": GOOGLE_DRIVE_START_APPROVAL_QUESTIONS,
    "google.drive.approve_file": GOOGLE_DRIVE_APPROVE_FILE_QUESTIONS,
    "google.drive.decline_approval": GOOGLE_DRIVE_DECLINE_APPROVAL_QUESTIONS,
    "google.drive.cancel_approval": GOOGLE_DRIVE_CANCEL_APPROVAL_QUESTIONS,
    "google.drive.comment_approval": GOOGLE_DRIVE_COMMENT_APPROVAL_QUESTIONS,
    "google.drive.reassign_approval": GOOGLE_DRIVE_REASSIGN_APPROVAL_QUESTIONS,
}

DRIVE_CHECKER_ALL_TOOL_NAMES = tuple(DRIVE_CHECKER_QUESTIONS_BY_TOOL.keys())

DRIVE_CHECKER_READ_TOOL_NAMES = tuple(
    name
    for name in DRIVE_CHECKER_ALL_TOOL_NAMES
    if name.endswith(
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
            ".list_permissions",
            ".get_permission",
            ".list_comments",
            ".get_comment",
            ".list_replies",
            ".get_reply",
            ".list_revisions",
            ".get_revision",
            ".get_changes_start_token",
            ".list_changes",
            ".list_shared_drives",
            ".get_shared_drive",
            ".list_file_labels",
            ".list_apps",
            ".get_app",
            ".list_access_proposals",
            ".get_access_proposal",
            ".list_approvals",
            ".get_approval",
        )
    )
)

DRIVE_CHECKER_WRITE_TOOL_NAMES = tuple(
    name for name in DRIVE_CHECKER_ALL_TOOL_NAMES if name not in DRIVE_CHECKER_READ_TOOL_NAMES
)
