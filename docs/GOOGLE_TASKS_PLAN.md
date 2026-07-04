# Google Tasks — план интеграции

Полный каталог tools, волны реализации, OAuth, inline-кнопки и технические детали.  
Файл для **ревью перед кодом** — как `GOOGLE_CALENDAR_PLAN.md`, `GOOGLE_GMAIL_PLAN.md`, `GOOGLE_SHEETS_PLAN.md`.

---

## 1. Цель

Telegram-бот (Hermes Agent) получает **полный доступ к Google Tasks** пользователя через **тот же Google OAuth 2.0**, что Calendar / Gmail / Drive / Sheets.

Агент вызывает tools через существующий flow: `search_tools` → `use_tool`.  
**Tool graph не используется** — tasks tools регистрируются в общем registry с тегами.  
**Embedding index** пересобирается автоматически при старте бота (Fireworks embeddings) — новые tools сразу доступны через `search_tools`.

```json
{"mode": "catalog", "tags": ["google", "tasks"]}
{"mode": "rank", "query": "add todo buy milk", "tags": ["google", "tasks", "write"]}
{"mode": "rank", "query": "what is due today", "tags": ["google", "tasks", "read"]}
```

### Что пользователь может делать

- смотреть списки задач (task lists) и задачи внутри них
- создавать / редактировать / удалять задачи и подзадачи
- отмечать выполненными / возвращать в работу
- фильтровать по due date (сегодня, просроченные, ближайшие N дней)
- искать задачи по названию (в одном списке или во всех)
- переносить задачи между списками и менять порядок / вложенность
- управлять списками (создать «Покупки», переименовать, удалить)
- очищать выполненные из списка

### Связь с Calendar

Google Tasks — **отдельный API** (`tasks.googleapis.com`), не Calendar API.  
Задачи с `due` **могут отображаться** в Google Calendar UI, но:

- в Tasks API `due` — **только дата** (время отбрасывается)
- нет прямого `htmlLink` на событие календаря — есть `webViewLink` на задачу в Tasks UI
- для **событий календаря** — `google.calendar.*`; для **todo** — `google.tasks.*`

---

## 2. Как работает Google Tasks (для агента)

### 2.1 Модель данных

```
User
 └── TaskList[]          (до 2000 списков)
      └── Task[]         (до 20 000 active на список, 100 000 total)
           └── SubTask[] (до 2000 на parent, через parent + move)
```

| Сущность | Ключевые поля | Примечание |
|----------|---------------|------------|
| **TaskList** | `id`, `title`, `updated` | «My Tasks», «Shopping», … |
| **Task** | `id`, `title`, `notes`, `status`, `due`, `completed`, `parent`, `position`, `webViewLink` | `status`: `needsAction` \| `completed` |
| **Subtask** | тот же Task с `parent` = id родителя | создаётся через `insert(parent=…)` или `move(parent=…)` |

### 2.2 Статусы и видимость

| Поле | Значение |
|------|----------|
| `status` | `needsAction` — активная; `completed` — выполнена |
| `hidden` | read-only; true после clear completed (скрытые выполненные) |
| `deleted` | soft-delete флаг в list при `showDeleted=true` |

### 2.3 Ограничения API (важно для промпта)

| Ограничение | Детали |
|-------------|--------|
| Assigned tasks (Docs / Chat / Gmail) | **нельзя** создать через `insert`; только read/delete/move с ограничениями |
| Notes на assigned tasks | read-only / нельзя менять |
| Recurring tasks | **нельзя** переносить между списками (`move.destinationTasklist`) |
| Due date | только **дата**, время игнорируется |
| Default list | нет alias `"primary"` — нужен реальный `tasklist_id` (см. §2.4) |
| `tasks.list` | не фильтрует по `parent` — подзадачи фильтруем на стороне handler |

### 2.4 Default task list

В Calendar есть `calendar_id="primary"`. В Tasks **нет** такого alias в API.

**Стратегия Hermes:**

1. При первом вызове `google.tasks.*` без `tasklist_id` → `GET tasklists.list` → найти список с `title` matching `My Tasks` / `Мои задачи` (case-insensitive) **или** первый список.
2. Кэшировать `default_tasklist_id` per user в SQLite (`google_tokens` metadata или отдельная колонка).
3. Sugar-tools (`quick_add_task`, `list_today`, …) используют этот default, если `tasklist_id` не передан.
4. Tool `google.tasks.list_tasklists` всегда возвращает `default_tasklist_id` в ответе для агента.

