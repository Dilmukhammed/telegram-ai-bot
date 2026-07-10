from __future__ import annotations

from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_LIVE_FETCH,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_USER_GOAL,
    FETCH_GMAIL_MESSAGE,
    FETCH_GMAIL_SENT_MESSAGE,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    EvidenceRef,
    VerificationQuestion,
)

_USER_GOAL = EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal")

_LIVE_SENT_MESSAGE = EvidenceRef(
    kind=EVIDENCE_LIVE_FETCH,
    fetch=FETCH_GMAIL_SENT_MESSAGE,
    label="gmail_sent_live",
)

_LIVE_SOURCE_MESSAGE = EvidenceRef(
    kind=EVIDENCE_LIVE_FETCH,
    fetch=FETCH_GMAIL_MESSAGE,
    label="gmail_source_message_live",
)

_PRIOR_GMAIL_READ = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_name_pattern="google.gmail.*",
    optional=True,
    max_age_steps=10,
    label="prior_gmail_context",
)

_PRIOR_MESSAGE = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "google.gmail.get_message",
        "google.gmail.search_messages",
        "google.gmail.list_inbox",
        "google.gmail.list_unread",
        "google.gmail.list_messages",
        "google.gmail.get_thread",
    ),
    match=(("message_id", "$call.message_id"),),
    optional=True,
    label="prior_message_in_trace",
)

_PRIOR_THREAD = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "google.gmail.get_thread",
        "google.gmail.list_threads",
        "google.gmail.search_messages",
        "google.gmail.list_inbox",
    ),
    match=(("thread_id", "$call.thread_id"),),
    optional=True,
    label="prior_thread_in_trace",
)

_PRIOR_LABELS = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("google.gmail.list_labels", "google.gmail.get_label"),
    optional=True,
    max_age_steps=8,
    label="prior_labels_context",
)

_PRIOR_DRAFT = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("google.gmail.get_draft", "google.gmail.list_drafts"),
    match=(("draft_id", "$call.draft_id"),),
    optional=True,
    label="prior_draft_in_trace",
)

_PRIOR_FILTERS = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("google.gmail.list_filters", "google.gmail.get_filter"),
    optional=True,
    max_age_steps=8,
    label="prior_filters_context",
)

_PRIOR_SEND_AS = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("google.gmail.list_send_as", "google.gmail.get_send_as"),
    optional=True,
    max_age_steps=8,
    label="prior_send_as_context",
)

_PRIOR_VACATION = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("google.gmail.get_vacation_settings",),
    optional=True,
    max_age_steps=6,
    label="prior_vacation_settings",
)

# --- Call evidence ---

