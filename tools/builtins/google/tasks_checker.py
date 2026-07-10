from __future__ import annotations

from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_LIVE_FETCH,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_USER_GOAL,
    FETCH_TASKS_GET_TASK,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    EvidenceRef,
    VerificationQuestion,
)

_USER_GOAL = EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal")

_LIVE_TASK = EvidenceRef(
    kind=EVIDENCE_LIVE_FETCH,
    fetch=FETCH_TASKS_GET_TASK,
    label="tasks_get_task_live",
)

_PRIOR_TASK_READ = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "google.tasks.get_task",
        "google.tasks.list_tasks",
        "google.tasks.search_tasks",
        "google.tasks.list_default_tasks",
        "google.tasks.list_today",
        "google.tasks.list_overdue",
        "google.tasks.list_upcoming",
        "google.tasks.list_subtasks",
        "google.tasks.list_all_open_tasks",
    ),
    match=(("task_id", "$call.task_id"),),
    optional=True,
    max_age_steps=10,
    label="prior_task_read",
)

_PRIOR_TASKLIST = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("google.tasks.list_tasklists", "google.tasks.get_tasklist"),
    match=(("tasklist_id", "$call.tasklist_id"),),
    optional=True,
    max_age_steps=10,
    label="prior_tasklist",
)

_PRIOR_TASKS_CONTEXT = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_name_pattern="google.tasks.*",
    optional=True,
    max_age_steps=10,
    label="prior_tasks_context",
)


def _call(label: str, *fields: str) -> EvidenceRef:
    return EvidenceRef(kind=EVIDENCE_CALL, fields=fields, label=label)


# --- Task lists (read) ---

GOOGLE_TASKS_LIST_TASKLISTS_QUESTIONS = (
    VerificationQuestion(
        id="list_discovery_intent",
        text="Did the user need to discover or pick a task list before another action?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL, _PRIOR_TASKS_CONTEXT),
    ),
)

GOOGLE_TASKS_GET_TASKLIST_QUESTIONS = (
    VerificationQuestion(
        id="tasklist_id_correct",
        text="Does tasklist_id match the list the user asked about from list_tasklists?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_tasklist_call", "tasklist_id"), _USER_GOAL, _PRIOR_TASKLIST),
    ),
)

# --- Task lists (write) ---

GOOGLE_TASKS_CREATE_TASKLIST_QUESTIONS = (
    VerificationQuestion(
        id="title_matches",
        text="Does title match the new task list name the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_tasklist_call", "title"), _USER_GOAL),
    ),
)

GOOGLE_TASKS_UPDATE_TASKLIST_QUESTIONS = (
    VerificationQuestion(
        id="tasklist_id_correct",
        text="Is tasklist_id the list the user asked to rename?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_tasklist_call", "tasklist_id", "title"), _USER_GOAL, _PRIOR_TASKLIST),
    ),
    VerificationQuestion(
        id="title_matches",
        text="Does title match the new list name the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_tasklist_call", "title"), _USER_GOAL),
    ),
)

GOOGLE_TASKS_PATCH_TASKLIST_QUESTIONS = (
    VerificationQuestion(
        id="tasklist_id_correct",
        text="Is tasklist_id the list the user asked to update?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("patch_tasklist_call", "tasklist_id", "title"), _USER_GOAL, _PRIOR_TASKLIST),
    ),
    VerificationQuestion(
        id="title_matches",
        text="Does title match what the user asked to change?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("patch_tasklist_call", "title"), _USER_GOAL),
    ),
)