---

## 3. Auth — расширение существующего OAuth

### 3.1 Scope

| Scope | Используем |
|-------|------------|
| `https://www.googleapis.com/auth/tasks` | **да** — full read/write |
| `https://www.googleapis.com/auth/tasks.readonly` | нет — слишком узко для агента |

**Добавить в `DEFAULT_GOOGLE_OAUTH_SCOPES`:**

```env
GOOGLE_OAUTH_SCOPES=...,https://www.googleapis.com/auth/tasks
```

### 3.2 Re-consent

- Старые токены без `tasks` scope → `{ok: false, error: "Tasks scope missing — run /connect_google again"}`
- `google.auth.status` → + `tasks_ready: true/false`
- `/connect_google` текст: «Calendar, Gmail, Drive, Sheets **и Tasks**»
- `/disconnect_google` — без изменений

### 3.3 GCP

- Enable **Google Tasks API** в том же проекте, что Calendar/Gmail
- Consent screen: scope `tasks` non-sensitive (обычно без verification для personal/testing mode)

### 3.4 Auth tools (3) — без новых имён

| Tool | Изменение |
|------|-----------|
| `google.auth.status` | + `tasks_ready` |
| `google.auth.connect_url` | + tasks scope |
| `google.auth.disconnect` | без изменений |

---

## 4. Схема тегов

| Tag | Когда |
|-----|-------|
| `google` | **Все** Google tools |
| `tasks` | **Все** `google.tasks.*` |
| `read` | list, get, search, list_today, … |
| `write` | create, patch, update, delete, move, complete, clear |
| `tasklists` | CRUD списков задач |
| `subtasks` | create/move с parent, list_subtasks |

**Минимум:** `tags=("google", "tasks", "read")`  
**Фильтр:** `tags=["google", "tasks"]` → только Tasks tools (AND в search_tools).

Пример регистрации:

```python
ToolSpec(
    name="google.tasks.list_today",
    description="List tasks due today in a task list (default list if omitted).",
    parameters={...},
    handler=_handler,
    tags=("google", "tasks", "read"),
    examples=("tasks due today", "what todos today", "что в задачах на сегодня"),
)
```

---

## 5. Полный каталог — **24 tools**

Naming: `google.tasks.<action>`

### 5.1 Сводная таблица

| # | Tool | API / wrapper | Tags | Wave |
|---|------|---------------|------|------|
| **Task lists (6)** |
| 1 | `list_tasklists` | `tasklists.list` | read, tasklists | T-1 |
| 2 | `get_tasklist` | `tasklists.get` | read, tasklists | T-2 |
| 3 | `create_tasklist` | `tasklists.insert` | write, tasklists | T-3 |
| 4 | `update_tasklist` | `tasklists.update` | write, tasklists | T-3 |
| 5 | `patch_tasklist` | `tasklists.patch` | write, tasklists | T-3 |
| 6 | `delete_tasklist` | `tasklists.delete` | write, tasklists | T-3 |
| **Tasks — CRUD (8)** |
| 7 | `list_tasks` | `tasks.list` | read | T-1 |
| 8 | `get_task` | `tasks.get` | read | T-1 |
| 9 | `create_task` | `tasks.insert` | write | T-1 |
| 10 | `update_task` | `tasks.update` | write | T-2 |
| 11 | `patch_task` | `tasks.patch` | write | T-2 |
| 12 | `delete_task` | `tasks.delete` | write | T-2 |
| 13 | `move_task` | `tasks.move` | write | T-2 |
| 14 | `clear_completed` | `tasks.clear` | write | T-3 |
| **Sugar — read (6)** |
| 15 | `list_default_tasks` | wrapper → list_tasks на default list | read | T-1 |
| 16 | `list_today` | wrapper → dueMin/dueMax = today | read | T-1 |
| 17 | `list_overdue` | wrapper → due < today, needsAction | read | T-1 |
| 18 | `list_upcoming` | wrapper → due in next N days | read | T-1 |
| 19 | `search_tasks` | list + client filter by title/notes | read | T-2 |
| 20 | `list_subtasks` | list + filter parent=id | read, subtasks | T-2 |
| 21 | `list_all_open_tasks` | all lists → needsAction | read | T-2 |
| **Sugar — write (3)** |
| 22 | `quick_add_task` | insert title (+ optional due/notes) | write | T-1 |
| 23 | `complete_task` | patch status=completed | write | T-1 |
| 24 | `uncomplete_task` | patch status=needsAction | write | T-2 |