_GET_PROFILE_CALL = EvidenceRef(kind=EVIDENCE_CALL, fields=(), label="get_profile_call")
_LIST_LABELS_CALL = EvidenceRef(kind=EVIDENCE_CALL, fields=(), label="list_labels_call")
_GET_LABEL_CALL = EvidenceRef(kind=EVIDENCE_CALL, fields=("label_id",), label="get_label_call")
_SEARCH_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("q", "max_results", "include_spam_trash"),
    label="search_messages_call",
)
_LIST_MESSAGES_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("label_ids", "max_results", "include_spam_trash"),
    label="list_messages_call",
)
_GET_MESSAGE_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("message_id", "format"), label="get_message_call"
)
_LIST_INBOX_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("max_results",), label="list_inbox_call"
)
_LIST_UNREAD_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("max_results", "include_spam_trash"), label="list_unread_call"
)
_LIST_THREADS_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("q", "label_ids", "max_results", "include_spam_trash"),
    label="list_threads_call",
)
_GET_THREAD_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("thread_id", "format"), label="get_thread_call"
)
_GET_ATTACHMENT_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("message_id", "attachment_id"),
    label="get_attachment_call",
)
_MODIFY_MESSAGE_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("message_id", "add_label_ids", "remove_label_ids"),
    label="modify_message_call",
)
_MODIFY_THREAD_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("thread_id", "add_label_ids", "remove_label_ids"),
    label="modify_thread_call",
)
_MSG_OR_THREAD_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("message_id", "thread_id"),
    label="message_or_thread_call",
)
_TRASH_MSG_CALL = EvidenceRef(kind=EVIDENCE_CALL, fields=("message_id",), label="trash_message_call")
_TRASH_THREAD_CALL = EvidenceRef(kind=EVIDENCE_CALL, fields=("thread_id",), label="trash_thread_call")
_SEND_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("to", "cc", "bcc", "subject", "body_text", "body_html", "from_send_as"),
    label="send_message_call",
)
_REPLY_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("message_id", "reply_all", "body_text", "body_html", "from_send_as"),
    label="reply_call",
)
_FORWARD_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("message_id", "to", "cc", "bcc", "body_text", "from_send_as"),
    label="forward_call",
)
_CREATE_LABEL_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("name", "label_list_visibility", "message_list_visibility"),
    label="create_label_call",
)
_UPDATE_LABEL_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("label_id", "name", "label_list_visibility", "message_list_visibility"),
    label="update_label_call",
)
_DELETE_LABEL_CALL = EvidenceRef(kind=EVIDENCE_CALL, fields=("label_id",), label="delete_label_call")
_BATCH_MODIFY_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("message_ids", "add_label_ids", "remove_label_ids"),
    label="batch_modify_call",
)
_LIST_DRAFTS_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("max_results",), label="list_drafts_call"
)
_GET_DRAFT_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("draft_id", "format"), label="get_draft_call"
)
_DRAFT_COMPOSE_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("draft_id", "to", "cc", "bcc", "subject", "body_text", "body_html", "from_send_as"),
    label="draft_compose_call",
)
_SEND_DRAFT_CALL = EvidenceRef(kind=EVIDENCE_CALL, fields=("draft_id",), label="send_draft_call")
_DELETE_DRAFT_CALL = EvidenceRef(kind=EVIDENCE_CALL, fields=("draft_id",), label="delete_draft_call")
_DELETE_MESSAGE_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("message_id", "confirm"), label="delete_message_call"
)
_BATCH_DELETE_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("message_ids", "confirm"),
    label="batch_delete_call",
)
_LIST_FILTERS_CALL = EvidenceRef(kind=EVIDENCE_CALL, fields=(), label="list_filters_call")
_GET_FILTER_CALL = EvidenceRef(kind=EVIDENCE_CALL, fields=("filter_id",), label="get_filter_call")
_CREATE_FILTER_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("criteria", "action"), label="create_filter_call"
)
_DELETE_FILTER_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("filter_id",), label="delete_filter_call"
)
_GET_VACATION_CALL = EvidenceRef(kind=EVIDENCE_CALL, fields=(), label="get_vacation_call")
_UPDATE_VACATION_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=(
        "enable_auto_reply",
        "response_subject",
        "response_body_plain_text",
        "response_body_html",
        "restrict_to_contacts",
        "restrict_to_domain",
        "start_time",
        "end_time",
    ),
    label="update_vacation_call",
)
_LIST_SEND_AS_CALL = EvidenceRef(kind=EVIDENCE_CALL, fields=(), label="list_send_as_call")
_GET_SEND_AS_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("send_as_email",), label="get_send_as_call"
)
_PATCH_SEND_AS_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("send_as_email", "display_name", "reply_to_address", "signature", "is_default"),
    label="patch_send_as_call",
)
_IMPORT_MESSAGE_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("to", "subject", "body_text", "body_html", "label_ids", "thread_id", "never_mark_spam"),
    label="import_message_call",
)

# --- Read tools (18) ---

GOOGLE_GMAIL_GET_PROFILE_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="profile_needed_for_goal",
        text="Was fetching the mailbox profile needed for the user's request (address, counts)?",
        severity=SEVERITY_WARN,
        evidence=(_GET_PROFILE_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_LIST_LABELS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="needed_for_label_action",
        text="Was listing labels necessary before applying, creating, or explaining a label?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_LABELS_CALL, _USER_GOAL, _PRIOR_GMAIL_READ),
    ),
)

GOOGLE_GMAIL_GET_LABEL_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="label_id_matches_intent",
        text="Does label_id match the label the user asked about (INBOX, custom name, etc.)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_GET_LABEL_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
)

GOOGLE_GMAIL_SEARCH_MESSAGES_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="query_matches_intent",
        text="Does the Gmail search query (from:, subject:, is:unread, dates) match what the user wants to find?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SEARCH_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="scope_appropriate",
        text="Are max_results and include_spam_trash appropriate (not missing the target email)?",
        severity=SEVERITY_WARN,
        evidence=(_SEARCH_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="search_before_action",
        text="If a reply/forward/label follows, does this search locate the right message(s)?",
        severity=SEVERITY_WARN,
        evidence=(_SEARCH_CALL, _USER_GOAL, _PRIOR_GMAIL_READ),
    ),
)

