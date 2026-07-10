from __future__ import annotations

from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_LIVE_FETCH,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_RUNTIME,
    EVIDENCE_USER_GOAL,
    FETCH_CALENDAR_EVENT_EXISTS,
    FETCH_CALENDAR_SLOT_CONFLICTS,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    EvidenceRef,
    VerificationQuestion,
)

# --- Shared evidence ---

_LIVE_SLOT_CONFLICTS = EvidenceRef(
    kind=EVIDENCE_LIVE_FETCH,
    fetch=FETCH_CALENDAR_SLOT_CONFLICTS,
    label="slot_conflicts_live",
)

_LIVE_EVENT_STATE = EvidenceRef(
    kind=EVIDENCE_LIVE_FETCH,
    fetch=FETCH_CALENDAR_EVENT_EXISTS,
    label="event_state_live",
)

_USER_GOAL = EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal")
_RUNTIME = EvidenceRef(kind=EVIDENCE_RUNTIME, optional=True, label="runtime_context")

_PRIOR_EVENT_IN_TRACE = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "google.calendar.list_events",
        "google.calendar.search_events",
        "google.calendar.list_upcoming",
        "google.calendar.list_today",
        "google.calendar.list_instances",
        "google.calendar.get_event",
        "google.calendar.create_event",
        "google.calendar.create_meet_event",
        "google.calendar.quick_add_event",
    ),
    match=(("event_id", "$call.event_id"),),
    optional=True,
    label="prior_event_in_trace",
)

_PRIOR_SCHEDULING_READ = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("google.calendar.freebusy", "google.calendar.find_free_slots"),
    optional=True,
    max_age_steps=6,
    label="prior_scheduling_read",
)

_PRIOR_LIST_CALENDARS = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("google.calendar.list_calendars", "google.calendar.get_calendar"),
    optional=True,
    max_age_steps=6,
    label="prior_calendars_context",
)

_PRIOR_LIST_COLORS = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("google.calendar.list_colors",),
    optional=True,
    max_age_steps=8,
    label="prior_color_palette",
)

# --- Call evidence by tool shape ---

_GET_CALENDAR_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("calendar_id",), label="get_calendar_call"
)
_LIST_EVENTS_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("calendar_id", "time_min", "time_max", "query", "max_results", "order_by"),
    label="list_events_call",
)
_GET_EVENT_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("calendar_id", "event_id", "event"), label="get_event_call"
)
_SEARCH_EVENTS_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("calendar_id", "query", "time_min", "time_max", "days_ahead", "max_results"),
    label="search_events_call",
)
_LIST_UPCOMING_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("calendar_id", "count", "days_ahead", "time_zone"),
    label="list_upcoming_call",
)
_LIST_TODAY_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("calendar_id", "time_zone", "max_results"),
    label="list_today_call",
)
_LIST_INSTANCES_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("calendar_id", "event_id", "time_min", "time_max", "max_results"),
    label="list_instances_call",
)
_LIST_CALENDARS_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("show_hidden", "show_deleted"),
    label="list_calendars_call",
)
_SCHEDULING_READ_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("time_min", "time_max", "calendar_ids", "duration_minutes", "working_hours_start", "working_hours_end"),
    label="scheduling_read_call",
)
_CREATE_EVENT_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("calendar_id", "summary", "start", "end", "time_zone", "description", "location", "attendees", "color_id"),
    label="create_event_call",
)
_QUICK_ADD_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("calendar_id", "text", "event"), label="quick_add_call"
)
_PATCH_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("calendar_id", "event_id", "summary", "start", "end", "time_zone", "description", "location", "color_id"),
    label="patch_event_call",
)
_UPDATE_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("calendar_id", "event_id", "summary", "start", "end", "time_zone", "description", "location"),
    label="update_event_call",
)
_DELETE_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("calendar_id", "event_id"), label="delete_event_call"
)
_MOVE_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("calendar_id", "event_id", "destination_calendar_id"),
    label="move_event_call",
)
_CREATE_CALENDAR_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("summary", "description", "time_zone"),
    label="create_calendar_call",
)
_UPDATE_CALENDAR_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("calendar_id", "summary", "description", "time_zone"),
    label="update_calendar_call",
)
_DELETE_CALENDAR_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("calendar_id",), label="delete_calendar_call"
)
_CLEAR_CALENDAR_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("calendar_id", "confirm"), label="clear_calendar_call"
)
_IMPORT_EVENT_CALL = EvidenceRef(
    kind=EVIDENCE_CALL,
    fields=("calendar_id", "summary", "start", "end", "time_zone", "description", "location"),
    label="import_event_call",
)
_SET_CALENDAR_COLOR_CALL = EvidenceRef(
    kind=EVIDENCE_CALL, fields=("calendar_id", "color_id"), label="set_calendar_color_call"
)

