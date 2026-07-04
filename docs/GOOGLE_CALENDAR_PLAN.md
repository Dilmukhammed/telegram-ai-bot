# Google Calendar — план интеграции

Окончательный каталог tools, волны реализации, OAuth и технические детали.  
Файл для ревью перед кодом.

---

## 1. Цель

Telegram-бот (Hermes Agent) получает **полный доступ к Google Calendar** пользователя через OAuth 2.0.  
Агент вызывает tools через существний flow: `search_tools` → `use_tool`.  
**Tool graph не используется** — calendar tools просто регистрируются в общем registry с тегами.

Для поиска calendar tools агент вызывает:

```json
{"query": "events today", "tags": ["google", "calendar"]}
```

Пользователь может:

- смотреть расписание (сегодня, неделя, ближайшие)
- искать события по тексту
- создавать / менять / удалять события
- работать с recurring-событиями
- проверять занятость и находить свободные слоты
- управлять secondary-календарями

---

## 2. Auth

### 2.1 OAuth scope (один на весь календарь)

```
https://www.googleapis.com/auth/calendar
```

Full read/write: events + calendars + freebusy.

### 2.2 Bot commands

| Command | Действие |
|---------|----------|
| `/connect_google` | Ссылка на OAuth (Calendar scope) |
| `/disconnect_google` | Отзыв токена локально + Google revoke |
| `/google_status` | Подключён ли аккаунт, email, scopes |

### 2.3 Auth tools (3)

| Tool | Описание | Tags |
|------|----------|------|
| `google.auth.status` | `{connected, email, scopes, expires_at}` | `google`, `auth` |
| `google.auth.connect_url` | URL для OAuth (state = telegram_user_id) | `google`, `auth` |
| `google.auth.disconnect` | Отключить Google для текущего user | `google`, `auth` |

### 2.4 Хранение токенов

- SQLite: `telegram_user_id` → `refresh_token`, `access_token`, `expires_at`, `email`, `scopes`
- Refresh автоматически перед каждым API call
- Только подключённые users могут вызывать `google.calendar.*`

### 2.5 Инфраструктура OAuth

```
oauth_server.py              # FastAPI: /oauth/google/start, /oauth/google/callback
tools/builtins/google/
  auth.py                    # build_auth_url, exchange_code, refresh, revoke
  token_store.py             # CRUD credentials per user
  client.py                  # calendar v3 service wrapper
```

Env (→ `config.py`):

```
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=https://your-domain/oauth/google/callback
GOOGLE_OAUTH_SCOPES=https://www.googleapis.com/auth/calendar
```

---

## 3. Окончательный каталог tools — 22 штуки

Naming: `google.calendar.<action>`

Default `calendar_id`: `"primary"` во всех tools, где применимо.

### Схема тегов

Каждый calendar tool регистрируется в `tools/builtins/google/` и попадает в общий `BUILTIN_TOOLS` / registry.

| Tag | Когда |
|-----|-------|
| `google` | **Все** Google tools (calendar + auth) |
| `calendar` | **Все** calendar tools (`google.calendar.*`) |
| `read` | Read-only: list, get, search, freebusy |
| `write` | Create, patch, update, delete, move, import, clear |
| `calendars` | CRUD secondary calendars |
| `scheduling` | freebusy, find_free_slots |
| `auth` | OAuth tools (`google.auth.*`) |

**Минимум для calendar API tools:** `tags=("google", "calendar", …)`  
**Фильтр в search_tools:** `tags=["google", "calendar"]` → только calendar tools (AND).

Регистрация (пример):

```python
GOOGLE_CALENDAR_LIST_TODAY = ToolSpec(
    name="google.calendar.list_today",
    description="List all events for today in the user's timezone.",
    parameters={...},
    handler=_handler,
    tags=("google", "calendar", "read"),
    examples=("what is on my calendar today", "events today"),
)
```

---

### 3.1 Calendars — управление календарями (6)

#### `google.calendar.list_calendars`

| | |
|---|---|
| **API** | `GET calendars.list` |
| **Описание** | Список всех калendarей пользователя |
| **Параметры** | `show_hidden` (bool, default false), `show_deleted` (bool, default false) |
| **Returns** | `[{id, summary, description, timeZone, primary, accessRole, backgroundColor}]` |
| **Wave** | Cal-4 |

