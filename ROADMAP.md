# Hermes Agent — Roadmap

Living document for ideas and next steps **after** the original plan (`PLAN.md`, Phases 0–4).

Add items here as we think of them. Check off when shipped. No need to keep this file perfectly ordered.

---

## Current baseline

- 3 tools: `echo.test`, `exa.web_search`, `exa.web_fetch`
- Discovery: embedding + keyword hybrid via `search_tools`
- Execution: `use_tool` with validation, cache, rate limits, telemetry
- Surface: Telegram bot + local CLI (text, voice, vision in; text rich out)

---

## Ideas backlog

### Rich reply: text + photo blocks in one message

**Status:** planned — not implementing yet.

**Goal:** Bot answer in **one** `sendRichMessage` with alternating blocks:

```
paragraph text
photo (HTTPS URL)
paragraph text
photo (HTTPS URL)
```

Not inline images inside a sentence — Telegram Rich Markdown uses **separate blocks** (`paragraph`, `![](url)` media syntax).

**Why we want it:**

- Long answers with illustrations (diagrams, charts, fetched OG images, generated images)
- Cleaner than multiple bot messages in a row
- Matches native Telegram Rich Messages capability (Bot API 10.1)

**Constraints / design notes:**

- Every photo block needs a **public HTTP/HTTPS URL** — Telegram does not accept local files in rich markdown media syntax
- Options for image URLs:
  - [ ] Host on temporary object storage / CDN after upload
  - [ ] Re-use URLs from Exa/search results when relevant
  - [ ] Image generation tool → upload → get URL
  - [ ] Telegram `file_id` → bot server download → re-upload to public URL (extra step)
- Bot output today is **text-only** via `streaming.py` → `finalize()`; needs a **block composer** (text + media segments)
- Model must return structured reply (JSON or markdown with strict `![](https://...)` blocks), not free-form guess

**Possible design (when we build it):**

```
rich_reply.py          # parse/build multi-block rich markdown
streaming.py           # finalize() accepts blocks or composed markdown
agent/prompts.py       # instruct model how to embed photo URLs in replies
```

**Open questions:**

- [ ] Who provides URLs — only tools, or also user-sent photos echoed back?
- [ ] Max photos per message (Telegram limits ~50 media attachments per rich message)
- [ ] Fallback if URL invalid — skip photo block or send text-only?
- [ ] Keep `<details>` sources block compatible with multi-block layout?

---

### Agent workspace (sandbox filesystem)

**Status:** planned — design only, not implementing yet.

**Problem today:**

- User sends **photo** → in-memory base64 to LLM (vision); no server path, no `file_ref`.
- User sends **document/file** → no handler; bot ignores.
- **Outbound** files work via Google download → ephemeral `RunFileStore` → `telegram.send_file` (UTF-8 BOM + extension fix for mobile).
- Agent cannot create/edit local files, list a folder, or reuse user uploads across turns.

**Goal:** Per-user **sandbox directory** on the server. Agent works **only inside that root** — create/read/write/list/move/delete files and folders. Optional bridge to Telegram send.

**Layout (draft):**

```
data/workspaces/{user_id}/
  uploads/      ← inbound from Telegram (photo, document)
  agent/        ← agent-created files
  exports/      ← optional cache from Drive/Gmail downloads
```

Agent sees **relative paths only** (`agent/report.md`, `uploads/invoice.pdf`). Any `../`, absolute path, or symlink escape → reject.

**Planned tools (draft):**

| Tool | What |
|------|------|
| `workspace.list` | List files/dirs (optional recursive) |
| `workspace.read_file` | Text inline; binary → `file_ref` |
| `workspace.write_file` | Create/overwrite text or bytes |
| `workspace.mkdir` | Create directory |
| `workspace.delete` | File or dir (`confirm=true` for dirs) |
| `workspace.move` | Rename/move within sandbox |
| `workspace.stat` | Size, mime, mtime, `file_ref` if exists |

Reuse **`telegram.send_file`** for delivery (same `file_ref` pattern). Inbound Telegram handler saves to `uploads/` and returns `file_ref` + relative path to agent.