GOOGLE_TASKS_DELETE_TASKLIST_QUESTIONS = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Is confirm=true set for deleting the entire task list and all its tasks?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_tasklist_call", "tasklist_id", "confirm"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="tasklist_id_correct",
        text="Is tasklist_id the list the user explicitly asked to delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_tasklist_call", "tasklist_id"), _USER_GOAL, _PRIOR_TASKLIST),
    ),
    VerificationQuestion(
        id="delete_list_not_clear",
        text="Did the user want to delete the whole list, not just hide completed tasks?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

# --- Tasks (read) ---

GOOGLE_TASKS_LIST_TASKS_QUESTIONS = (
    VerificationQuestion(
        id="tasklist_scope",
        text="Is tasklist_id (or default) the list the user asked to browse?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_tasks_call", "tasklist_id", "due_min", "due_max"), _USER_GOAL, _PRIOR_TASKLIST),
    ),
    VerificationQuestion(
        id="due_filters_match",
        text="Do due_min/due_max match the date range the user asked for?",
        severity=SEVERITY_WARN,
        evidence=(_call("list_tasks_call", "due_min", "due_max"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="view_not_specialized",
        text="Would list_today/list_overdue/list_upcoming have been a better fit than generic list?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
)

GOOGLE_TASKS_GET_TASK_QUESTIONS = (
    VerificationQuestion(
        id="task_target_correct",
        text="Do tasklist_id and task_id identify the task the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("get_task_call", "tasklist_id", "task_id"), _USER_GOAL, _PRIOR_TASKS_CONTEXT),
    ),
)

GOOGLE_TASKS_LIST_DEFAULT_TASKS_QUESTIONS = (
    VerificationQuestion(
        id="default_list_intent",
        text="Did the user ask for todos on their main/default list (My Tasks)?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="completed_scope",
        text="Does include_completed match whether the user wanted done items too?",
        severity=SEVERITY_INFO,
        evidence=(_call("list_default_call", "include_completed"), _USER_GOAL),
    ),
)

GOOGLE_TASKS_LIST_TODAY_QUESTIONS = (
    VerificationQuestion(
        id="today_view_intent",
        text="Did the user ask for tasks due today specifically?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="tasklist_scope",
        text="Is tasklist_id (or default) the list scope the user intended?",
        severity=SEVERITY_WARN,
        evidence=(_call("list_today_call", "tasklist_id", "time_zone"), _USER_GOAL, _PRIOR_TASKLIST),
    ),
)

GOOGLE_TASKS_LIST_OVERDUE_QUESTIONS = (
    VerificationQuestion(
        id="overdue_view_intent",
        text="Did the user ask for overdue/past-due open tasks?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="tasklist_scope",
        text="Is tasklist_id scoped to the list the user cares about?",
        severity=SEVERITY_INFO,
        evidence=(_call("list_overdue_call", "tasklist_id"), _USER_GOAL, _PRIOR_TASKLIST),
    ),
)

GOOGLE_TASKS_LIST_UPCOMING_QUESTIONS = (
    VerificationQuestion(
        id="upcoming_window",
        text="Does days_ahead match how far ahead the user asked to look?",
        severity=SEVERITY_WARN,
        evidence=(_call("list_upcoming_call", "days_ahead", "time_zone"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="tasklist_scope",
        text="Is tasklist_id the list the user wanted upcoming tasks from?",
        severity=SEVERITY_INFO,
        evidence=(_call("list_upcoming_call", "tasklist_id"), _USER_GOAL, _PRIOR_TASKLIST),
    ),
)

GOOGLE_TASKS_SEARCH_TASKS_QUESTIONS = (
    VerificationQuestion(
        id="query_matches_intent",
        text="Does query match the title/notes substring the user asked to find?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("search_call", "query", "tasklist_id"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="search_scope",
        text="If tasklist_id is set, is it the list the user wanted to search; if omitted, did they mean all lists?",
        severity=SEVERITY_WARN,
        evidence=(_call("search_call", "tasklist_id"), _USER_GOAL, _PRIOR_TASKLIST),
    ),
)

GOOGLE_TASKS_LIST_SUBTASKS_QUESTIONS = (
    VerificationQuestion(
        id="parent_task_correct",
        text="Is parent_task_id the parent task whose subtasks the user asked to list?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("list_subtasks_call", "tasklist_id", "parent_task_id"), _USER_GOAL, _PRIOR_TASK_READ),
    ),
)

GOOGLE_TASKS_LIST_ALL_OPEN_TASKS_QUESTIONS = (
    VerificationQuestion(
        id="cross_list_intent",
        text="Did the user ask for open tasks across all lists, not one list only?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="limits_sufficient",
        text="Are max_results_per_list and max_total high enough not to miss the target task?",
        severity=SEVERITY_INFO,
        evidence=(_call("list_all_open_call", "max_results_per_list", "max_total"), _USER_GOAL),
    ),
)

# --- Tasks (write) ---

GOOGLE_TASKS_CREATE_TASK_QUESTIONS = (
    VerificationQuestion(
        id="title_matches",
        text="Does title match the todo the user asked to create?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_task_call", "title", "notes", "due", "status"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="tasklist_scope",
        text="Is tasklist_id (or default) where the user wanted the new task?",
        severity=SEVERITY_WARN,
        evidence=(_call("create_task_call", "tasklist_id"), _USER_GOAL, _PRIOR_TASKLIST),
    ),
    VerificationQuestion(
        id="subtask_parent",
        text="If parent is set, is it the correct parent task for a subtask?",
        severity=SEVERITY_WARN,
        evidence=(_call("create_task_call", "parent", "previous"), _USER_GOAL, _PRIOR_TASK_READ),
    ),
    VerificationQuestion(
        id="task_created_live",
        text="Does live get_task show the created task with expected title/due/status?",
        severity=SEVERITY_WARN,
        evidence=(_call("create_task_call", "title", "due", "status"), _LIVE_TASK, _USER_GOAL),
    ),
)

GOOGLE_TASKS_QUICK_ADD_TASK_QUESTIONS = (
    VerificationQuestion(
        id="title_matches",
        text="Does title match the quick todo the user asked to add?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("quick_add_call", "title", "notes", "due"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="default_list_intended",
        text="Did the user want the default My Tasks list (not a named list)?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL, _PRIOR_TASKS_CONTEXT),
    ),
    VerificationQuestion(
        id="task_created_live",
        text="Does live get_task on the created task confirm title and due?",
        severity=SEVERITY_WARN,
        evidence=(_call("quick_add_call", "title", "due"), _LIVE_TASK, _USER_GOAL),
    ),
)

GOOGLE_TASKS_UPDATE_TASK_QUESTIONS = (
    VerificationQuestion(
        id="task_target_correct",
        text="Are tasklist_id and task_id the task the user asked to replace?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_task_call", "tasklist_id", "task_id"), _USER_GOAL, _PRIOR_TASK_READ),
    ),
    VerificationQuestion(
        id="full_replace_intended",
        text="Did the user want a full replace (omitted fields cleared), not a partial patch?",
        severity=SEVERITY_WARN,
        evidence=(_call("update_task_call", "title", "notes", "due", "status"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="fields_match_intent",
        text="Do title/notes/due/status match what the user asked to set?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("update_task_call", "title", "notes", "due", "status"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="task_state_live",
        text="Does live get_task reflect the updated task fields?",
        severity=SEVERITY_WARN,
        evidence=(_call("update_task_call", "task_id", "title", "status"), _LIVE_TASK, _USER_GOAL),
    ),
)

GOOGLE_TASKS_PATCH_TASK_QUESTIONS = (
    VerificationQuestion(
        id="task_target_correct",
        text="Are tasklist_id and task_id the task the user asked to edit?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("patch_task_call", "tasklist_id", "task_id"), _USER_GOAL, _PRIOR_TASK_READ),
    ),
    VerificationQuestion(
        id="partial_fields_match",
        text="Do only the provided fields (title/notes/due/status) match the user's requested change?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("patch_task_call", "title", "notes", "due", "status"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="patch_not_complete_confusion",
        text="If status changed, does it match complete vs reopen intent (not accidental toggle)?",
        severity=SEVERITY_WARN,
        evidence=(_call("patch_task_call", "status"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="task_state_live",
        text="Does live get_task confirm the patched fields?",
        severity=SEVERITY_WARN,
        evidence=(_call("patch_task_call", "task_id", "title", "due", "status"), _LIVE_TASK, _USER_GOAL),
    ),
)

GOOGLE_TASKS_DELETE_TASK_QUESTIONS = (
    VerificationQuestion(
        id="task_target_correct",
        text="Are tasklist_id and task_id the task the user asked to delete permanently?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_task_call", "tasklist_id", "task_id"), _USER_GOAL, _PRIOR_TASK_READ),
    ),
    VerificationQuestion(
        id="delete_not_complete",
        text="Did the user want permanent delete, not just mark complete?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

GOOGLE_TASKS_MOVE_TASK_QUESTIONS = (
    VerificationQuestion(
        id="task_target_correct",
        text="Are tasklist_id and task_id the task the user asked to move or reorder?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("move_call", "tasklist_id", "task_id"), _USER_GOAL, _PRIOR_TASK_READ),
    ),
    VerificationQuestion(
        id="destination_list",
        text="If destination_tasklist_id is set, is it the target list the user specified?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("move_call", "destination_tasklist_id"), _USER_GOAL, _PRIOR_TASKLIST),
    ),
    VerificationQuestion(
        id="subtask_placement",
        text="If parent/previous are set, do they match subtask nesting or ordering intent?",
        severity=SEVERITY_WARN,
        evidence=(_call("move_call", "parent", "previous"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="task_moved_live",
        text="Does live get_task show the task in the expected list/state after move?",
        severity=SEVERITY_WARN,
        evidence=(_call("move_call", "task_id", "destination_tasklist_id"), _LIVE_TASK, _USER_GOAL),
    ),
)

GOOGLE_TASKS_CLEAR_COMPLETED_QUESTIONS = (
    VerificationQuestion(
        id="confirm_explicit",
        text="Is confirm=true set for hiding all completed tasks in the list?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("clear_completed_call", "confirm", "tasklist_id"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="clear_not_delete_list",
        text="Did the user want to hide completed tasks, not delete the whole list or active tasks?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="tasklist_scope",
        text="Is tasklist_id (or default) the list whose completed items should be cleared?",
        severity=SEVERITY_WARN,
        evidence=(_call("clear_completed_call", "tasklist_id"), _USER_GOAL, _PRIOR_TASKLIST),
    ),
)

GOOGLE_TASKS_COMPLETE_TASK_QUESTIONS = (
    VerificationQuestion(
        id="task_target_correct",
        text="Are tasklist_id and task_id the open task the user asked to mark done?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("complete_call", "tasklist_id", "task_id"), _USER_GOAL, _PRIOR_TASK_READ),
    ),
    VerificationQuestion(
        id="complete_not_delete",
        text="Did the user want to complete the task, not delete it?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="status_completed_live",
        text="Does live get_task show status completed?",
        severity=SEVERITY_WARN,
        evidence=(_call("complete_call", "task_id"), _LIVE_TASK, _USER_GOAL),
    ),
)

GOOGLE_TASKS_UNCOMPLETE_TASK_QUESTIONS = (
    VerificationQuestion(
        id="task_target_correct",
        text="Are tasklist_id and task_id the completed task the user asked to reopen?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("uncomplete_call", "tasklist_id", "task_id"), _USER_GOAL, _PRIOR_TASK_READ),
    ),
    VerificationQuestion(
        id="reopen_not_delete",
        text="Did the user want to reopen the task, not delete or recreate it?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="status_open_live",
        text="Does live get_task show status needsAction after reopen?",
        severity=SEVERITY_WARN,
        evidence=(_call("uncomplete_call", "task_id"), _LIVE_TASK, _USER_GOAL),
    ),
)

TASKS_CHECKER_QUESTIONS_BY_TOOL: dict[str, tuple[VerificationQuestion, ...]] = {
    "google.tasks.list_tasklists": GOOGLE_TASKS_LIST_TASKLISTS_QUESTIONS,
    "google.tasks.get_tasklist": GOOGLE_TASKS_GET_TASKLIST_QUESTIONS,
    "google.tasks.create_tasklist": GOOGLE_TASKS_CREATE_TASKLIST_QUESTIONS,
    "google.tasks.update_tasklist": GOOGLE_TASKS_UPDATE_TASKLIST_QUESTIONS,
    "google.tasks.patch_tasklist": GOOGLE_TASKS_PATCH_TASKLIST_QUESTIONS,
    "google.tasks.delete_tasklist": GOOGLE_TASKS_DELETE_TASKLIST_QUESTIONS,
    "google.tasks.list_tasks": GOOGLE_TASKS_LIST_TASKS_QUESTIONS,
    "google.tasks.get_task": GOOGLE_TASKS_GET_TASK_QUESTIONS,
    "google.tasks.create_task": GOOGLE_TASKS_CREATE_TASK_QUESTIONS,
    "google.tasks.update_task": GOOGLE_TASKS_UPDATE_TASK_QUESTIONS,
    "google.tasks.patch_task": GOOGLE_TASKS_PATCH_TASK_QUESTIONS,
    "google.tasks.delete_task": GOOGLE_TASKS_DELETE_TASK_QUESTIONS,
    "google.tasks.move_task": GOOGLE_TASKS_MOVE_TASK_QUESTIONS,
    "google.tasks.clear_completed": GOOGLE_TASKS_CLEAR_COMPLETED_QUESTIONS,
    "google.tasks.list_default_tasks": GOOGLE_TASKS_LIST_DEFAULT_TASKS_QUESTIONS,
    "google.tasks.list_today": GOOGLE_TASKS_LIST_TODAY_QUESTIONS,
    "google.tasks.list_overdue": GOOGLE_TASKS_LIST_OVERDUE_QUESTIONS,
    "google.tasks.list_upcoming": GOOGLE_TASKS_LIST_UPCOMING_QUESTIONS,
    "google.tasks.search_tasks": GOOGLE_TASKS_SEARCH_TASKS_QUESTIONS,
    "google.tasks.list_subtasks": GOOGLE_TASKS_LIST_SUBTASKS_QUESTIONS,
    "google.tasks.list_all_open_tasks": GOOGLE_TASKS_LIST_ALL_OPEN_TASKS_QUESTIONS,
    "google.tasks.quick_add_task": GOOGLE_TASKS_QUICK_ADD_TASK_QUESTIONS,
    "google.tasks.complete_task": GOOGLE_TASKS_COMPLETE_TASK_QUESTIONS,
    "google.tasks.uncomplete_task": GOOGLE_TASKS_UNCOMPLETE_TASK_QUESTIONS,
}

TASKS_CHECKER_ALL_TOOL_NAMES = tuple(TASKS_CHECKER_QUESTIONS_BY_TOOL.keys())

TASKS_CHECKER_READ_TOOL_NAMES = tuple(
    name
    for name in TASKS_CHECKER_ALL_TOOL_NAMES
    if name.endswith(
        (
            ".list_tasklists",
            ".get_tasklist",
            ".list_tasks",
            ".get_task",
            ".list_default_tasks",
            ".list_today",
            ".list_overdue",
            ".list_upcoming",
            ".search_tasks",
            ".list_subtasks",
            ".list_all_open_tasks",
        )
    )
)

TASKS_CHECKER_WRITE_TOOL_NAMES = tuple(
    name for name in TASKS_CHECKER_ALL_TOOL_NAMES if name not in TASKS_CHECKER_READ_TOOL_NAMES
)