---

#### `google.calendar.get_calendar`

| | |
|---|---|
| **API** | `GET calendars.get` |
| **Описание** | Метаданные одного календаря |
| **Параметры** | `calendar_id` (required) |
| **Returns** | `{id, summary, description, timeZone, primary, ...}` |
| **Wave** | Cal-1 |

---

#### `google.calendar.create_calendar`

| | |
|---|---|
| **API** | `POST calendars.insert` |
| **Описание** | Создать новый secondary calendar |
| **Параметры** | `summary` (required), `description`, `time_zone` (IANA, default from user settings) |
| **Returns** | `{id, summary, ...}` |
| **Wave** | Cal-4 |

---

#### `google.calendar.update_calendar`

| | |
|---|---|
| **API** | `PUT calendars.update` |
| **Описание** | Полное обновление календаря |
| **Параметры** | `calendar_id`, `summary`, `description`, `time_zone` |
| **Returns** | Updated calendar object |
| **Wave** | Cal-4 |

---

#### `google.calendar.delete_calendar`

| | |
|---|---|
| **API** | `DELETE calendars.delete` |
| **Описание** | Удалить secondary calendar (не primary) |
| **Параметры** | `calendar_id` (required) |
| **Returns** | `{deleted: true}` |
| **Wave** | Cal-4 |
| **Guard** | Reject if `calendar_id == "primary"` |

---

#### `google.calendar.clear_calendar`

| | |
|---|---|
| **API** | `POST calendars.clear` |
| **Описание** | Удалить все события из календаря |
| **Параметры** | `calendar_id`, `confirm` (must be `true`) |
| **Returns** | `{cleared: true, calendar_id}` |
| **Wave** | Cal-4 |
| **Guard** | Reject primary; require `confirm: true` |

---

### 3.2 Events — чтение и поиск (6)

#### `google.calendar.list_events`

| | |
|---|---|
| **API** | `GET events.list` |
| **Описание** | События за период |
| **Параметры** | |
| | `calendar_id` — default `"primary"` |
| | `time_min` — ISO 8601 (required) |
| | `time_max` — ISO 8601 (optional) |
| | `query` — text filter (optional) |
| | `max_results` — default 25, max 250 |
| | `single_events` — default true (expand recurring) |
| | `order_by` — `startTime` \| `updated` (default `startTime`) |
| | `show_deleted` — default false |
| | `time_zone` — для интерпретации (optional) |
| **Returns** | `{count, events: [{id, summary, start, end, location, status, htmlLink, recurringEventId}]}` |
| **Wave** | Cal-1 |

---

#### `google.calendar.get_event`

| | |
|---|---|
| **API** | `GET events.get` |
| **Описание** | Одно событие по ID |
| **Параметры** | `calendar_id`, `event_id` |
| **Returns** | Full event object: summary, description, start, end, attendees, reminders, recurrence, organizer, status |
| **Wave** | Cal-1 |

---

#### `google.calendar.search_events`

| | |
|---|---|
| **API** | `GET events.list` + param `q` |
| **Описание** | Текстовый поиск по title, description, location, attendees |
| **Параметры** | |
| | `query` (required) |
| | `calendar_id` — default `"primary"`; `"all"` = search across list_calendars |
| | `time_min`, `time_max` — optional range |
| | `max_results` — default 10 |
| **Returns** | `{query, count, events: [...]}` |
| **Wave** | Cal-1 |

---

#### `google.calendar.list_upcoming`

| | |
|---|---|
| **API** | Wrapper → `events.list` |
| **Описание** | Ближайшие N событий от текущего момента |
| **Параметры** | |
| | `calendar_id` — default `"primary"` |
| | `count` — default 10, max 50 |
| | `days_ahead` — default 7 (ограничить time_max) |
| **Returns** | `{count, events: [...]}` |
| **Wave** | Cal-1 |

---

#### `google.calendar.list_today`

| | |
|---|---|
| **API** | Wrapper → `events.list` |
| **Описание** | Все события на сегодня в timezone пользователя |
| **Параметры** | |
| | `calendar_id` — default `"primary"` |
| | `time_zone` — default from `BOT_TIMEZONE` / user calendar TZ |
| **Returns** | `{date, time_zone, count, events: [...]}` |
| **Wave** | Cal-1 |