**Итого: 24 tools** (14 прямых API + 10 sugar).

---

## 6. Описание каждого tool

Compact response helper: `compact_task()`, `compact_tasklist()` — как `compact_event()` в Calendar.

### 6.1 Task lists (6)

#### `google.tasks.list_tasklists`

| | |
|---|---|
| **API** | `GET /tasks/v1/users/@me/lists` |
| **Описание** | Все списки задач пользователя |
| **Параметры** | `max_results` (optional, default 100, max 100), `page_token` (optional) |
| **Returns** | `{count, default_tasklist_id, tasklists: [{id, title, updated}]}` |
| **Tags** | `google`, `tasks`, `read`, `tasklists` |
| **Examples** | `my task lists`, `списки задач`, `show google tasks lists` |

---

#### `google.tasks.get_tasklist`

| | |
|---|---|
| **API** | `GET /tasks/v1/users/@me/lists/{tasklist}` |
| **Параметры** | `tasklist_id` (required) |
| **Returns** | `{id, title, updated}` |
| **Tags** | `google`, `tasks`, `read`, `tasklists` |
| **Wave** | T-2 |

---

#### `google.tasks.create_tasklist`

| | |
|---|---|
| **API** | `POST /tasks/v1/users/@me/lists` |
| **Параметры** | `title` (required, max 1024) |
| **Returns** | `{created: true, tasklist: {id, title}}` |
| **Tags** | `google`, `tasks`, `write`, `tasklists` |
| **Wave** | T-3 |

---

#### `google.tasks.update_tasklist`

| | |
|---|---|
| **API** | `PUT /tasks/v1/users/@me/lists/{tasklist}` |
| **Параметры** | `tasklist_id`, `title` (required) |
| **Returns** | Updated tasklist |
| **Tags** | `google`, `tasks`, `write`, `tasklists` |
| **Wave** | T-3 |

---

#### `google.tasks.patch_tasklist`

| | |
|---|---|
| **API** | `PATCH /tasks/v1/users/@me/lists/{tasklist}` |
| **Параметры** | `tasklist_id`, `title` (optional) |
| **Returns** | Updated tasklist |
| **Tags** | `google`, `tasks`, `write`, `tasklists` |
| **Wave** | T-3 |

---

#### `google.tasks.delete_tasklist`

| | |
|---|---|
| **API** | `DELETE /tasks/v1/users/@me/lists/{tasklist}` |
| **Параметры** | `tasklist_id`, `confirm` (must be `true`) |
| **Returns** | `{deleted: true, tasklist_id}` |
| **Guard** | `confirm=true`; warn if list non-empty |
| **Tags** | `google`, `tasks`, `write`, `tasklists` |
| **Wave** | T-3 |

---

### 6.2 Tasks — CRUD (8)

#### `google.tasks.list_tasks`

| | |
|---|---|
| **API** | `GET /tasks/v1/lists/{tasklist}/tasks` |
| **Описание** | Задачи в указанном списке с фильтрами API |
| **Параметры** | |
| | `tasklist_id` — optional → default list |
| | `due_min`, `due_max` — RFC3339 date bounds |
| | `completed_min`, `completed_max` — optional |
| | `updated_min` — optional |
| | `show_completed` — default `true` |
| | `show_deleted` — default `false` |
| | `show_hidden` — default `false` |
| | `show_assigned` — default `false` |
| | `max_results` — default 50, max 100 |
| | `page_token` — optional |
| **Returns** | `{tasklist_id, count, tasks: [compact_task], next_page_token?}` |
| **compact_task** | `{id, title, notes?, status, due?, completed?, parent?, webViewLink?, links?, assignmentInfo?}` |
| **Tags** | `google`, `tasks`, `read` |
| **Examples** | `list tasks in shopping list`, `all tasks with due date` |