**Security / limits (from `config.py`):**

- [ ] Max workspace size per user (disk quota)
- [ ] Max single file size
- [ ] Max file count
- [ ] Path traversal blocked (`resolve()` under root)
- [ ] Per-user isolation (`user_id` roots)
- [ ] No shell/exec — FS CRUD tools only
- [ ] Optional TTL / `/clear_workspace` / cleanup job

**Open questions:**

- [ ] **Per-user vs per-run workspace?** Per-user = files survive between messages; per-run = safer, simpler.
- [ ] Merge with **RunFileStore** (ephemeral) or separate persistent store?
- [ ] Photo: save to disk **and** keep vision inline, or file-only?
- [ ] Google download → copy into `exports/` when agent needs to edit before send?
- [ ] Allowed extensions / mime whitelist for writes?

**Possible layout (when we build it):**

```
tools/builtins/workspace/
  paths.py           # resolve safe path under user root
  store.py           # read/write/list + file_ref registration
  tools.py           # workspace.* ToolSpecs
bot/inbound_files.py # F.document / F.photo → uploads/
config.py            # WORKSPACE_* limits
```

**Relation to existing pieces:**

- `RunFileStore` — keep for short-lived Google→Telegram pipeline (or unify under workspace later).
- `telegram.send_file` — unchanged; consumes `file_ref` from workspace or run store.
- ROADMAP `file.read` row → superseded by this section.

---

### Per-user message queue (one reply at a time)

**Status:** planned — not implementing yet.

**Problem:** User sends message #1 → bot starts thinking. User sends message #2 while #1 is still running → both hit the agent, history races, duplicate drafts, wasted tokens, confusing UX.

**Desired behavior:**

1. User sends message → bot starts processing (lock per `user_id`).
2. While locked, any **new** user message is **not** sent to the agent immediately.
3. Bot replies briefly: «Обрабатываю предыдущее сообщение…» (or Telegram reaction / short ack — TBD).
4. New messages are **queued** (FIFO per user).
5. When current run finishes → automatically dequeue and process next message.
6. Repeat until queue empty → release lock.

**Possible design (when we build it):**

```
bot/session_lock.py     # asyncio Lock + deque per user_id
bot/chat_service.py     # generate_reply acquires lock / enqueues
main.py                 # handlers call queue API instead of direct generate_reply
```

**Open questions:**

- [ ] Queue cap (e.g. max 5 pending) — drop oldest or reject with «слишком много»?
- [ ] Voice/photo while busy — same queue or separate?
- [ ] `/reset` clears queue + cancels in-flight?
- [ ] Ack style: plain text reply vs `react` emoji vs edit draft?
- [ ] Merge rapid-fire text into one turn if sent within N seconds? (optional)

---

### Google integrations — service shortlist

**Status:** planning — **defining scope before OAuth implementation.**

**Auth model (one login):**

- **User OAuth 2.0** — Calendar, Drive, Gmail, Contacts, Sheets, Tasks (personal data).
- **Project API key + billing** — Maps / Places / Geocoding / Routes (not «войти своим аккаунтом», отдельная настройка в GCP).

**Flow (target):**

1. `/connect_google` → ссылка в браузер → один consent screen.
2. Refresh token сохраняется per `telegram_user_id`.
3. Новый сервис = новый scope bundle → при необходимости re-auth («добавить доступ»).

---

#### Google Calendar — full tool catalog

**Status:** spec ready → implement after OAuth skeleton.

**OAuth scope (full calendar):**

```
https://www.googleapis.com/auth/calendar
```

Covers read/write events + calendars + freebusy. Один scope на весь календарный блок.

**Default calendar ID:** `primary` (можно переопределить в каждом tool).

---

##### A. Calendars (управление календарями)