---

#### `google.calendar.list_instances`

| | |
|---|---|
| **API** | `GET events.instances` |
| **Описание** | Все вхождения recurring-события в диапазоне |
| **Параметры** | |
| | `calendar_id`, `event_id` (recurring master id) |
| | `time_min`, `time_max` (required) |
| | `max_results` — default 25 |
| **Returns** | `{recurring_event_id, count, instances: [...]}` |
| **Wave** | Cal-3 |

---

### 3.3 Events — создание и изменение (7)

#### `google.calendar.create_event`

| | |
|---|---|
| **API** | `POST events.insert` |
| **Описание** | Создать событие с полным набором полей |
| **Параметры** | |
| | `calendar_id` — default `"primary"` |
| | `summary` (required) |
| | `start` — `{datetime, time_zone}` или `{date}` для all-day |
| | `end` — same format |
| | `description`, `location` — optional |
| | `attendees` — `[{email, display_name?}]` |
| | `reminders` — `{use_default: true}` или `{overrides: [{method: "popup"\|"email", minutes: int}]}` |
| | `recurrence` — `["RRULE:FREQ=WEEKLY;BYDAY=MO"]` |
| | `color_id` — optional |
| | `send_updates` — `all` \| `externalOnly` \| `none` (default `none`) |
| **Returns** | Created event object + `htmlLink` |
| **Wave** | Cal-2 |

---

#### `google.calendar.quick_add_event`

| | |
|---|---|
| **API** | `POST events.quickAdd` |
| **Описание** | Создать из natural language |
| **Параметры** | |
| | `calendar_id` — default `"primary"` |
| | `text` (required) — e.g. `"Обед с Алией завтра в 13:00"` |
| | `send_updates` — default `none` |
| **Returns** | Created event object |
| **Wave** | Cal-2 |

---

#### `google.calendar.update_event`

| | |
|---|---|
| **API** | `PUT events.update` |
| **Описание** | Полная замена события (все поля) |
| **Параметры** | Same as `create_event` + `event_id` (required) |
| **Returns** | Updated event object |
| **Wave** | Cal-3 |

---

#### `google.calendar.patch_event`

| | |
|---|---|
| **API** | `PATCH events.patch` |
| **Описание** | Частичное изменение — только переданные поля |
| **Параметры** | |
| | `calendar_id`, `event_id` (required) |
| | Any subset of: `summary`, `description`, `location`, `start`, `end`, `attendees`, `reminders`, `recurrence`, `color_id` |
| | `send_updates` — default `none` |
| **Returns** | Patched event object |
| **Wave** | Cal-2 |
| **Note** | Основной tool для «перенеси на час позже», «переименуй» |

---

#### `google.calendar.delete_event`

| | |
|---|---|
| **API** | `DELETE events.delete` |
| **Описание** | Удалить событие |
| **Параметры** | |
| | `calendar_id`, `event_id` (required) |
| | `send_updates` — default `none` |
| **Returns** | `{deleted: true, event_id}` |
| **Wave** | Cal-2 |

---

#### `google.calendar.move_event`

| | |
|---|---|
| **API** | `POST events.move` |
| **Описание** | Перенести событие в другой календарь |
| **Параметры** | |
| | `calendar_id` — source calendar |
| | `event_id` |
| | `destination_calendar_id` |
| | `send_updates` — default `none` |
| **Returns** | Moved event object |
| **Wave** | Cal-3 |

---

#### `google.calendar.import_event`

| | |
|---|---|
| **API** | `POST events.import` |
| **Описание** | Импорт private copy события |
| **Параметры** | Same as create_event fields + `calendar_id` |
| **Returns** | Imported event object |
| **Wave** | Cal-4 |
| **Note** | Редкий кейс; для миграции / копирования |

---

### 3.4 Scheduling — занятость и слоты (2)

#### `google.calendar.freebusy`