---

#### `google.tasks.get_task`

| | |
|---|---|
| **API** | `GET /tasks/v1/lists/{tasklist}/tasks/{task}` |
| **Параметры** | `tasklist_id`, `task_id` (required) |
| **Returns** | Full compact_task |
| **Tags** | `google`, `tasks`, `read` |

---

#### `google.tasks.create_task`

| | |
|---|---|
| **API** | `POST /tasks/v1/lists/{tasklist}/tasks` |
| **Параметры** | |
| | `tasklist_id` — optional → default |
| | `title` (required) |
| | `notes` (optional, max 8192) |
| | `due` (optional, RFC3339 **date** — time stripped) |
| | `status` — optional, default `needsAction` |
| | `parent` — optional, parent task id (subtask) |
| | `previous` — optional, sibling ordering |
| **Returns** | `{created: true, task: compact_task, webViewLink}` |
| **Tags** | `google`, `tasks`, `write`, `subtasks` |
| **Examples** | `create task buy milk tomorrow`, `add subtask` |

---

#### `google.tasks.update_task`

| | |
|---|---|
| **API** | `PUT /tasks/v1/lists/{tasklist}/tasks/{task}` |
| **Описание** | Полная замена задачи (omitted fields cleared) |
| **Параметры** | `tasklist_id`, `task_id`, `title`, `notes`, `due`, `status` |
| **Returns** | Updated compact_task |
| **Tags** | `google`, `tasks`, `write` |
| **Wave** | T-2 |

---

#### `google.tasks.patch_task`

| | |
|---|---|
| **API** | `PATCH /tasks/v1/lists/{tasklist}/tasks/{task}` |
| **Параметры** | `tasklist_id`, `task_id` + any of: `title`, `notes`, `due`, `status` |
| **Returns** | Updated compact_task |
| **Tags** | `google`, `tasks`, `write` |
| **Wave** | T-2 |

---

#### `google.tasks.delete_task`

| | |
|---|---|
| **API** | `DELETE /tasks/v1/lists/{tasklist}/tasks/{task}` |
| **Параметры** | `tasklist_id`, `task_id` |
| **Returns** | `{deleted: true, task_id}` |
| **Note** | Assigned tasks: удаляет и assignment surface |
| **Tags** | `google`, `tasks`, `write` |
| **Wave** | T-2 |

---

#### `google.tasks.move_task`

| | |
|---|---|
| **API** | `POST .../tasks/{task}/move` |
| **Параметры** | |
| | `tasklist_id`, `task_id` (required) |
| | `destination_tasklist_id` — optional, другой список |
| | `parent` — optional, сделать subtask |
| | `previous` — optional, порядок среди siblings |
| **Returns** | Moved compact_task |
| **Guard** | Recurring tasks → reject cross-list move |
| **Tags** | `google`, `tasks`, `write`, `subtasks` |
| **Wave** | T-2 |

---

#### `google.tasks.clear_completed`

| | |
|---|---|
| **API** | `POST .../lists/{tasklist}/clear` |
| **Параметры** | `tasklist_id`, `confirm` (must be `true`) |
| **Returns** | `{cleared: true, tasklist_id}` |
| **Note** | Completed → hidden, не deleted |
| **Tags** | `google`, `tasks`, `write` |
| **Wave** | T-3 |

---

### 6.3 Sugar — read (6)

#### `google.tasks.list_default_tasks`

| | |
|---|---|
| **Wrapper** | `list_tasks` на default tasklist |
| **Параметры** | `show_completed` (default false), `max_results` (default 50) |
| **Returns** | `{tasklist_id, tasklist_title, count, tasks: [...]}` |
| **Tags** | `google`, `tasks`, `read` |
| **Examples** | `my todos`, `what's on my task list`, `мои задачи` |

---

#### `google.tasks.list_today`

| | |
|---|---|
| **Wrapper** | `list_tasks` + `due_min`/`due_max` = today in `BOT_TIMEZONE` |
| **Параметры** | `tasklist_id` (optional), `include_completed` (default false) |
| **Returns** | `{date, tasklist_id, count, tasks: [...]}` |
| **Tags** | `google`, `tasks`, `read` |
| **Examples** | `tasks due today`, `что сделать сегодня` |

---

#### `google.tasks.list_overdue`

