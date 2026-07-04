---
skill_id: google.tasks
description: Google Tasks — todos, lists, subtasks, due dates, complete/reopen (OAuth)
tags: google, tasks
---

# Google Tasks skill

Use when the user asks about **todos, task lists, reminders with due dates, subtasks, or Google Tasks** — not Calendar meetings/events.

**Auth:** user OAuth — `google.auth.status` → `tasks_ready=true`. Same `/connect_google` as Calendar/Gmail/Drive. If `tasks_ready=false` after connect → user must re-run `/connect_google` (new scopes).

**Default list:** omit `tasklist_id` → bot resolves user's default (usually «My Tasks»). For named lists → `list_tasklists` first.

**Due dates:** Google Tasks API is **date-only** — pass `YYYY-MM-DD` (time in ISO datetime is ignored).

**Not Tasks:** meetings, calls, calendar blocks → `google.calendar.*`.

## Discovery

Load once per run: `skills.load` → `skill_id: "google.tasks"`.

`search_tools` tags (AND):

| Need | search_tools |
|------|----------------|
| Full Tasks catalog (24 tools) | `{"mode":"catalog","tags":["google","tasks"]}` |
| Read tasks | `{"mode":"catalog","tags":["google","tasks","read"]}` |
| Create/edit/delete tasks | `{"mode":"catalog","tags":["google","tasks","write"]}` |
| Task lists CRUD | `{"mode":"catalog","tags":["google","tasks","tasklists"]}` |
| Subtasks | `{"mode":"catalog","tags":["google","tasks","subtasks"]}` |
| Rank by task | `{"mode":"rank","query":"add todo buy milk","tags":["google","tasks"]}` |

## Standard flows

### What's on my todo list?

| User intent | Tool |
|-------------|------|
| Default list (My Tasks) | `list_default_tasks` |
| Due today | `list_today` |
| Overdue | `list_overdue` |
| Due next N days | `list_upcoming` (`days_ahead`, default 7) |
| All open across lists | `list_all_open_tasks` |
| One list with filters | `list_tasks` (`due_min`/`due_max`, `tasklist_id`) |
| Search by keyword | `search_tasks` (`query`; all lists unless `tasklist_id` set) |
| One task by id | `get_task` |
| Subtasks of parent | `list_subtasks` (`parent_task_id`) |

Prefer sugar tools (`list_default_tasks`, `list_today`, …) over raw `list_tasks` for common views.

### Add / complete / edit / delete tasks

| User intent | Tool |
|-------------|------|
| Quick todo on default list | `quick_add_task` (`title`, optional `due`, `notes`) |
| Task on specific list / subtask | `create_task` (`tasklist_id`, `parent` for subtask) |
| Mark done | `complete_task` (`task_id` from list/search) |
| Reopen | `uncomplete_task` |
| Small edit (title, due, notes) | `patch_task` |
| Full replace | `update_task` — omitted fields cleared |
| Delete permanently | `delete_task` |
| Move list / nest subtask / reorder | `move_task` (`destination_tasklist_id`, `parent`, `previous`) |

**Recurring/assigned tasks:** `move_task` may fail — tool returns a clear error.

### Task lists (not individual tasks)

| Tool | When |
|------|------|
| `list_tasklists` | All lists + `default_tasklist_id` |
| `get_tasklist` | Metadata for one list |
| `create_tasklist` | New list (Shopping, Work, …) |
| `patch_tasklist` / `update_tasklist` | Rename list |
| `delete_tasklist` | Delete list **and all its tasks** — **`confirm=true`** |
| `clear_completed` | Hide completed tasks in a list — **`confirm=true`** |

## Subtasks

- Create: `create_task` with `parent` = parent `task_id`
- List: `list_subtasks` with `parent_task_id`
- Reorder/nest: `move_task` with `parent` / `previous`

## Links in replies

When the user should open a task in Google Tasks:
- Put `webViewLink` from tool result or `tasks.google.com` URL in the **final reply** (plain or `[title](url)`, up to 5).
- Inline buttons; stripped from visible text.
- URLs only in tool JSON → collapsed «Ссылки» — paste in reply if user should tap.

## Destructive actions (require `confirm=true`)

| Tool | Effect |
|------|--------|
| `delete_tasklist` | Deletes list and **all** tasks in it |
| `clear_completed` | Hides all completed tasks (does not delete open tasks) |

Warn user before confirming `delete_tasklist`.

## Anti-patterns

| Wrong | Right |
|-------|-------|
| `google.calendar.create_event` for a todo | `quick_add_task` / `create_task` |
| `list_tasks` for «my todos» | `list_default_tasks` |
| `list_today` (calendar) for tasks due today | `google.tasks.list_today` |
| Exa web search for user's todos | `search_tasks` / `list_default_tasks` |
| Invent `task_id` | From list/search/create result |
| `update_task` for rename only | `patch_task` |
| Time-specific due (15:00) | Tasks only store **date** — use Calendar for timed events |

## Typical user requests

| User says | Flow |
|-----------|------|
| «Мои задачи» | `list_default_tasks` |
| «Что на сегодня?» (todos) | `list_today` |
| «Просроченные» | `list_overdue` |
| «Добавь купить молоко» | `quick_add_task` |
| «Добавь в список Покупки» | `list_tasklists` → `create_task` |
| «Отметь выполненным» | `search_tasks` → `complete_task` |
| «Найди задачу про отчёт» | `search_tasks` |
| «Создай список Работа» | `create_tasklist` |
| «Подзадачи у задачи X» | `list_subtasks` |

## All 24 tools (prefix `google.tasks.`)

**Lists:** `list_tasklists`, `get_tasklist`, `create_tasklist`, `update_tasklist`, `patch_tasklist`, `delete_tasklist`

**Read tasks:** `list_default_tasks`, `list_today`, `list_overdue`, `list_upcoming`, `list_all_open_tasks`, `list_tasks`, `get_task`, `search_tasks`, `list_subtasks`

**Write tasks:** `quick_add_task`, `create_task`, `patch_task`, `update_task`, `delete_task`, `complete_task`, `uncomplete_task`, `move_task`, `clear_completed`