# --- Read tools (11) ---

GOOGLE_CALENDAR_GET_CALENDAR_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="calendar_id_matches_intent",
        text="Does calendar_id refer to the calendar the user asked about (not a random secondary calendar)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_GET_CALENDAR_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
    VerificationQuestion(
        id="metadata_needed_for_goal",
        text="Was calendar metadata (timezone, title) actually needed to answer the user's request?",
        severity=SEVERITY_WARN,
        evidence=(_GET_CALENDAR_CALL, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_LIST_EVENTS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="range_covers_intent",
        text="Do time_min and time_max cover the date range the user asked about (not a too-narrow window)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIST_EVENTS_CALL, _USER_GOAL, _RUNTIME),
    ),
    VerificationQuestion(
        id="calendar_correct",
        text="Is calendar_id the calendar the user cares about for this query?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_EVENTS_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
    VerificationQuestion(
        id="text_query_if_used",
        text="If query is set, does it match the event or keyword the user wanted to find?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_EVENTS_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="result_limit_sufficient",
        text="Is max_results high enough that important events are unlikely to be truncated?",
        severity=SEVERITY_INFO,
        evidence=(_LIST_EVENTS_CALL, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_GET_EVENT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="event_id_from_user_context",
        text="Does event_id match the specific event the user referred to (from prior list/search or their message)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_GET_EVENT_CALL, _USER_GOAL, _PRIOR_EVENT_IN_TRACE),
    ),
    VerificationQuestion(
        id="calendar_id_consistent",
        text="Is calendar_id consistent with where that event was found earlier in the run?",
        severity=SEVERITY_WARN,
        evidence=(_GET_EVENT_CALL, _PRIOR_EVENT_IN_TRACE),
    ),
    VerificationQuestion(
        id="event_found_in_result",
        text="Did the call return the expected event details (not empty/error for a valid id)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_GET_EVENT_CALL, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_SEARCH_EVENTS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="query_matches_intent",
        text="Does the search query capture the meeting title, person, or topic the user mentioned?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SEARCH_EVENTS_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="time_window_appropriate",
        text="Do time_min/time_max or days_ahead cover when the user thinks the event occurs?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SEARCH_EVENTS_CALL, _USER_GOAL, _RUNTIME),
    ),
    VerificationQuestion(
        id="calendar_correct",
        text="Is the search scoped to the right calendar?",
        severity=SEVERITY_WARN,
        evidence=(_SEARCH_EVENTS_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
)

GOOGLE_CALENDAR_LIST_UPCOMING_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="horizon_matches_intent",
        text="Are count and days_ahead appropriate for what the user meant by 'upcoming' or 'next'?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIST_UPCOMING_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="timezone_correct",
        text="If time_zone is set, does it match the user's locale or bot timezone?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_UPCOMING_CALL, _RUNTIME, _USER_GOAL),
    ),
    VerificationQuestion(
        id="calendar_correct",
        text="Is calendar_id the calendar the user expects their schedule from?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_UPCOMING_CALL, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_LIST_TODAY_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="today_in_user_timezone",
        text="Is 'today' interpreted using the correct timezone for the user (not UTC drift)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIST_TODAY_CALL, _RUNTIME, _USER_GOAL),
    ),
    VerificationQuestion(
        id="calendar_correct",
        text="Is calendar_id the calendar whose today-schedule the user asked for?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_TODAY_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="max_results_sufficient",
        text="Is max_results high enough for a busy day without silently dropping events?",
        severity=SEVERITY_INFO,
        evidence=(_LIST_TODAY_CALL, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_LIST_COLORS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="needed_for_color_change",
        text="Was list_colors called because a color_id is needed for an upcoming create/patch/set_calendar_color?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
    VerificationQuestion(
        id="not_redundant_repeat",
        text="If list_colors was already fetched this run, was a repeat call necessary?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL, _PRIOR_LIST_COLORS),
    ),
)

GOOGLE_CALENDAR_LIST_INSTANCES_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="recurring_master_correct",
        text="Does event_id refer to the recurring series the user asked about (master id, not a single instance id)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIST_INSTANCES_CALL, _USER_GOAL, _PRIOR_EVENT_IN_TRACE),
    ),
    VerificationQuestion(
        id="range_covers_intent",
        text="Do time_min/time_max cover the period for which the user wants occurrences listed?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIST_INSTANCES_CALL, _USER_GOAL, _RUNTIME),
    ),
    VerificationQuestion(
        id="calendar_correct",
        text="Is calendar_id where that recurring event lives?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_INSTANCES_CALL, _PRIOR_EVENT_IN_TRACE),
    ),
)

GOOGLE_CALENDAR_FREEBUSY_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="range_covers_intent",
        text="Does the query time range cover the day or window the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SCHEDULING_READ_CALL, _USER_GOAL, _RUNTIME),
    ),
    VerificationQuestion(
        id="calendars_included",
        text="Were all calendars that matter for scheduling (user + attendees) included?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SCHEDULING_READ_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
    VerificationQuestion(
        id="sufficient_before_write",
        text="If a create/patch follows, does this freebusy data cover the slot to be booked?",
        severity=SEVERITY_WARN,
        evidence=(_SCHEDULING_READ_CALL, _USER_GOAL, _PRIOR_SCHEDULING_READ),
    ),
)

GOOGLE_CALENDAR_FIND_FREE_SLOTS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="range_covers_intent",
        text="Does the search window cover when the user wants to meet?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SCHEDULING_READ_CALL, _USER_GOAL, _RUNTIME),
    ),
    VerificationQuestion(
        id="duration_matches_request",
        text="Is duration_minutes appropriate for the meeting length the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SCHEDULING_READ_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="calendars_included",
        text="Were the right calendars searched for mutual free time?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SCHEDULING_READ_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
    VerificationQuestion(
        id="working_hours_sane",
        text="Do working_hours_start/end reflect reasonable hours for the user's context?",
        severity=SEVERITY_WARN,
        evidence=(_SCHEDULING_READ_CALL, _RUNTIME, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_LIST_CALENDARS_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="needed_for_calendar_pick",
        text="Was listing calendars necessary to pick the right calendar_id for a follow-up action?",
        severity=SEVERITY_WARN,
        evidence=(_LIST_CALENDARS_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="hidden_deleted_flags_appropriate",
        text="If show_hidden or show_deleted is true, did the user ask for hidden/trashed calendars?",
        severity=SEVERITY_INFO,
        evidence=(_LIST_CALENDARS_CALL, _USER_GOAL),
    ),
)

# --- Write tools (12) ---

GOOGLE_CALENDAR_CREATE_EVENT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="slot_not_busy",
        text=(
            "Was the slot actually free — no overlapping events at this time "
            "(excluding the event just created)?"
        ),
        severity=SEVERITY_CRITICAL,
        evidence=(_LIVE_SLOT_CONFLICTS, _CREATE_EVENT_CALL, _USER_GOAL, _PRIOR_SCHEDULING_READ),
    ),
    VerificationQuestion(
        id="time_matches_user",
        text="Do start and end match the date and time the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_CREATE_EVENT_CALL, _USER_GOAL, _RUNTIME),
    ),
    VerificationQuestion(
        id="timezone_correct",
        text="Is time_zone correct for the user or bot timezone (not accidental UTC shift)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_CREATE_EVENT_CALL, _RUNTIME, _USER_GOAL),
    ),
    VerificationQuestion(
        id="calendar_correct",
        text="Was the intended calendar selected (work vs personal vs primary)?",
        severity=SEVERITY_WARN,
        evidence=(_CREATE_EVENT_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
    VerificationQuestion(
        id="summary_and_details_match",
        text="Do summary, description, location, and attendees match the user's request?",
        severity=SEVERITY_WARN,
        evidence=(_CREATE_EVENT_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="duration_sane",
        text="Is duration reasonable (not zero-length or multi-day by mistake)?",
        severity=SEVERITY_WARN,
        evidence=(_CREATE_EVENT_CALL,),
    ),
)

GOOGLE_CALENDAR_CREATE_MEET_EVENT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    *GOOGLE_CALENDAR_CREATE_EVENT_QUESTIONS,
    VerificationQuestion(
        id="meet_link_requested",
        text="Did the user want a video call / Google Meet link (not just an in-person calendar block)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_CREATE_EVENT_CALL, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_QUICK_ADD_EVENT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="slot_not_busy",
        text="Was the slot free besides the event created from quick-add?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIVE_SLOT_CONFLICTS, _QUICK_ADD_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="nl_parsed_correctly",
        text="Does the created event match the natural-language text (title, time, date)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_QUICK_ADD_CALL, _USER_GOAL, _RUNTIME),
    ),
    VerificationQuestion(
        id="calendar_correct",
        text="Was quick-add applied to the calendar the user intended?",
        severity=SEVERITY_WARN,
        evidence=(_QUICK_ADD_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
)

GOOGLE_CALENDAR_PATCH_EVENT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_event_targeted",
        text="Does event_id match the event the user wanted to change (not another meeting)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_PATCH_CALL, _USER_GOAL, _PRIOR_EVENT_IN_TRACE),
    ),
    VerificationQuestion(
        id="intended_fields_only",
        text="Are only the fields the user asked to change being updated (no unrelated edits)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_PATCH_CALL, _USER_GOAL, _PRIOR_EVENT_IN_TRACE),
    ),
    VerificationQuestion(
        id="slot_not_busy",
        text="If start/end changed, is the new slot free of other overlapping events?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIVE_SLOT_CONFLICTS, _PATCH_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="mutation_reflected",
        text="After the patch, does live event state reflect the requested changes?",
        severity=SEVERITY_WARN,
        evidence=(_PATCH_CALL, _LIVE_EVENT_STATE, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_UPDATE_EVENT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_event_targeted",
        text="Does event_id match the event the user wanted to fully replace?",
        severity=SEVERITY_CRITICAL,
        evidence=(_UPDATE_CALL, _USER_GOAL, _PRIOR_EVENT_IN_TRACE),
    ),
    VerificationQuestion(
        id="time_matches_user",
        text="Do the replacement start/end match what the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_UPDATE_CALL, _USER_GOAL, _RUNTIME),
    ),
    VerificationQuestion(
        id="slot_not_busy",
        text="Is the new time slot free of conflicting events (excluding this event)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIVE_SLOT_CONFLICTS, _UPDATE_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="full_replace_intended",
        text="Did the user want a full replace (update_event) rather than a small patch?",
        severity=SEVERITY_WARN,
        evidence=(_UPDATE_CALL, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_DELETE_EVENT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_event_targeted",
        text="Does event_id match the event the user asked to cancel or delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_CALL, _USER_GOAL, _PRIOR_EVENT_IN_TRACE),
    ),
    VerificationQuestion(
        id="user_intent_to_delete",
        text="Did the user ask to cancel/delete — not move, reschedule, or edit?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="not_recurring_master_by_mistake",
        text="If this is a recurring event, did the user intend to delete this instance/series?",
        severity=SEVERITY_WARN,
        evidence=(_DELETE_CALL, _USER_GOAL, _PRIOR_EVENT_IN_TRACE),
    ),
)

GOOGLE_CALENDAR_MOVE_EVENT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_event_targeted",
        text="Does event_id match the event the user wanted to move?",
        severity=SEVERITY_CRITICAL,
        evidence=(_MOVE_CALL, _USER_GOAL, _PRIOR_EVENT_IN_TRACE),
    ),
    VerificationQuestion(
        id="destination_calendar_valid",
        text="Is destination_calendar_id the calendar the user named (work/personal/project)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_MOVE_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
    VerificationQuestion(
        id="move_not_duplicate",
        text="Was move chosen instead of create+delete (user wanted transfer, not copy)?",
        severity=SEVERITY_WARN,
        evidence=(_MOVE_CALL, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_CREATE_CALENDAR_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="title_matches_intent",
        text="Does summary/title match what the user wanted to name the new calendar?",
        severity=SEVERITY_CRITICAL,
        evidence=(_CREATE_CALENDAR_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="timezone_correct",
        text="Is time_zone appropriate for how this calendar will be used?",
        severity=SEVERITY_WARN,
        evidence=(_CREATE_CALENDAR_CALL, _RUNTIME, _USER_GOAL),
    ),
    VerificationQuestion(
        id="not_duplicate_calendar",
        text="Did the user want a new calendar rather than reuse an existing one?",
        severity=SEVERITY_WARN,
        evidence=(_CREATE_CALENDAR_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
)

GOOGLE_CALENDAR_UPDATE_CALENDAR_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_calendar_targeted",
        text="Does calendar_id match the calendar the user asked to rename or reconfigure?",
        severity=SEVERITY_CRITICAL,
        evidence=(_UPDATE_CALENDAR_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
    VerificationQuestion(
        id="fields_match_request",
        text="Are only the metadata fields the user mentioned being updated?",
        severity=SEVERITY_CRITICAL,
        evidence=(_UPDATE_CALENDAR_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="not_primary_restricted",
        text="If changing primary calendar metadata, is it allowed and intended?",
        severity=SEVERITY_WARN,
        evidence=(_UPDATE_CALENDAR_CALL, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_DELETE_CALENDAR_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="correct_calendar_targeted",
        text="Does calendar_id match the secondary calendar the user asked to remove?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_CALENDAR_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
    VerificationQuestion(
        id="not_primary_calendar",
        text="Is this definitely not the primary calendar (which cannot be deleted)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_CALENDAR_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
    VerificationQuestion(
        id="user_intent_delete_calendar",
        text="Did the user intend to delete the whole calendar — not just clear events?",
        severity=SEVERITY_CRITICAL,
        evidence=(_DELETE_CALENDAR_CALL, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_CLEAR_CALENDAR_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Was confirm=true set for this destructive wipe of all events?",
        severity=SEVERITY_CRITICAL,
        evidence=(_CLEAR_CALENDAR_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="correct_calendar_targeted",
        text="Does calendar_id match the calendar the user asked to wipe?",
        severity=SEVERITY_CRITICAL,
        evidence=(_CLEAR_CALENDAR_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
    VerificationQuestion(
        id="user_intent_clear_not_delete",
        text="Did the user want to clear events but keep the calendar (not delete_calendar)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_CLEAR_CALENDAR_CALL, _USER_GOAL),
    ),
)

GOOGLE_CALENDAR_IMPORT_EVENT_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="slot_not_busy",
        text="Is the imported event's slot free of other overlapping events?",
        severity=SEVERITY_CRITICAL,
        evidence=(_LIVE_SLOT_CONFLICTS, _IMPORT_EVENT_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="import_not_invite",
        text="Was import appropriate (private copy/migration) rather than create_event with invites?",
        severity=SEVERITY_CRITICAL,
        evidence=(_IMPORT_EVENT_CALL, _USER_GOAL),
    ),
    VerificationQuestion(
        id="time_matches_source",
        text="Do start/end match the event times the user wanted to import?",
        severity=SEVERITY_CRITICAL,
        evidence=(_IMPORT_EVENT_CALL, _USER_GOAL, _RUNTIME),
    ),
)

GOOGLE_CALENDAR_SET_CALENDAR_COLOR_QUESTIONS: tuple[VerificationQuestion, ...] = (
    VerificationQuestion(
        id="color_id_valid",
        text="Is color_id from list_colors and valid for calendar (not event) colors?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SET_CALENDAR_COLOR_CALL, _PRIOR_LIST_COLORS, _USER_GOAL),
    ),
    VerificationQuestion(
        id="correct_calendar_targeted",
        text="Does calendar_id match the calendar whose color the user wanted to change?",
        severity=SEVERITY_CRITICAL,
        evidence=(_SET_CALENDAR_COLOR_CALL, _USER_GOAL, _PRIOR_LIST_CALENDARS),
    ),
    VerificationQuestion(
        id="color_matches_user_choice",
        text="Does the chosen color match the color the user described (green, red, etc.)?",
        severity=SEVERITY_WARN,
        evidence=(_SET_CALENDAR_COLOR_CALL, _PRIOR_LIST_COLORS, _USER_GOAL),
    ),
)

# --- Registry metadata ---

CALENDAR_CHECKER_ALL_TOOL_NAMES: tuple[str, ...] = (
    "google.calendar.get_calendar",
    "google.calendar.list_events",
    "google.calendar.get_event",
    "google.calendar.search_events",
    "google.calendar.list_upcoming",
    "google.calendar.list_today",
    "google.calendar.list_colors",
    "google.calendar.list_instances",
    "google.calendar.freebusy",
    "google.calendar.find_free_slots",
    "google.calendar.list_calendars",
    "google.calendar.create_event",
    "google.calendar.create_meet_event",
    "google.calendar.quick_add_event",
    "google.calendar.patch_event",
    "google.calendar.update_event",
    "google.calendar.delete_event",
    "google.calendar.move_event",
    "google.calendar.create_calendar",
    "google.calendar.update_calendar",
    "google.calendar.delete_calendar",
    "google.calendar.clear_calendar",
    "google.calendar.import_event",
    "google.calendar.set_calendar_color",
)

CALENDAR_CHECKER_READ_TOOL_NAMES: tuple[str, ...] = (
    "google.calendar.get_calendar",
    "google.calendar.list_events",
    "google.calendar.get_event",
    "google.calendar.search_events",
    "google.calendar.list_upcoming",
    "google.calendar.list_today",
    "google.calendar.list_colors",
    "google.calendar.list_instances",
    "google.calendar.freebusy",
    "google.calendar.find_free_slots",
    "google.calendar.list_calendars",
)

CALENDAR_CHECKER_WRITE_TOOL_NAMES: tuple[str, ...] = (
    "google.calendar.create_event",
    "google.calendar.create_meet_event",
    "google.calendar.quick_add_event",
    "google.calendar.patch_event",
    "google.calendar.update_event",
    "google.calendar.delete_event",
    "google.calendar.move_event",
    "google.calendar.create_calendar",
    "google.calendar.update_calendar",
    "google.calendar.delete_calendar",
    "google.calendar.clear_calendar",
    "google.calendar.import_event",
    "google.calendar.set_calendar_color",
)

CALENDAR_CHECKER_QUESTIONS_BY_TOOL: dict[str, tuple[VerificationQuestion, ...]] = {
    "google.calendar.get_calendar": GOOGLE_CALENDAR_GET_CALENDAR_QUESTIONS,
    "google.calendar.list_events": GOOGLE_CALENDAR_LIST_EVENTS_QUESTIONS,
    "google.calendar.get_event": GOOGLE_CALENDAR_GET_EVENT_QUESTIONS,
    "google.calendar.search_events": GOOGLE_CALENDAR_SEARCH_EVENTS_QUESTIONS,
    "google.calendar.list_upcoming": GOOGLE_CALENDAR_LIST_UPCOMING_QUESTIONS,
    "google.calendar.list_today": GOOGLE_CALENDAR_LIST_TODAY_QUESTIONS,
    "google.calendar.list_colors": GOOGLE_CALENDAR_LIST_COLORS_QUESTIONS,
    "google.calendar.list_instances": GOOGLE_CALENDAR_LIST_INSTANCES_QUESTIONS,
    "google.calendar.freebusy": GOOGLE_CALENDAR_FREEBUSY_QUESTIONS,
    "google.calendar.find_free_slots": GOOGLE_CALENDAR_FIND_FREE_SLOTS_QUESTIONS,
    "google.calendar.list_calendars": GOOGLE_CALENDAR_LIST_CALENDARS_QUESTIONS,
    "google.calendar.create_event": GOOGLE_CALENDAR_CREATE_EVENT_QUESTIONS,
    "google.calendar.create_meet_event": GOOGLE_CALENDAR_CREATE_MEET_EVENT_QUESTIONS,
    "google.calendar.quick_add_event": GOOGLE_CALENDAR_QUICK_ADD_EVENT_QUESTIONS,
    "google.calendar.patch_event": GOOGLE_CALENDAR_PATCH_EVENT_QUESTIONS,
    "google.calendar.update_event": GOOGLE_CALENDAR_UPDATE_EVENT_QUESTIONS,
    "google.calendar.delete_event": GOOGLE_CALENDAR_DELETE_EVENT_QUESTIONS,
    "google.calendar.move_event": GOOGLE_CALENDAR_MOVE_EVENT_QUESTIONS,
    "google.calendar.create_calendar": GOOGLE_CALENDAR_CREATE_CALENDAR_QUESTIONS,
    "google.calendar.update_calendar": GOOGLE_CALENDAR_UPDATE_CALENDAR_QUESTIONS,
    "google.calendar.delete_calendar": GOOGLE_CALENDAR_DELETE_CALENDAR_QUESTIONS,
    "google.calendar.clear_calendar": GOOGLE_CALENDAR_CLEAR_CALENDAR_QUESTIONS,
    "google.calendar.import_event": GOOGLE_CALENDAR_IMPORT_EVENT_QUESTIONS,
    "google.calendar.set_calendar_color": GOOGLE_CALENDAR_SET_CALENDAR_COLOR_QUESTIONS,
}

SLOT_CONFLICT_QUESTION_IDS = frozenset({"slot_not_busy"})

LIVE_EVENT_STATE_QUESTION_IDS = frozenset({"mutation_reflected"})