| | |
|---|---|
| **Wrapper** | due < start of today, status=needsAction |
| **Параметры** | `tasklist_id` (optional), `max_results` (default 50) |
| **Returns** | `{count, tasks: [...]}` |
| **Tags** | `google`, `tasks`, `read` |

---

#### `google.tasks.list_upcoming`

| | |
|---|---|
| **Wrapper** | due from tomorrow through `days_ahead` (default 7) |
| **Параметры** | `tasklist_id`, `days_ahead`, `max_results` |
| **Returns** | `{days_ahead, count, tasks: [...]}` |
| **Tags** | `google`, `tasks`, `read` |

---

#### `google.tasks.search_tasks`

| | |
|---|---|
| **Wrapper** | list_tasks (или list_all) + case-insensitive match in title/notes |
| **Параметры** | `query` (required), `tasklist_id` (optional — all lists if omitted), `max_results` (default 20) |
| **Returns** | `{query, count, tasks: [{..., tasklist_id, tasklist_title}]}` |
| **Tags** | `google`, `tasks`, `read` |
| **Wave** | T-2 |

---

#### `google.tasks.list_subtasks`

| | |
|---|---|
| **Wrapper** | list_tasks + filter `parent == parent_task_id` |
| **Параметры** | `tasklist_id`, `parent_task_id` (required) |
| **Returns** | `{parent_task_id, count, tasks: [...]}` |
| **Tags** | `google`, `tasks`, `read`, `subtasks` |
| **Wave** | T-2 |

---

#### `google.tasks.list_all_open_tasks`

| | |
|---|---|
| **Wrapper** | foreach tasklist → list_tasks(needsAction, not hidden) |
| **Параметры** | `max_results_per_list` (default 30), `max_total` (default 50) |
| **Returns** | `{count, tasks: [{..., tasklist_id, tasklist_title}]}` |
| **Tags** | `google`, `tasks`, `read` |
| **Wave** | T-2 |
| **Note** | Rate-limit aware — cap lists scanned |

---

### 6.4 Sugar — write (3)

#### `google.tasks.quick_add_task`

| | |
|---|---|
| **Wrapper** | `create_task` на default list |
| **Параметры** | `title` (required), `due` (optional date), `notes` (optional) |
| **Returns** | `{created: true, task: compact_task, webViewLink}` |
| **Tags** | `google`, `tasks`, `write` |
| **Examples** | `remind me to call mom friday`, `добавь задачу купить хлеб` |

---

#### `google.tasks.complete_task`

| | |
|---|---|
| **Wrapper** | `patch_task` status=`completed` |
| **Параметры** | `tasklist_id`, `task_id` |
| **Returns** | `{completed: true, task: compact_task}` |
| **Tags** | `google`, `tasks`, `write` |

---

#### `google.tasks.uncomplete_task`

| | |
|---|---|
| **Wrapper** | `patch_task` status=`needsAction`, clear `completed` |
| **Параметры** | `tasklist_id`, `task_id` |
| **Returns** | `{completed: false, task: compact_task}` |
| **Tags** | `google`, `tasks`, `write` |
| **Wave** | T-2 |

---

## 7. Inline-кнопки (Tasks-UX)

По стандарту Maps / Gmail / Drive / Calendar:

| Источник URL | Поле |
|--------------|------|
| Task | `webViewLink` |
| Task (legacy) | `selfLink` — не для UI, только API |
| Assigned task | `assignmentInfo.linkToTask` → Docs/Chat |

**Collector:** `TasksLinkCollector` — ingest `webViewLink` из tool results.  
**Labels:** title задачи → «Купить молоко»; fallback «Открыть задачу»; list → per-task buttons (max 5).  
**Strip:** `strip_tasks_button_urls` — `tasks.google.com`, `webViewLink` из текста ответа.

---

## 8. Типовые workflows (agent prompt)

### «Что на сегодня?»

```
search_tools(tags=[google, tasks])
→ list_today
→ ответ текстом + webViewLink → inline buttons
```

### «Добавь задачу»

```
quick_add_task(title=..., due=optional)
или create_task(tasklist_id=...) если указан список
```

### «Отметь выполненным»

```
search_tasks(query=...) → complete_task(task_id=...)
```

### «Подзадачи»