| Tool | API | Что делает |
|------|-----|------------|
| `google.calendar.list_calendars` | `calendars.list` | Все календари пользователя (primary, рабочий, подписанные) |
| `google.calendar.get_calendar` | `calendars.get` | Метаданные одного календаря: название, timezone, цвет |
| `google.calendar.create_calendar` | `calendars.insert` | Создать новый календарь (secondary) |
| `google.calendar.update_calendar` | `calendars.update` | Полное обновление календаря (название, описание, timezone) |
| `google.calendar.delete_calendar` | `calendars.delete` | Удалить secondary calendar (не primary) |
| `google.calendar.clear_calendar` | `calendars.clear` | Удалить **все события** из календаря (только secondary; требует `confirm: true`) |

---

##### B. Events — чтение и поиск

| Tool | API | Что делает |
|------|-----|------------|
| `google.calendar.list_events` | `events.list` | События за период (`time_min`, `time_max`), фильтр по календарю |
| `google.calendar.get_event` | `events.get` | Одно событие по `event_id` |
| `google.calendar.search_events` | `events.list` + `q` | Текстовый поиск по title/description/location/attendees |
| `google.calendar.list_upcoming` | `events.list` | Sugar: «ближайшие N событий» от now (обёртка над list) |
| `google.calendar.list_today` | `events.list` | Sugar: события на сегодня в timezone пользователя |
| `google.calendar.list_instances` | `events.instances` | Все вхождения recurring-события в диапазоне дат |

**`list_events` ключевые параметры:**

- `calendar_id` (default `primary`)
- `time_min`, `time_max` (ISO 8601)
- `query` — optional text filter
- `max_results` (default 25, cap 250)
- `single_events` (default true — развернуть recurring)
- `order_by` — `startTime` | `updated`
- `show_deleted` — для sync/undo сценариев

---

##### C. Events — создание и изменение

| Tool | API | Что делает |
|------|-----|------------|
| `google.calendar.create_event` | `events.insert` | Новое событие: title, start/end, timezone, description, location, attendees, reminders, recurrence (RRULE), color |
| `google.calendar.quick_add_event` | `events.quickAdd` | Создать из текста: «Обед с Алией завтра в 13:00» |
| `google.calendar.update_event` | `events.update` | Полная замена события (все поля) |
| `google.calendar.patch_event` | `events.patch` | Частичное изменение: только переданные поля (перенос времени, переименование) |
| `google.calendar.delete_event` | `events.delete` | Удалить событие |
| `google.calendar.move_event` | `events.move` | Перенести событие в другой календарь |
| `google.calendar.import_event` | `events.import` | Импорт как private copy (редко; для миграции) |

**`create_event` ключевые параметры:**

- `summary` (title), `description`, `location`
- `start`, `end` — `{datetime, timezone}` или `{date}` для all-day
- `attendees` — `[{email, optional_display_name}]`
- `reminders` — `{use_default}` или `{overrides: [{method, minutes}]}`
- `recurrence` — `["RRULE:FREQ=WEEKLY;BYDAY=MO"]`
- `conference_data` — опционально Google Meet link (если включим позже)
- `send_updates` — `all` | `externalOnly` | `none`

---

##### D. Scheduling (умный ассистент)

| Tool | API | Что делает |
|------|-----|------------|
| `google.calendar.freebusy` | `freebusy.query` | Когда занят/свободен между `time_min` и `time_max` (1+ календарей) |
| `google.calendar.find_free_slots` | local helper | Sugar: свободные слоты длительностью N минут в рабочих часах |

`find_free_slots` — не отдельный Google API, логика поверх `freebusy` + `list_events`; удобно для «найди час для встречи».

---

##### E. Auth & status (не calendar API, но нужны)

| Tool | Что делает |
|------|------------|
| `google.auth.status` | Подключён ли Google, scopes, email аккаунта |
| `google.auth.connect_url` | Ссылка для OAuth (или bot command `/connect_google`) |
| `google.auth.disconnect` | Отозвать токен локально + revoke |

Bot commands (не tools): `/connect_google`, `/disconnect_google`.

---

##### F. Отложено (не в v1 calendar)