| | |
|---|---|
| **API** | `POST freebusy.query` |
| **Описание** | Когда пользователь занят/свободен |
| **Параметры** | |
| | `time_min`, `time_max` (required, ISO 8601) |
| | `calendar_ids` — default `["primary"]`; list of calendar IDs |
| | `time_zone` — optional |
| **Returns** | `{calendars: {id: {busy: [{start, end}, ...]}}}` |
| **Wave** | Cal-1 |

---

#### `google.calendar.find_free_slots`

| | |
|---|---|
| **API** | Local logic over `freebusy.query` |
| **Описание** | Найти свободные слоты заданной длительности |
| **Параметры** | |
| | `time_min`, `time_max` (required) |
| | `duration_minutes` — default 60 |
| | `calendar_ids` — default `["primary"]` |
| | `working_hours_start` — default `"09:00"` |
| | `working_hours_end` — default `"18:00"` |
| | `time_zone` — user TZ |
| | `max_slots` — default 5 |
| **Returns** | `{duration_minutes, slots: [{start, end}]}` |
| **Wave** | Cal-3 |

---

## 4. Сводная таблица (все tools + tags)

| # | Tool | Wave | R/W | Tags | API |
|---|------|------|-----|------|-----|
| 1 | `google.calendar.list_calendars` | Cal-4 | R | `google`, `calendar`, `calendars`, `read` | calendars.list |
| 2 | `google.calendar.get_calendar` | Cal-1 | R | `google`, `calendar`, `calendars`, `read` | calendars.get |
| 3 | `google.calendar.create_calendar` | Cal-4 | W | `google`, `calendar`, `calendars`, `write` | calendars.insert |
| 4 | `google.calendar.update_calendar` | Cal-4 | W | `google`, `calendar`, `calendars`, `write` | calendars.update |
| 5 | `google.calendar.delete_calendar` | Cal-4 | W | `google`, `calendar`, `calendars`, `write` | calendars.delete |
| 6 | `google.calendar.clear_calendar` | Cal-4 | W | `google`, `calendar`, `calendars`, `write` | calendars.clear |
| 7 | `google.calendar.list_events` | Cal-1 | R | `google`, `calendar`, `read` | events.list |
| 8 | `google.calendar.get_event` | Cal-1 | R | `google`, `calendar`, `read` | events.get |
| 9 | `google.calendar.search_events` | Cal-1 | R | `google`, `calendar`, `read` | events.list + q |
| 10 | `google.calendar.list_upcoming` | Cal-1 | R | `google`, `calendar`, `read` | wrapper |
| 11 | `google.calendar.list_today` | Cal-1 | R | `google`, `calendar`, `read` | wrapper |
| 12 | `google.calendar.list_instances` | Cal-3 | R | `google`, `calendar`, `read` | events.instances |
| 13 | `google.calendar.create_event` | Cal-2 | W | `google`, `calendar`, `write` | events.insert |
| 14 | `google.calendar.quick_add_event` | Cal-2 | W | `google`, `calendar`, `write` | events.quickAdd |
| 15 | `google.calendar.update_event` | Cal-3 | W | `google`, `calendar`, `write` | events.update |
| 16 | `google.calendar.patch_event` | Cal-2 | W | `google`, `calendar`, `write` | events.patch |
| 17 | `google.calendar.delete_event` | Cal-2 | W | `google`, `calendar`, `write` | events.delete |
| 18 | `google.calendar.move_event` | Cal-3 | W | `google`, `calendar`, `write` | events.move |
| 19 | `google.calendar.import_event` | Cal-4 | W | `google`, `calendar`, `write` | events.import |
| 20 | `google.calendar.freebusy` | Cal-1 | R | `google`, `calendar`, `scheduling`, `read` | freebusy.query |
| 21 | `google.calendar.find_free_slots` | Cal-3 | R | `google`, `calendar`, `scheduling`, `read` | local + freebusy |
| 22 | `google.auth.status` | OAuth | — | `google`, `auth` | — |
| 23 | `google.auth.connect_url` | OAuth | — | `google`, `auth` | — |
| 24 | `google.auth.disconnect` | OAuth | — | `google`, `auth` | — |

---

## 5. Волны реализации

### Wave OAuth — prerequisite

- [ ] Google Cloud project + OAuth client
- [ ] `oauth_server.py` callback
- [ ] `token_store.py` + encryption
- [ ] `/connect_google`, `/disconnect_google`, `/google_status`
- [ ] `google.auth.*` tools
- [ ] Guard: `google.calendar.*` fails with «connect Google first» if no token