GOOGLE_GMAIL_LIST_MESSAGES_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="label_filter_correct",
        text="Do label_ids filter to the mailbox slice the user asked for?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIST_MESSAGES_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
    VerificationQuestion(
        id="result_limit_sufficient",
        text="Is max_results enough to include the message the user cares about?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_MESSAGES_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_GET_MESSAGE_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="message_id_from_context",
        text="Does message_id match the email the user referred to from search/list/thread?",
        severity=SEVERITY_CRITICAL,
        evidence=(_GET_MESSAGE_CALL, _USER_GOAL, _PRIOR_MESSAGE, _PRIOR_GMAIL_READ),
    ),
    VerificationQuestion(
        id="format_sufficient",
        text="Is format (full/metadata/minimal) enough for the user's goal (body vs headers only)?",
        severity=SEVERITY_WARN,
        evidence=(_GET_MESSAGE_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="message_found",
        text="Did the call return message content (not error for a valid id)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_GET_MESSAGE_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_LIST_INBOX_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="inbox_is_what_user_wanted",
        text="Did the user ask for inbox/recent mail (not unread-only or a search query)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIST_INBOX_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="result_limit_sufficient",
        text="Is max_results enough for 'show my inbox' without hiding relevant mail?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_INBOX_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_LIST_UNREAD_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="unread_is_what_user_wanted",
        text="Did the user ask specifically for unread/new mail?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIST_UNREAD_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="not_duplicate_search",
        text="Was list_unread better than search_messages(q=is:unread) for this request?",
        severity=SEVERITY_INFO,
        evidence=(_LIST_UNREAD_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_LIST_THREADS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="query_or_labels_match_intent",
        text="Do q and/or label_ids match the conversations the user wants?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIST_THREADS_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
    VerificationQuestion(
        id="threads_not_messages_preferred",
        text="Was thread-level listing appropriate (user cares about conversations, not single messages)?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_THREADS_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_GET_THREAD_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="thread_id_from_context",
        text="Does thread_id match the conversation the user asked to open?",
        severity=SEVERITY_CRITICAL,
        evidence=(_GET_THREAD_CALL, _USER_GOAL, _PRIOR_THREAD, _PRIOR_GMAIL_READ),
    ),
    VerificationQuestion(
        id="format_sufficient",
        text="Is format sufficient to read the thread for the user's goal?",
        severity=SEVERITY_WARN,
        evidence=(_GET_THREAD_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_GET_ATTACHMENT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="message_and_attachment_correct",
        text="Do message_id and attachment_id match the file the user asked to download?",
        severity=SEVERITY_CRITICAL,
        evidence=(_GET_ATTACHMENT_CALL, _USER_GOAL, _PRIOR_MESSAGE),
    ),
    VerificationQuestion(
        id="attachment_metadata_seen",
        text="Was attachment metadata from get_message used to pick the right attachment_id?",
        severity=SEVERITY_WARN,
        evidence=(_GET_ATTACHMENT_CALL, _PRIOR_MESSAGE, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_LIST_DRAFTS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="needed_before_draft_action",
        text="Was listing drafts needed to pick draft_id for send/update/delete?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_DRAFTS_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_GET_DRAFT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="draft_id_from_context",
        text="Does draft_id match the draft the user asked to view or edit?",
        severity=SEVERITY_CRITICAL,
        evidence=(_GET_DRAFT_CALL, _USER_GOAL, _PRIOR_DRAFT),
    ),
    VerificationQuestion(
        id="review_before_send",
        text="If send_draft follows, was draft content reviewed for recipients and body?",
        severity=SEVERITY_WARN,
        evidence=(_GET_DRAFT_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_LIST_FILTERS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="needed_for_filter_management",
        text="Was listing filters needed before create/update/delete of a rule?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_FILTERS_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_GET_FILTER_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="filter_id_matches_intent",
        text="Does filter_id match the mail rule the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_GET_FILTER_CALL, _USER_GOAL, _PRIOR_FILTERS),
    ),
)

GOOGLE_GMAIL_GET_VACATION_SETTINGS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="needed_before_update",
        text="Was reading vacation settings needed before changing out-of-office?",
        severity=SEVERITY_WARN,
        evidence=(_GET_VACATION_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_LIST_SEND_AS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="needed_for_alias_pick",
        text="Was listing send-as aliases needed before send or patch_send_as?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_SEND_AS_CALL, _USER_GOAL, _PRIOR_SEND_AS),
    ),
)

GOOGLE_GMAIL_GET_SEND_AS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="alias_matches_intent",
        text="Does send_as_email match the alias the user wants to use or configure?",
        severity=SEVERITY_CRITICAL,
        evidence=(_GET_SEND_AS_CALL, _USER_GOAL, _PRIOR_SEND_AS),
    ),
)

# --- Write tools (27) ---

GOOGLE_GMAIL_SEND_MESSAGE_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="recipient_matches_intent",
        text="Do to/cc/bcc match who the user asked to email (no wrong address, no missing recipient)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SEND_CALL, _USER_GOAL, _PRIOR_GMAIL_READ),
    ),
    VerificationQuestion(
        id="subject_body_match_intent",
        text="Do subject and body match what the user requested (language, tone, facts)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SEND_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="send_as_appropriate",
        text="Is from_send_as the correct alias for this email?",
        severity=SEVERITY_WARN,
        evidence=(_SEND_CALL, _USER_GOAL, _PRIOR_SEND_AS),
    ),
    VerificationQuestion(
        id="sent_message_verified",
        text="Does the sent message exist in Gmail with expected headers (live verify)?",
        severity=SEVERITY_WARN,
        evidence=(_SEND_CALL, _LIVE_SENT_MESSAGE, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_REPLY_TO_MESSAGE_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_message_thread",
        text="Does message_id refer to the email the user wanted to reply to (right sender/subject)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_REPLY_CALL, _USER_GOAL, _PRIOR_MESSAGE, _LIVE_SOURCE_MESSAGE),
    ),
    VerificationQuestion(
        id="reply_scope_correct",
        text="Is reply_all correct for reply vs reply-all as the user asked?",
        severity=SEVERITY_CRITICAL,
        evidence=(_REPLY_CALL, _USER_GOAL, _PRIOR_MESSAGE),
    ),
    VerificationQuestion(
        id="reply_body_match_intent",
        text="Does the reply body say what the user intended?",
        severity=SEVERITY_CRITICAL,
        evidence=(_REPLY_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="sent_in_same_thread",
        text="Was the reply sent and visible in the expected thread (live sent verify)?",
        severity=SEVERITY_WARN,
        evidence=(_REPLY_CALL, _LIVE_SENT_MESSAGE, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_FORWARD_MESSAGE_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_message_targeted",
        text="Does message_id refer to the email the user wanted to forward?",
        severity=SEVERITY_CRITICAL,
        evidence=(_FORWARD_CALL, _USER_GOAL, _PRIOR_MESSAGE, _LIVE_SOURCE_MESSAGE),
    ),
    VerificationQuestion(
        id="recipient_matches_intent",
        text="Do forward recipients match who the user asked to send this to?",
        severity=SEVERITY_CRITICAL,
        evidence=(_FORWARD_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="forward_note_match_intent",
        text="Does any prepended note match the user's request?",
        severity=SEVERITY_WARN,
        evidence=(_FORWARD_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="sent_message_verified",
        text="Was the forward sent successfully (live sent verify)?",
        severity=SEVERITY_WARN,
        evidence=(_FORWARD_CALL, _LIVE_SENT_MESSAGE, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_MODIFY_MESSAGE_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_message_targeted",
        text="Does message_id match the email the user wanted to label or modify?",
        severity=SEVERITY_CRITICAL,
        evidence=(_MODIFY_MESSAGE_CALL, _USER_GOAL, _PRIOR_MESSAGE),
    ),
    VerificationQuestion(
        id="labels_match_intent",
        text="Do add_label_ids/remove_label_ids implement what the user asked (star, unread, custom label)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_MODIFY_MESSAGE_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
    VerificationQuestion(
        id="not_wrong_label_toggle",
        text="Are labels being added and removed in the right direction (not inverted)?",
        severity=SEVERITY_WARN,
        evidence=(_MODIFY_MESSAGE_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_MODIFY_THREAD_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_thread_targeted",
        text="Does thread_id match the conversation the user wanted to label?",
        severity=SEVERITY_CRITICAL,
        evidence=(_MODIFY_THREAD_CALL, _USER_GOAL, _PRIOR_THREAD),
    ),
    VerificationQuestion(
        id="thread_level_intended",
        text="Did the user want the whole thread labeled (not a single message)?",
        severity=SEVERITY_WARN,
        evidence=(_MODIFY_THREAD_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="labels_match_intent",
        text="Do label changes match the user's request?",
        severity=SEVERITY_CRITICAL,
        evidence=(_MODIFY_THREAD_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
)

GOOGLE_GMAIL_MARK_READ_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_target",
        text="Does message_id or thread_id match what the user asked to mark as read?",
        severity=SEVERITY_CRITICAL,
        evidence=(_MSG_OR_THREAD_CALL, _USER_GOAL, _PRIOR_MESSAGE, _PRIOR_THREAD),
    ),
    VerificationQuestion(
        id="read_not_unread_intent",
        text="Did the user want to mark read (not unread/archive/delete)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_MSG_OR_THREAD_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="message_vs_thread_choice",
        text="If both ids possible, was the right scope chosen (one message vs whole thread)?",
        severity=SEVERITY_WARN,
        evidence=(_MSG_OR_THREAD_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_MARK_UNREAD_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_target",
        text="Does message_id or thread_id match what the user asked to mark unread?",
        severity=SEVERITY_CRITICAL,
        evidence=(_MSG_OR_THREAD_CALL, _USER_GOAL, _PRIOR_MESSAGE, _PRIOR_THREAD),
    ),
    VerificationQuestion(
        id="unread_intent",
        text="Did the user want unread flag (not archive/trash/read)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_MSG_OR_THREAD_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_ARCHIVE_MESSAGE_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_target",
        text="Does message_id or thread_id match the mail the user asked to archive?",
        severity=SEVERITY_CRITICAL,
        evidence=(_MSG_OR_THREAD_CALL, _USER_GOAL, _PRIOR_MESSAGE, _PRIOR_THREAD),
    ),
    VerificationQuestion(
        id="archive_not_delete",
        text="Did the user want archive (remove from inbox), not trash or permanent delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_MSG_OR_THREAD_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_TRASH_MESSAGE_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_message_targeted",
        text="Does message_id match the email the user asked to trash?",
        severity=SEVERITY_CRITICAL,
        evidence=(_TRASH_MSG_CALL, _USER_GOAL, _PRIOR_MESSAGE),
    ),
    VerificationQuestion(
        id="trash_not_permanent_delete",
        text="Did the user want trash (recoverable), not permanent delete_message?",
        severity=SEVERITY_CRITICAL,
        evidence=(_TRASH_MSG_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_UNTRASH_MESSAGE_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_message_targeted",
        text="Does message_id match the trashed email the user asked to restore?",
        severity=SEVERITY_CRITICAL,
        evidence=(_TRASH_MSG_CALL, _USER_GOAL, _PRIOR_MESSAGE),
    ),
    VerificationQuestion(
        id="restore_intent",
        text="Did the user ask to restore from trash?",
        severity=SEVERITY_CRITICAL,
        evidence=(_TRASH_MSG_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_TRASH_THREAD_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_thread_targeted",
        text="Does thread_id match the conversation the user asked to trash?",
        severity=SEVERITY_CRITICAL,
        evidence=(_TRASH_THREAD_CALL, _USER_GOAL, _PRIOR_THREAD),
    ),
    VerificationQuestion(
        id="thread_trash_intended",
        text="Did the user want the whole thread trashed (not one message)?",
        severity=SEVERITY_WARN,
        evidence=(_TRASH_THREAD_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_UNTRASH_THREAD_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_thread_targeted",
        text="Does thread_id match the trashed conversation to restore?",
        severity=SEVERITY_CRITICAL,
        evidence=(_TRASH_THREAD_CALL, _USER_GOAL, _PRIOR_THREAD),
    ),
    VerificationQuestion(
        id="restore_intent",
        text="Did the user ask to restore the thread from trash?",
        severity=SEVERITY_CRITICAL,
        evidence=(_TRASH_THREAD_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_CREATE_LABEL_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="name_matches_intent",
        text="Does the label name match what the user wanted to create?",
        severity=SEVERITY_CRITICAL,
        evidence=(_CREATE_LABEL_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
    VerificationQuestion(
        id="not_duplicate_label",
        text="Did the user want a new label (not reuse an existing one)?",
        severity=SEVERITY_WARN,
        evidence=(_CREATE_LABEL_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
)

GOOGLE_GMAIL_UPDATE_LABEL_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_label_targeted",
        text="Does label_id match the user label being renamed or reconfigured?",
        severity=SEVERITY_CRITICAL,
        evidence=(_UPDATE_LABEL_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
    VerificationQuestion(
        id="not_system_label",
        text="Is this a user label (system labels like INBOX cannot be renamed)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_UPDATE_LABEL_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
    VerificationQuestion(
        id="fields_match_request",
        text="Are only the requested name/visibility fields being changed?",
        severity=SEVERITY_WARN,
        evidence=(_UPDATE_LABEL_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_DELETE_LABEL_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_label_targeted",
        text="Does label_id match the custom label the user asked to delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_LABEL_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
    VerificationQuestion(
        id="not_system_label",
        text="Is this definitely not a system label (INBOX, UNREAD, etc.)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_LABEL_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
    VerificationQuestion(
        id="user_intent_delete_label",
        text="Did the user intend to delete the label (not just remove it from one message)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_LABEL_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_BATCH_MODIFY_MESSAGES_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="message_set_matches_intent",
        text="Do message_ids cover exactly the emails the user asked to batch-label?",
        severity=SEVERITY_CRITICAL,
        evidence=(_BATCH_MODIFY_CALL, _USER_GOAL, _PRIOR_GMAIL_READ),
    ),
    VerificationQuestion(
        id="labels_match_intent",
        text="Do add/remove label changes match the batch action the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_BATCH_MODIFY_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
    VerificationQuestion(
        id="batch_size_reasonable",
        text="Is the batch size appropriate (not thousands by mistake)?",
        severity=SEVERITY_WARN,
        evidence=(_BATCH_MODIFY_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_CREATE_DRAFT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="recipient_matches_intent",
        text="Do draft recipients match who the user asked to write to?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DRAFT_COMPOSE_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="subject_body_match_intent",
        text="Do subject and body match what the user wanted in the draft?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DRAFT_COMPOSE_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="draft_not_send_yet",
        text="Did the user want a draft saved (not send immediately)?",
        severity=SEVERITY_WARN,
        evidence=(_DRAFT_COMPOSE_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_UPDATE_DRAFT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_draft_targeted",
        text="Does draft_id match the draft the user asked to edit?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DRAFT_COMPOSE_CALL, _USER_GOAL, _PRIOR_DRAFT),
    ),
    VerificationQuestion(
        id="fields_match_request",
        text="Are only the draft fields the user asked to change being updated?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DRAFT_COMPOSE_CALL, _USER_GOAL, _PRIOR_DRAFT),
    ),
)

GOOGLE_GMAIL_DELETE_DRAFT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_draft_targeted",
        text="Does draft_id match the draft the user asked to discard?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_DRAFT_CALL, _USER_GOAL, _PRIOR_DRAFT),
    ),
    VerificationQuestion(
        id="user_intent_delete_draft",
        text="Did the user want to delete the draft (not send it)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_DRAFT_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_SEND_DRAFT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_draft_targeted",
        text="Does draft_id match the draft the user asked to send?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SEND_DRAFT_CALL, _USER_GOAL, _PRIOR_DRAFT),
    ),
    VerificationQuestion(
        id="user_intent_to_send",
        text="Did the user ask to send (not edit or delete) this draft?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SEND_DRAFT_CALL, _USER_GOAL, _PRIOR_DRAFT),
    ),
    VerificationQuestion(
        id="draft_content_reviewed",
        text="Was draft content (recipients, body) reviewed before sending?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SEND_DRAFT_CALL, _PRIOR_DRAFT, _USER_GOAL),
    ),
    VerificationQuestion(
        id="sent_message_verified",
        text="Was the draft sent successfully (live sent verify)?",
        severity=SEVERITY_WARN,
        evidence=(_SEND_DRAFT_CALL, _LIVE_SENT_MESSAGE, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_DELETE_MESSAGE_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Was confirm=true set for this irreversible permanent delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_MESSAGE_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="correct_message_targeted",
        text="Does message_id match the email the user asked to permanently erase?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_MESSAGE_CALL, _USER_GOAL, _PRIOR_MESSAGE),
    ),
    VerificationQuestion(
        id="permanent_not_trash",
        text="Did the user intend permanent delete (not trash/archive)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_MESSAGE_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_BATCH_DELETE_MESSAGES_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Was confirm=true set for batch permanent delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_BATCH_DELETE_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="message_set_matches_intent",
        text="Do message_ids match exactly the emails the user asked to permanently delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_BATCH_DELETE_CALL, _USER_GOAL, _PRIOR_GMAIL_READ),
    ),
    VerificationQuestion(
        id="permanent_not_trash",
        text="Did the user intend permanent erase (not move to trash)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_BATCH_DELETE_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_CREATE_FILTER_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="criteria_matches_intent",
        text="Do filter criteria match what the user described (from, subject, query)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_CREATE_FILTER_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="action_matches_intent",
        text="Does the filter action do what the user asked (label, archive, forward)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_CREATE_FILTER_CALL, _USER_GOAL, _PRIOR_LABELS),
    ),
    VerificationQuestion(
        id="not_overly_broad",
        text="Is the filter narrow enough not to catch unrelated mail?",
        severity=SEVERITY_WARN,
        evidence=(_CREATE_FILTER_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_DELETE_FILTER_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_filter_targeted",
        text="Does filter_id match the rule the user asked to remove?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_FILTER_CALL, _USER_GOAL, _PRIOR_FILTERS),
    ),
    VerificationQuestion(
        id="user_intent_delete_filter",
        text="Did the user intend to delete the filter (not edit it)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_FILTER_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_UPDATE_VACATION_SETTINGS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="auto_reply_matches_intent",
        text="Do enable_auto_reply, subject, and body match what the user wanted for out-of-office?",
        severity=SEVERITY_CRITICAL,
        evidence=(_UPDATE_VACATION_CALL, _USER_GOAL, _PRIOR_VACATION),
    ),
    VerificationQuestion(
        id="dates_if_set",
        text="If start/end times set, do they match the vacation period the user described?",
        severity=SEVERITY_WARN,
        evidence=(_UPDATE_VACATION_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="restrictions_appropriate",
        text="Are restrict_to_contacts/domain appropriate for who should get auto-replies?",
        severity=SEVERITY_WARN,
        evidence=(_UPDATE_VACATION_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_PATCH_SEND_AS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="alias_matches_intent",
        text="Does send_as_email match the alias the user wanted to configure?",
        severity=SEVERITY_CRITICAL,
        evidence=(_PATCH_SEND_AS_CALL, _USER_GOAL, _PRIOR_SEND_AS),
    ),
    VerificationQuestion(
        id="fields_match_request",
        text="Are display name, signature, reply-to changes what the user asked for?",
        severity=SEVERITY_CRITICAL,
        evidence=(_PATCH_SEND_AS_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="default_alias_intentional",
        text="If is_default changed, did the user intend to switch the default send-as?",
        severity=SEVERITY_WARN,
        evidence=(_PATCH_SEND_AS_CALL, _USER_GOAL),
    ),
)

GOOGLE_GMAIL_IMPORT_MESSAGE_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="import_not_send",
        text="Was import appropriate (mailbox migration) rather than send_message?",
        severity=SEVERITY_CRITICAL,
        evidence=(_IMPORT_MESSAGE_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="content_matches_source",
        text="Do headers/body match the message the user wanted to import?",
        severity=SEVERITY_CRITICAL,
        evidence=(_IMPORT_MESSAGE_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="thread_attach_if_set",
        text="If thread_id set, is attaching to that thread correct?",
        severity=SEVERITY_WARN,
        evidence=(_IMPORT_MESSAGE_CALL, _USER_GOAL, _PRIOR_THREAD),
    ),
)

# --- Registry ---

GMAIL_CHECKER_ALL_TOOL_NAMES: tuple[str, ...] = (
    "google.gmail.get_profile",
    "google.gmail.list_labels",
    "google.gmail.get_label",
    "google.gmail.search_messages",
    "google.gmail.list_messages",
    "google.gmail.get_message",
    "google.gmail.list_inbox",
    "google.gmail.list_unread",
    "google.gmail.list_threads",
    "google.gmail.get_thread",
    "google.gmail.get_attachment",
    "google.gmail.list_drafts",
    "google.gmail.get_draft",
    "google.gmail.list_filters",
    "google.gmail.get_filter",
    "google.gmail.get_vacation_settings",
    "google.gmail.list_send_as",
    "google.gmail.get_send_as",
    "google.gmail.modify_message",
    "google.gmail.modify_thread",
    "google.gmail.mark_read",
    "google.gmail.mark_unread",
    "google.gmail.archive_message",
    "google.gmail.trash_message",
    "google.gmail.untrash_message",
    "google.gmail.trash_thread",
    "google.gmail.untrash_thread",
    "google.gmail.send_message",
    "google.gmail.reply_to_message",
    "google.gmail.forward_message",
    "google.gmail.create_label",
    "google.gmail.update_label",
    "google.gmail.delete_label",
    "google.gmail.batch_modify_messages",
    "google.gmail.create_draft",
    "google.gmail.update_draft",
    "google.gmail.delete_draft",
    "google.gmail.send_draft",
    "google.gmail.delete_message",
    "google.gmail.batch_delete_messages",
    "google.gmail.create_filter",
    "google.gmail.delete_filter",
    "google.gmail.update_vacation_settings",
    "google.gmail.patch_send_as",
    "google.gmail.import_message",
)

GMAIL_CHECKER_READ_TOOL_NAMES: tuple[str, ...] = (
    "google.gmail.get_profile",
    "google.gmail.list_labels",
    "google.gmail.get_label",
    "google.gmail.search_messages",
    "google.gmail.list_messages",
    "google.gmail.get_message",
    "google.gmail.list_inbox",
    "google.gmail.list_unread",
    "google.gmail.list_threads",
    "google.gmail.get_thread",
    "google.gmail.get_attachment",
    "google.gmail.list_drafts",
    "google.gmail.get_draft",
    "google.gmail.list_filters",
    "google.gmail.get_filter",
    "google.gmail.get_vacation_settings",
    "google.gmail.list_send_as",
    "google.gmail.get_send_as",
)

GMAIL_CHECKER_WRITE_TOOL_NAMES: tuple[str, ...] = tuple(
    name for name in GMAIL_CHECKER_ALL_TOOL_NAMES if name not in GMAIL_CHECKER_READ_TOOL_NAMES
)

GMAIL_CHECKER_QUESTIONS_BY_TOOL: dict[str, tuple[VerificationQuestion, ...]] = {
    "google.gmail.get_profile": GOOGLE_GMAIL_GET_PROFILE_QUESTIONS,
    "google.gmail.list_labels": GOOGLE_GMAIL_LIST_LABELS_QUESTIONS,
    "google.gmail.get_label": GOOGLE_GMAIL_GET_LABEL_QUESTIONS,
    "google.gmail.search_messages": GOOGLE_GMAIL_SEARCH_MESSAGES_QUESTIONS,
    "google.gmail.list_messages": GOOGLE_GMAIL_LIST_MESSAGES_QUESTIONS,
    "google.gmail.get_message": GOOGLE_GMAIL_GET_MESSAGE_QUESTIONS,
    "google.gmail.list_inbox": GOOGLE_GMAIL_LIST_INBOX_QUESTIONS,
    "google.gmail.list_unread": GOOGLE_GMAIL_LIST_UNREAD_QUESTIONS,
    "google.gmail.list_threads": GOOGLE_GMAIL_LIST_THREADS_QUESTIONS,
    "google.gmail.get_thread": GOOGLE_GMAIL_GET_THREAD_QUESTIONS,
    "google.gmail.get_attachment": GOOGLE_GMAIL_GET_ATTACHMENT_QUESTIONS,
    "google.gmail.list_drafts": GOOGLE_GMAIL_LIST_DRAFTS_QUESTIONS,
    "google.gmail.get_draft": GOOGLE_GMAIL_GET_DRAFT_QUESTIONS,
    "google.gmail.list_filters": GOOGLE_GMAIL_LIST_FILTERS_QUESTIONS,
    "google.gmail.get_filter": GOOGLE_GMAIL_GET_FILTER_QUESTIONS,
    "google.gmail.get_vacation_settings": GOOGLE_GMAIL_GET_VACATION_SETTINGS_QUESTIONS,
    "google.gmail.list_send_as": GOOGLE_GMAIL_LIST_SEND_AS_QUESTIONS,
    "google.gmail.get_send_as": GOOGLE_GMAIL_GET_SEND_AS_QUESTIONS,
    "google.gmail.modify_message": GOOGLE_GMAIL_MODIFY_MESSAGE_QUESTIONS,
    "google.gmail.modify_thread": GOOGLE_GMAIL_MODIFY_THREAD_QUESTIONS,
    "google.gmail.mark_read": GOOGLE_GMAIL_MARK_READ_QUESTIONS,
    "google.gmail.mark_unread": GOOGLE_GMAIL_MARK_UNREAD_QUESTIONS,
    "google.gmail.archive_message": GOOGLE_GMAIL_ARCHIVE_MESSAGE_QUESTIONS,
    "google.gmail.trash_message": GOOGLE_GMAIL_TRASH_MESSAGE_QUESTIONS,
    "google.gmail.untrash_message": GOOGLE_GMAIL_UNTRASH_MESSAGE_QUESTIONS,
    "google.gmail.trash_thread": GOOGLE_GMAIL_TRASH_THREAD_QUESTIONS,
    "google.gmail.untrash_thread": GOOGLE_GMAIL_UNTRASH_THREAD_QUESTIONS,
    "google.gmail.send_message": GOOGLE_GMAIL_SEND_MESSAGE_QUESTIONS,
    "google.gmail.reply_to_message": GOOGLE_GMAIL_REPLY_TO_MESSAGE_QUESTIONS,
    "google.gmail.forward_message": GOOGLE_GMAIL_FORWARD_MESSAGE_QUESTIONS,
    "google.gmail.create_label": GOOGLE_GMAIL_CREATE_LABEL_QUESTIONS,
    "google.gmail.update_label": GOOGLE_GMAIL_UPDATE_LABEL_QUESTIONS,
    "google.gmail.delete_label": GOOGLE_GMAIL_DELETE_LABEL_QUESTIONS,
    "google.gmail.batch_modify_messages": GOOGLE_GMAIL_BATCH_MODIFY_MESSAGES_QUESTIONS,
    "google.gmail.create_draft": GOOGLE_GMAIL_CREATE_DRAFT_QUESTIONS,
    "google.gmail.update_draft": GOOGLE_GMAIL_UPDATE_DRAFT_QUESTIONS,
    "google.gmail.delete_draft": GOOGLE_GMAIL_DELETE_DRAFT_QUESTIONS,
    "google.gmail.send_draft": GOOGLE_GMAIL_SEND_DRAFT_QUESTIONS,
    "google.gmail.delete_message": GOOGLE_GMAIL_DELETE_MESSAGE_QUESTIONS,
    "google.gmail.batch_delete_messages": GOOGLE_GMAIL_BATCH_DELETE_MESSAGES_QUESTIONS,
    "google.gmail.create_filter": GOOGLE_GMAIL_CREATE_FILTER_QUESTIONS,
    "google.gmail.delete_filter": GOOGLE_GMAIL_DELETE_FILTER_QUESTIONS,
    "google.gmail.update_vacation_settings": GOOGLE_GMAIL_UPDATE_VACATION_SETTINGS_QUESTIONS,
    "google.gmail.patch_send_as": GOOGLE_GMAIL_PATCH_SEND_AS_QUESTIONS,
    "google.gmail.import_message": GOOGLE_GMAIL_IMPORT_MESSAGE_QUESTIONS,
}

GMAIL_LIVE_SENT_QUESTION_IDS = frozenset(
    {
        "sent_message_verified",
        "sent_in_same_thread",
    }
)