| Tool | Почему позже |
|------|--------------|
| `google.calendar.watch_events` | Webhook/push — нужен публичный HTTPS endpoint |
| `google.calendar.list_acl` / `share_calendar` | Sharing ACL — редкий кейс в Telegram |
| `google.calendar.colors` | `list_colors`, `set_calendar_color`, `color_id` on events — **done** |
| `google.calendar.settings` | User settings — почти не нужен агенту |

---

##### Implementation waves (calendar only)

| Wave | Tools | Goal |
|------|-------|------|
| **Cal-1** | `list_calendars`, `list_events`, `list_today`, `list_upcoming`, `get_event`, `search_events`, `freebusy` | Read-only: «что сегодня», поиск, занятость |
| **Cal-2** | `create_event`, `quick_add_event`, `patch_event`, `delete_event` | Daily use: поставить/перенести/убрать |
| **Cal-3** | `update_event`, `move_event`, `list_instances`, `find_free_slots` | Recurring + полный CRUD |
| **Cal-4** | `create_calendar`, `update_calendar`, `delete_calendar`, `clear_calendar`, `import_event` | Power user |

**Total: 22 calendar tools + 3 auth tools.**

---

##### Agent hints (для prompts / tool graph)

```
list_today / list_upcoming  →  patch_event | delete_event
search_events               →  get_event
freebusy / find_free_slots  →  create_event
quick_add_event             →  get_event (verify)
create_event (recurring)    →  list_instances | patch_event | delete_event
```

---

#### Wave 1 — MVP (подключаем первыми)

| # | Сервис | Зачем боту | Tools (draft) | OAuth scopes | Приоритет |
|---|--------|------------|---------------|--------------|-----------|
| 1 | **Google Calendar** | Полный календарь — см. каталог выше (22 tools) | `google.calendar.*` | `calendar` | **P0 — IN PROGRESS (spec)** |
| 2 | **Google Drive (read)** | Найти файл, прочитать Doc/PDF/txt | `google.drive.search`, `google.drive.read`, `google.drive.metadata` | `drive.readonly` | **P0** |

**Wave 1 = минимум для «умного ассистента»:** календарь + документы.

---

#### Wave 2 — расширение файлов и людей

| # | Сервис | Зачем боту | Tools (draft) | OAuth scopes | Приоритет |
|---|--------|------------|---------------|--------------|-----------|
| 3 | **Google Drive (write)** | Сохранить заметку, загрузить экспорт | `google.drive.upload`, `google.drive.mkdir` | `drive.file` (только созданные ботом) или `drive` | **P1** |
| 4 | **Google Contacts** | «найди телефон X», email для приглашений | `google.contacts.search`, `google.contacts.get` | `contacts.readonly` | **P2** |
| 5 | **Google Tasks** | Todo-листы рядом с Calendar | `google.tasks.list`, `google.tasks.create` | `tasks` | **P2** |

---

#### Wave 3 — почта и таблицы

| # | Сервис | Зачем боту | Tools (draft) | OAuth scopes | Приоритет |
|---|--------|------------|---------------|--------------|-----------|
| 6 | **Gmail (read)** | «найди письмо от X», summary inbox | `google.gmail.search`, `google.gmail.read` | `gmail.readonly` | **P2** — restricted scope |
| 7 | **Gmail (send)** | Отправить письмо / ответ | `google.gmail.send`, `google.gmail.draft` | `gmail.send`, `gmail.compose` | **P3** — verification |
| 8 | **Google Sheets** | Прочитать/обновить таблицу | `google.sheets.read`, `google.sheets.update` | `spreadsheets` | **P2** |

**Note:** Gmail в production требует Google OAuth verification (долго). Для личного бота — Testing mode + test users.

---

#### Wave 4 — карты (отдельная модель, не user OAuth)

**Status:** spec ready → see `docs/GOOGLE_MAPS_PLAN.md` (20 tools, Maps-0…Maps-5).