**Deliverable:** user can connect account; bot knows email.

---

### Wave Cal-1 — read-only (7 calendar tools)

Tools:

1. `google.calendar.get_calendar`
2. `google.calendar.list_events`
3. `google.calendar.get_event`
4. `google.calendar.search_events`
5. `google.calendar.list_upcoming`
6. `google.calendar.list_today`
7. `google.calendar.freebusy`

**Deliverable:** «что сегодня», «что на неделе», «найди встречу с X», «когда я свободен».

Tests:

- [ ] list_today returns events in user TZ
- [ ] search finds by title
- [ ] freebusy returns busy blocks
- [ ] no token → clear error message

---

### Wave Cal-2 — daily write (4 tools)

Tools:

8. `google.calendar.create_event`
9. `google.calendar.quick_add_event`
10. `google.calendar.patch_event`
11. `google.calendar.delete_event`

**Deliverable:** «поставь встречу», «перенеси на 15:00», «отмени», quick add NL.

Tests:

- [ ] create all-day and timed events
- [ ] patch moves start/end
- [ ] delete removes event
- [ ] quick_add parses Russian text

---

### Wave Cal-3 — advanced (5 tools)

Tools:

12. `google.calendar.update_event`
13. `google.calendar.move_event`
14. `google.calendar.list_instances`
15. `google.calendar.find_free_slots`

**Deliverable:** recurring events, find meeting slot, move between calendars, full replace.

Tests:

- [ ] weekly recurring → list_instances
- [ ] find_free_slots respects working hours
- [ ] move_event changes calendar_id

---

### Wave Cal-4 — power user (6 tools)

Tools:

16. `google.calendar.list_calendars`
17. `google.calendar.create_calendar`
18. `google.calendar.update_calendar`
19. `google.calendar.delete_calendar`
20. `google.calendar.clear_calendar`
21. `google.calendar.import_event`

**Deliverable:** multi-calendar workflows, cleanup, import.

Guards:

- [ ] cannot delete/clear primary
- [ ] clear requires `confirm: true`

---

## 6. Регистрация в registry (без tool graph)

Calendar tools добавляются в общий список инструментов — **без** graph hints / related_tools.

```
tools/builtins/google/__init__.py   # GOOGLE_TOOLS tuple
tools/builtins/__init__.py          # BUILTIN_TOOLS += GOOGLE_TOOLS
```

После регистрации tools автоматически:

- индексируются для embedding/keyword search (name, description, tags, examples)
- фильтруются через `search_tools(..., tags=["google", "calendar"])`
- возвращают `tags` в результате search

**Tool graph** — отдельная фича из ROADMAP, подключим позже.

---

## 7. Agent prompt hints

Добавить в system/agent prompt:

- For Google Calendar tasks, call `search_tools` with `tags: ["google", "calendar"]`.
- Default calendar: `primary`
- Datetime always ISO 8601 with timezone
- Use `list_today` / `list_upcoming` for schedule questions — not raw `list_events` unless custom range
- Use `patch_event` for small changes; `update_event` only when replacing many fields
- Use `quick_add_event` when user gives informal NL time
- Use `search_events` before patch/delete if user didn't specify exact event
- For «когда свободен» → `freebusy` or `find_free_slots`, then offer `create_event`
- `send_updates: none` by default unless user asks to notify attendees
- Recurring: create with `recurrence` RRULE; edit single instance vs series — patch with care (document in tool response)

---

## 8. Rate limits & cache

| Tool group | cache_ttl | rate_limit |
|------------|-----------|------------|
| Read (list, get, search, freebusy) | 60s | 30/min per user |
| Write (create, patch, delete, ...) | none | 20/min per user |
| Sugar (list_today, list_upcoming) | 30s | same as read |

Google Calendar API quotas: 1,000,000 queries/day per project — sufficient for personal bot.

---

## 9. File layout (final)