```
get_task → create_task(parent=...) или list_subtasks
```

### «Перенести в другой список»

```
list_tasklists → move_task(destination_tasklist_id=...)
```

---

## 9. Инфраструктура (новые файлы)

```
tools/builtins/google/
  tasks_client.py           # build_tasks_service(), async wrapper
  tasks_serialize.py          # compact_task, compact_tasklist
  tasks_defaults.py           # resolve_default_tasklist_id(user_id)
  tasks_tasklists.py          # handlers 1–6
  tasks_core.py               # handlers 7–14
  tasks_sugar.py              # handlers 15–24
  tasks_tools.py              # ToolSpec registry + GOOGLE_TASKS_TOOLS tuple
  tasks_urls.py               # webViewLink normalize, is_tasks_url

agent/
  tasks_button_urls.py
  tasks_links.py              # TasksLinkCollector

test_google_tasks.py
docs/GOOGLE_TASKS_PLAN.md     # этот файл
```

Расширить:

- `auth.py` — `tasks_ready`, `get_tasks_service()`
- `config.py` — scope, limits
- `agent/prompts.py` — Tasks workflow section
- `agent/loop.py` — TasksLinkCollector (после Tasks-UX wave)
- `tools/builtins/google/__init__.py` — + GOOGLE_TASKS_TOOLS
- `main.py` — embedding index picks up new tools automatically

---

## 10. Волны реализации

| Wave | Tools | Count | Scope |
|------|-------|-------|-------|
| **T-1** | list_tasklists, list_tasks, get_task, create_task, list_default_tasks, list_today, list_overdue, list_upcoming, quick_add_task, complete_task | **10** | ✅ shipped |
| **T-2** | update_task, patch_task, delete_task, move_task, search_tasks, list_subtasks, list_all_open_tasks, uncomplete_task, get_tasklist | **9** | ✅ shipped |
| **T-3** | create/update/patch/delete_tasklist, clear_completed | **5** | ✅ shipped |
| **T-UX** | TasksLinkCollector + strip + prompts | — | inline buttons ✅ |
| **Total** | | **24** | |

---

## 11. Limits & config

| Env | Default | Purpose |
|-----|---------|---------|
| `TASKS_MAX_RESULTS` | 50 | default page size |
| `TASKS_MAX_NOTES_CHARS` | 2000 | truncate notes for LLM |
| `TASKS_RATE_LIMIT_READ` | 60/60 | per-user |
| `TASKS_RATE_LIMIT_WRITE` | 30/60 | per-user |
| `TASKS_DEFAULT_LIST_TITLE` | `My Tasks` | fallback title match |

Guards:

- `delete_tasklist`, `clear_completed` → `confirm=true`
- `delete_task` on assigned → warn in tool result

---

## 12. Что сознательно НЕ включаем

| Item | Why |
|------|-----|
| Создание assigned tasks (Docs/Chat) | API запрещает insert |
| Recurring tasks management | нет dedicated API surface |
| Tasks ↔ Calendar sync tool | разные API; due date only in Tasks |
| `tasks.readonly` scope only | агенту нужен write |
| Batch API | Tasks API не имеет batch endpoint |
| Google Keep | нет API |

---

## 13. Checklist перед merge

- [ ] Ревью каталога (этот файл) — **сейчас**
- [ ] Enable Tasks API in GCP
- [ ] OAuth scope + `tasks_ready` + re-consent text
- [x] T-1 → T-2 → T-3 → T-UX
- [ ] `test_google_tasks.py`
- [ ] Live smoke: list_today → quick_add → complete
- [ ] `BOT_STATUS.md` update
- [ ] Embedding index rebuild (auto on bot start)

---

## 14. Сравнение с другими Google-сервисами

| | Calendar | Gmail | Tasks |
|---|----------|-------|-------|
| Tools | 23 | 45 | **24** |
| OAuth scope | calendar | gmail.modify | **tasks** |
| Default entity | `primary` | `userId=me` | **default tasklist_id** |
| UI link field | `htmlLink` | thread URL | **`webViewLink`** |
| Inline buttons | ✅ | ✅ | ✅ |
| Sugar tools | list_today, quick_add | list_inbox, search | list_today, quick_add, complete |

---

*Draft for review — 2026-07-03*