| # | Сервис | Зачем боту | Tools (draft) | Auth | Приоритет |
|---|--------|------------|---------------|------|-----------|
| 9 | **Geocoding** | Адрес → координаты | `google.maps.geocode`, `reverse_geocode` | API key | **P1** |
| 10 | **Places (New)** | «кафе рядом», детали | `places_text_search`, `place_details`, … | API key | **P1** |
| 11 | **Routes API** | Маршрут, ETA | `compute_routes`, `directions` (sugar) | API key | **P1** |
| 12 | **Static Maps** | Картинка карты в Telegram | `google.maps.static_map` | API key | **P2** |

Billing в GCP обязателен. Один API key на проект, не per-user login.

---

#### Отложено / probably skip

| Сервис | Почему не сейчас |
|--------|------------------|
| **YouTube Data API** | Узкий кейс; отдельные квоты |
| **Google Photos** | Restricted scopes, сложный review |
| **Google Docs API (write in-place)** | Проще через Drive export/import на старте |
| **Google Meet** | Создание через Calendar достаточно |
| **Google Keep** | Нет публичного API |
| **Google Fit / Health** | Restricted + мало пользы для чат-бота |

---

#### Scope bundles (для одного consent screen)

```
# Bundle A — MVP (Wave 1, Calendar first)
calendar                    # full read/write — see calendar tool catalog

# Bundle A2 — files (after calendar OAuth works)
drive.readonly

# Bundle B — productivity (+ Wave 2)
+ drive.file          # или drive для полной записи
+ contacts.readonly
+ tasks

# Bundle C — office (+ Wave 3)
+ gmail.readonly
+ spreadsheets

# Bundle D — optional send
+ gmail.send
+ gmail.compose
```

Стартуем с **Bundle A**. Остальное — incremental re-auth по запросу.

---

#### Решения (нужно подтвердить)

- [ ] **Кто подключает Google:** только ты (admin) или любой Telegram user?
- [ ] **Wave 1 OK:** Calendar + Drive read?
- [ ] **Gmail** — нужен или отложить?
- [ ] **Maps** — включаем в тот же проект (API key) или потом?
- [ ] **Drive write:** `drive.file` (безопаснее) или полный `drive`?

---

#### Possible layout (when coding)

```
tools/builtins/google/
  auth.py              # OAuth URL, token refresh, scope bundles
  token_store.py       # telegram_user_id → credentials
oauth_server.py        # FastAPI callback (sidecar or same process)
  calendar_list.py
  calendar_create.py
  drive_search.py
  drive_read.py
  ...
```

**Open questions (unchanged):**

- [ ] Service account (Workspace domain) vs user OAuth? → **user OAuth** для личных данных
- [ ] Rate limits / billing alerts on Maps & Places?
- [ ] Drive: max export size, supported MIME types?

---

### Yandex Music (Index Music MCP + direct tools)

**Status:** planned — not implementing yet.

**Goal:** Agent can search and interact with **Yandex Music** on the user’s account — «найди трек X», «что послушать по настроению», playlists, likes, etc.

**Two layers (as discussed):**

1. **Index Music MCP** — MCP server for music discovery/indexing (semantic search over catalog / user library).
2. **Direct tools** in `tools/builtins/yandex/` — thin wrappers the agent calls via `use_tool` (same meta-tool pattern as Exa).

**Planned tools (draft names):**

| Tool | Idea |
|------|------|
| `yandex.music.search` | Search tracks, albums, artists by query |
| `yandex.music.track_info` | Metadata, lyrics snippet, link |
| `yandex.music.playlist_search` | Find playlists by name/mood |
| `yandex.music.my_playlists` | List user playlists (OAuth) |
| `yandex.music.likes` | Liked tracks / «Мне нравится» |
| `yandex.music.recommend` | Recommendations / «Похожие» |

**Requirements before coding:**

- [ ] User connects **own Yandex account** (OAuth / token — same pattern as Google)
- [ ] Yandex Music API or unofficial client — verify ToS & stability
- [ ] Index Music MCP server config in bot (`mcp.json` or env) when we wire MCP to agent
- [ ] Rate limits — «очень много эндпоинтов», start with read/search only, no autoplay from bot initially
- [ ] Reply format: track links (`music.yandex.ru/…`) in `<details>Источники</details>` or dedicated «🎵» block