```
oauth_server.py
tools/builtins/google/
  __init__.py              # register all tools
  auth.py
  token_store.py
  client.py                # Calendar API v3 async wrapper
  calendar_list.py         # list_events, list_today, list_upcoming, search
  calendar_read.py         # get_event, get_calendar, list_instances
  calendar_write.py        # create, patch, update, delete, quick_add, move, import
  calendar_calendars.py    # list/create/update/delete/clear calendars
  calendar_scheduling.py   # freebusy, find_free_slots
  serialize.py             # event → compact dict for LLM
config.py                  # GOOGLE_* env vars
```

---

## 10. Explicitly NOT in scope

| Feature | Reason |
|---------|--------|
| `events.watch` (push notifications) | Needs public HTTPS webhook |
| ACL / calendar sharing | Rare in Telegram bot |
| Calendar colors / settings | Settings API deferred; colors implemented via `list_colors` + `set_calendar_color` + `color_id` on events |
| Google Meet auto-create | Optional v2 (`conferenceDataVersion`); not v1 |
| Sync with other calendars | Out of scope |
| Multi-user shared bot calendar | Each user = own OAuth token |

---

## 11. Open decisions (for review)

- [ ] **Single user (admin only)** vs any Telegram user connects own Google?
- [ ] **OAuth server:** separate process or embedded in bot process?
- [ ] **Public URL** for callback — ngrok / VPS / Cloudflare tunnel?
- [ ] **Google Meet links** in `create_event` — v1 or later?
- [ ] **`search_events` with `calendar_id: "all"`** — search all calendars or primary only by default?

---

## 12. Checklist before coding

- [ ] Review this file ✓
- [ ] Confirm wave order (OAuth → Cal-1 → Cal-2 → Cal-3 → Cal-4)
- [ ] Confirm tool names / parameters
- [ ] Google Cloud project created
- [ ] Redirect URI decided
- [ ] Add `GOOGLE_*` to `config.py` + `.env.example`

---

*Last updated: 2026-07-02*

---

## 13. Статус реализации (2026-07-02)

### Сделано

| Блок | Что |
|------|-----|
| **OAuth** | Desktop client, manual paste flow, PKCE pending store, `/connect_google`, `/disconnect_google`, `/google_status`, auto-detect callback URL в сообщениях |
| **Auth tools** | `google.auth.status`, `google.auth.connect_url`, `google.auth.disconnect` |
| **Cal-1 read** | `get_calendar`, `list_events`, `get_event`, `search_events`, `list_upcoming`, `list_today`, `freebusy` |
| **Cal-2 write** | `create_event`, `quick_add_event`, `patch_event`, `delete_event` |
| **Cal-3** | `update_event`, `move_event`, `list_instances`, `find_free_slots` |
| **Cal-4** | `list_calendars`, `create_calendar`, `update_calendar`, `delete_calendar`, `clear_calendar`, `import_event` |
| **Colors** | `list_colors` (palette), `set_calendar_color` (calendarList), `color_id` на create/patch/update/import событий |
| **Guards** | delete/clear primary запрещены; clear требует `confirm: true`; calendar tools без токена → «connect Google first» |
| **Discovery** | `search_tools` с `tags` + `mode=catalog/rank`, tag_hints |
| **Agent** | context collapse: `search_tools` схлопывается после успешного `use_tool` |
| **Tests** | `test_google_calendar.py`, `test_tool_tags.py`, `test_context_collapse.py` |

**Итого:** 23 calendar tools + 3 auth = **26 Google tools**.

### Отложено (делать потом)

| # | Фича | Зачем понадобится | Блокер |
|---|------|-------------------|--------|
| 1 | **`events.watch`** (push/webhooks) | Проактивные уведомления в Telegram («встреча через 15 мин», синк с memory graph) | Публичный HTTPS endpoint, renew подписок ~каждые 7 дней |
| 2 | **ACL / sharing** | Управление доступом к календарям из бота (шаринг по email, права reader/writer) | Редкий кейс; шаринг проще в Google Calendar UI |
| 3 | **Google Meet auto-create** | `create_event` сразу с Meet-ссылкой для онлайн-встреч | `conferenceDataVersion=1` + `conferenceData.createRequest` — небольшая доработка, когда понадобится |

### Не планируем

- Calendar **settings** API (timezone/format недели на уровне аккаунта)
- Sync с внешними календарями
- Multi-user shared bot calendar (каждый user = свой OAuth token — уже так)