**Possible layout:**

```
tools/builtins/yandex/
  auth.py
  music_search.py
  music_playlists.py
mcps/
  index-music/           # MCP server connection (TBD)
```

**Open questions:**

- [ ] MCP only vs direct API only vs both?
- [ ] Playback control from Telegram or search/link only?
- [ ] Single shared account (yours) vs per Telegram user?
- [ ] Embedding index for music metadata (reuse Phase 2 hybrid index)?

---

### Background memory graph (long-term context)

**Status:** planned — vision / research — not implementing yet.

**Goal:** A **background system** watches the Telegram chat with the bot and **gradually builds a memory graph** — not just flat chat history, but structured knowledge: topics, projects, games, places, facts, timelines.

**Example use case:**

- User plays / discusses **«Альтернативный Рейн»** over many sessions.
- Graph stores: last session date, where the story stopped, NPCs, decisions, open threads.
- User writes: «начинаем игру» → bot **immediately** loads context: game = Alt-Rhein, checkpoint, date, unresolved hooks.
- Separate threads: work questions, weather, another game — all linked as nodes, not one blob.

**Core ideas:**

```
Chat messages (stream)
        ↓
Background worker (async, not blocking reply)
        ↓
Extract entities + relations → update graph
        ↓
Optional: ask user clarifying question when link is ambiguous
        ↓
Graph query at reply time → inject relevant subgraph into prompt
```

**Graph model (draft):**

| Node types | Examples |
|------------|----------|
| `session` | chat turn batch, date |
| `topic` / `project` | «Альтернативный Рейн», work, trip |
| `fact` | «last stopped at chapter 3», «user in Tashkent» |
| `person` / `entity` | NPC, colleague |
| `question` | open clarification bot asked |

| Edge types | Examples |
|------------|----------|
| `about` | fact → topic |
| `continues` | session → session (same topic) |
| `contradicts` / `updates` | new fact replaces old |
| `uncertain` | needs user confirmation |

**Behaviors:**

- [ ] **Background ingestion** — after each turn (or batch every N minutes), LLM or smaller model extracts structured updates; no blocking main reply path
- [ ] **Clarifying questions** — when confidence low or merge ambiguous: bot asks «Правильно понимаю, X связано с игрой Y?»; user answer → edge confirmed → graph updated
- [ ] **Explicit vs inferred** — user can say «запомни так»; system marks fact as user-confirmed vs auto-extracted
- [ ] **Recall on trigger** — keywords / intent («начинаем игру», «продолжаем Рейн») → retrieve subgraph + summary for system prompt
- [ ] **Stats & freshness** — last updated, session count per topic, optional dashboard (`/memory` admin?)

**Possible design (when we build it):**

```
memory/
  graph_store.py       # nodes/edges (SQLite, Kuzu, Neo4j-lite, or JSONL — TBD)
  extractor.py         # LLM pass: messages → graph deltas
  worker.py            # background queue from chat events
  recall.py            # query graph for current user + topic
  clarify.py           # generate clarification questions
bot/chat_service.py    # emit events to memory worker; inject recall in agent.run
```

**Integration with existing plans:**

- Complements **tool graph** (tools) vs **memory graph** (user/knowledge) — different layers
- Needs **Phase 4 permissions** if multi-user
- Pairs well with **message queue** (process memory after turn completes)
- `memory.user_note` tool could be front-end to manual graph writes

**Open questions:**

- [ ] Storage: embedded SQLite vs graph DB vs vector + graph hybrid?
- [ ] One graph per Telegram user — required
- [ ] Retention / GDPR: delete node, export graph?
- [ ] Extractor model: same 9router model vs cheap local vs batch nightly?
- [ ] How much to inject into prompt (token budget) vs on-demand tool `memory.recall`?
- [ ] Conflict resolution: user said A yesterday, B today — ask or auto-update?
- [ ] Visualize graph for user in Telegram (Mermaid / canvas)?

**North-star scenario:**

> «Начинаем игру»  
> → Bot: «Альтернативный Рейн — остановились 12 июля у переправы через Рейн, открыт вопрос про шпиона в Бонне. Продолжаем?»

---

### Tool graph + related-tool recommendations

**Status:** idea only — not implementing yet.

**Concept:** Build a graph of tools (nodes = tools, edges = “often used together” or “natural next step”). When the agent runs tool `T`, attach to the tool result (or to `search_tools` hits) a short **recommendation block**: 2–3 neighbor tools from the graph.

Example flow:

1. Agent calls `exa.web_search` → finds URLs.
2. Graph suggests: `exa.web_fetch` (“read full page”), maybe later `summarize.page`, `extract.links`.
3. Model sees optional hint, not a forced call — “you may also use…”.

**Why it’s good:**

- Scales to hundreds of tools without stuffing all schemas into context
- Teaches the model workflows (search → fetch → summarize)
- Complements embedding search (semantic) with structural hints (graph)

**Possible design (when we build it):**

```
tools/
  graph.py           # load edges, get_neighbors(tool_name, k=3)
  graph_edges.yaml   # or .json — hand-curated at first
```

- Edge types: `follows`, `alternative`, `prerequisite`
- Inject neighbors in `use_tool` response: `"related_tools": [...]` with name + one-line description
- Optional: learn edges from telemetry (`by_tool` co-occurrence in same session)

**Open questions:**

- [ ] Curated YAML vs learned from logs vs both?
- [ ] Show related tools on `search_tools` results too?
- [ ] Cap how many hints per turn so the model isn’t spammed?

---

### More tools (wishlist)

Add as separate rows when we pick them up. Suggested naming: `provider.action`.

| Tool | Idea | Priority |
|------|------|----------|
| `exa.web_search` | ✅ done | — |
| `exa.web_fetch` | ✅ done | — |
| `weather.openmeteo` | Weather by city/coords, no key | medium |
| `calc.eval` | Safe math / unit conversion | low |
| `memory.user_note` | Persist a note per user across sessions | medium |
| `file.read` | ~~Read user-uploaded doc~~ → see **Agent workspace** | planned |
| `summarize.text` | Compress long fetch result before LLM context | medium |
| `github.search` | Repos / issues API | later |
| `calendar.ics` | Parse event from URL | later |
| **Google suite** | Drive, Maps, Calendar — see dedicated section above | planned |
| **Yandex Music** | Index Music MCP + search/playlists/likes tools | planned |
| **Memory graph** | Background chat → knowledge graph + recall | planned |

---

### Phase 4 remainder — permissions

**Status:** deferred.

- `ADMIN_USER_IDS` exists for `/stats` only
- Full policy: per-user allowlists by tag or tool name
- Filter `search_tools` results so the model never sees forbidden tools

---

### UX / agent quality

- [ ] Stream final LLM answer token-by-token (today: prefilled word chunking after full reply)
- [x] Cite sources as clickable links after Exa calls (auto `<details>Источники</details>` appendix)
- [ ] Rich multi-block replies: text + photo + text + photo in one message (see above)
- [ ] Per-user message queue — block/queue while bot is busy, process next when done
- [ ] Session-level “tool trace” for user (`/last` — what tools were called)
- [ ] Smarter status lines when graph hints are shown

---

### Infrastructure (only if needed)

- [ ] Redis cache / rate limits (multi-instance bot)
- [ ] Persistent telemetry (SQLite or JSONL)
- [ ] Tool graph editor script from co-occurrence stats

---

## Done log

| Date | Item |
|------|------|
| 2026-07-02 | Phases 0–4 core shipped; see `PLAN.md` status summary |
| 2026-07-02 | Auto sources appendix, vision, voice, gap prefixes, date context |
| 2026-07-02 | `ROADMAP.md` created; tool graph idea captured |

---

## How to use this file

1. New idea → add under **Ideas backlog** or **More tools**.
2. Starting work → move to a short “In progress” section or open a PR.
3. Shipped → check box, add row to **Done log**, update `PLAN.md` if it was plan scope.
