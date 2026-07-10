# Hermes Agent — статус бота

Живая документация: что работает, какие инструменты подключены, известные проблемы.  
Обновляем снизу по мере изменений.

**Итог (2026-07-03):** Google-стек — **Calendar** (23), **Gmail** (45), **Drive** (70), **Maps** (18), **Sheets** (43, complete) + OAuth. Exa, voice, vision, supervisor, context collapse — production.

---

## ✅ Работает

| Функция | Статус | Примечание |
|---------|--------|------------|
| **Rich streaming** | ✅ | Draft API (`sendRichMessageDraft`) + keepalive каждые ~20 с → финальный `sendRichMessage` |
| **Текст** | ✅ | Обычные сообщения, burst-merge нескольких подряд |
| **Голос / аудио** | ✅ | Groq Whisper → транскрипция → агент |
| **Таблицы, форматирование** | ✅ | Telegram Rich Markdown: bold, lists, GFM-таблицы, math |
| **Поиск в интернете (Exa)** | ✅ | `exa.web_search` + `exa.web_fetch` |
| **Поиск инструментов** | ✅ | Embedding-index (Fireworks `qwen3-embedding-8b`) + keyword fallback |
| **Google Calendar** | ✅* | 23 инструмента, OAuth; list/create/patch/delete, freebusy, recurring |
| **Google Gmail** | ✅ | 45/45 tools (Mail-1…5); read/write/drafts/labels/filters/settings |
| **Google Maps** | ✅ | 18 инструментов; маршруты, Yandex transit, inline-кнопки, геолокация |
| **Google Drive** | ✅ | 70 инструментов; search/list, CRUD, permissions, comments, shared drives |
| **Google Sheets** | ✅ | 43/43 — full catalog (validation, charts, filters, protection) |
| **Inline-кнопки (Maps + Gmail)** | ✅ | До 5 URL-кнопок суммарно; 2 в ряд при 3+; URL не в тексте |
| **Vision (фото)** | ✅ | Multimodal in-run; в history только `[image]` placeholder |
| **Agent Supervisor** | ✅ | Soft triggers, CONTINUE/STOP, `/trace_last`, `/stats` |
| **Context collapse** | ✅ | In-run + persist: `search_tools` вырезается, `use_tool` сохраняется |
| **Chat persistence (v2)** | ✅ | SQLite `chat.sqlite`: sessions, message rows, run traces; summary on archive |
| **Telegram геолокация** | ✅ | 📍 pin → отдельный turn агенту с координатами (без автоподмешивания к след. сообщению) |

\* — Calendar: отложенный баг timezone. Sheets: scope `spreadsheets` → re-auth if `sheets_ready=false`.

---

## Google — что сделано (итог)

Один OAuth (`/connect_google`) на Calendar + Gmail + Drive + Sheets. Maps — server-side API key, OAuth не нужен.

| Сервис | Tools | OAuth | Inline-кнопки | Статус |
|--------|-------|-------|---------------|--------|
| **Calendar** | 23 | ✅ shared | — | ✅ полный CRUD, freebusy, recurring, multi-calendar |
| **Gmail** | 45 | ✅ shared | ✅ из финального ответа | ✅ inbox/search/threads/send/reply/drafts/labels/filters/vacation/send-as |
| **Drive** | 70 | ✅ shared | ✅ из финального ответа | ✅ files, permissions, comments, shared drives, export |
| **Sheets** | 43 | ✅ shared | — | ✅ complete: values, structure, format, validation, charts, protection |
| **Maps** | 18 | API key | ✅ из tool results | ✅ routes, places, geocode, static map, Street View, Yandex transit |

**Bot-команды Google:** `/connect_google`, `/google_status`, `/google_callback`, `/disconnect_google` — Calendar + Gmail + Drive + Sheets; `gmail_ready`, `drive_ready`, `sheets_ready` в status.

**Prompts:** workflows calendar, gmail, drive, sheets, maps; Gmail/Drive spreadsheet URLs в финальном ответе (до 5); Maps URL не в тексте — только кнопки.

**Sheets discovery:** `search_tools` tags `["google","sheets"]` + family (`values`, `structure`, `read`, `write`). Flow: `drive.search_files` → `sheets.get_spreadsheet` → `get_values` / `read_sheet` / `update_values`. План: `docs/GOOGLE_SHEETS_PLAN.md`.

---

## Архитектура инструментов

Модель **не видит** все ~92 tools сразу. Она видит только **2 meta-tools**:

| Meta-tool | Назначение |
|-----------|------------|
| **`search_tools`** | Найти нужный инструмент в registry. `mode=rank` — по запросу + embeddings; `mode=catalog` — полный список по tags. |
| **`use_tool`** | Выполнить инструмент по имени + JSON arguments. |

### Flow агента

```
Пользователь → search_tools (найти tool) → use_tool (вызов) → ответ tool → … → финальный ответ
                      ↑ вырезается из history          ↑ сохраняется в history
```

**Persistent history** (между сообщениями и **после рестарта**) в `data/chat.sqlite`:
- `chat_sessions` + `chat_messages` — полный worker slice per turn (`use_tool` JSON, без search_tools)
- `chat_session_traces` — RunTrace + assistant reply per user turn (для session summary)
- Prompt: last `CHAT_MAX_HISTORY` user turns из **active session**; старые turns остаются в DB
- `/reset` / `/start` → archive session + EN summary (async, из traces) + новая active session
- Legacy `chat_history.sqlite` → one-shot migration on startup (`CHAT_MIGRATE_V1_*`)

Подробнее — `docs/CHAT_STORAGE_V2_PLAN.md`, раздел **Context Collapse** ниже.

---

## Context Collapse ✅

**Статус:** полноценно работает (2026-07-03).

**Зачем:** `search_tools` — служебный шаг discovery (найти schema в registry). Для follow-up нужны только **реальные вызовы** (`use_tool` + JSON-ответ). Каталог инструментов в history — лишний шум и трата tokens; плюс создаёт ложное впечатление, что модель «снова искала tools» в прошлых turn'ах.

**Идея:** во время turn модель **может** искать tools; в сохранённом контексте выглядит так, будто она **сразу** вызвала нужный instrument.

### Два слоя

| Слой | Когда | Модуль | Что делает |
|------|-------|--------|------------|
| **In-run** | Внутри одного ответа бота | `agent/context_collapse.py` → `SearchContextCollapser` | После **успешного** `use_tool` помечает последний `search_tools` exchange на удаление; перед следующим LLM-вызовом / в конце turn — вырезает пару `assistant` + `tool` |
| **Persist** | При записи в chat history | `agent/history_persist.py` | `extract_worker_history_for_persist` → `strip_all_search_tools` (все раунды search) + `strip_supervisor_injections` |

Wiring: `agent/loop.py` (`SearchContextCollapser`, `extract_worker_history_for_persist` в `_complete_run`).

### Flow (один turn)

```
user: "маршрут до Chorsu"
  → assistant: search_tools(tags=[google,maps])     ← видит LLM in-run
  → tool: { tools: [...], count: 18 }
  → assistant: use_tool(google.maps.compute_routes)
  → tool: { ok: true, routes: [...] }
  → assistant: "Вот маршрут…"                       ← финал пользователю

В RAM history после turn (что увидит модель в следующем сообщении):

user: "маршрут до Chorsu"
  → assistant: use_tool(google.maps.compute_routes)
  → tool: { ok: true, routes: [...] }
  → assistant: "Вот маршрут…"
```

`search_tools` **нет** — как будто tool был известен сразу.

### Что сохраняется / что нет

| Сохраняется в history | Не сохраняется |
|-----------------------|----------------|
| `user` — запрос | `search_tools` + catalog/rank result |
| `assistant` + `tool` — `use_tool` и полный JSON-ответ | Supervisor review injections (`Supervisor review (…)`) |
| `assistant` — финальный текст (без rich-appendices) | In-run-only промежуточные search до успешного use_tool (схлопываются) |

**RunTrace / supervisor** по-прежнему видят все `search_tools` (логируются **до** collapse, флаг `collapsed_from_context`) — для `/trace_last` и отладки.

### Не путать с «persistent history на диск»

Context collapse = **чистый контекст в prompt** (search_tools не попадает в сохранённый slice).  
**Chat store v2** (2026-07-09): history **переживает рестарт** — SQLite `CHAT_DB_PATH`, см. раздел Flow выше.

### Тесты

- `test_context_collapse.py` — in-run collapse, defer until use_tool ok
- `test_history_persist.py` — persist strip, несколько search-раундов за turn

---

## Registry: все инструменты (~92)

| Группа | Кол-во | Tags |
|--------|--------|------|
| Google OAuth | 3 | `google`, `auth` |
| Google Calendar | 23 | `google`, `calendar` |
| Google Gmail | 45 | `google`, `gmail` |
| Google Maps | 18 | `google`, `maps` |
| Exa | 2 | `web`, `search` / `exa` |
| Echo (dev) | 1 | — |


### Служебные

| Tool | Описание |
|------|----------|
| `echo.test` | Echo для тестов runtime (dev) |

### Google OAuth (3) — tags: `google`, `auth`

| Tool | Описание | Bot-команды |
|------|----------|-------------|
| `google.auth.status` | Проверить Google (Calendar + Gmail scopes, `gmail_ready`) | `/google_status` |
| `google.auth.connect_url` | URL для OAuth-подключения | `/connect_google` |
| `google.auth.disconnect` | Отключить Google | `/disconnect_google` |

> Все `google.calendar.*` и `google.gmail.*` требуют подключённый Google аккаунт с нужными scopes.

---

### Google Calendar (23) — tags: `google`, `calendar`

| Tool | Что делает | Когда использовать |
|------|------------|---------------------|
| `google.calendar.get_calendar` | Метаданные календаря (timezone, название) | Настройки календаря |
| `google.calendar.list_calendars` | Список всех календарей пользователя | Перед move / multi-calendar |
| `google.calendar.list_events` | События в явном диапазоне (`time_min` обязателен) | Конкретный период |
| `google.calendar.list_upcoming` | Ближайшие события (7 дней, 10 шт.) | «Что дальше?» |
| `google.calendar.list_today` | Все события на сегодня | «Что сегодня?» |
| `google.calendar.get_event` | Одно событие по ID | После list/search |
| `google.calendar.search_events` | Поиск по тексту в title/description | Keyword search |
| `google.calendar.list_instances` | Occurrences recurring-события | Повторяющиеся |
| `google.calendar.freebusy` | Busy-блоки (сырые) | Проверка занятости |
| `google.calendar.find_free_slots` | Свободные слоты для встречи | «Когда можем встретиться?» |
| `google.calendar.create_event` | Создать с полным контролем (attendees, recurrence) | Сложные события |
| `google.calendar.quick_add_event` | Создать из natural language | «Обед завтра в 13:00» |
| `google.calendar.patch_event` | Частичное обновление | Изменить одно поле |
| `google.calendar.update_event` | Полная замена (omitted = cleared!) | Полный rewrite |
| `google.calendar.delete_event` | Удалить событие | — |
| `google.calendar.move_event` | Перенести в другой календарь | — |
| `google.calendar.list_colors` | Палитра цветов | Перед set color |
| `google.calendar.set_calendar_color` | Цвет календаря в списке | — |
| `google.calendar.create_calendar` | Новый secondary calendar | — |
| `google.calendar.update_calendar` | Обновить metadata календаря | — |
| `google.calendar.delete_calendar` | Удалить secondary calendar | Primary нельзя |
| `google.calendar.clear_calendar` | Удалить все события (`confirm=true`) | — |
| `google.calendar.import_event` | Import без invitations | Миграция iCal |

**Статус:** ✅ **полноценно работает** (2026-07-03). Подключение через `/connect_google`. Известный баг: timezone при create (см. проблемы).

---

### Google Gmail (45) — tags: `google`, `gmail`

| Категория | Tools | Примеры |
|-----------|-------|---------|
| **Read** | inbox, unread, search, list threads/messages, get message/thread, labels, drafts | `list_inbox`, `search_messages`, `get_thread` |
| **Write** | send, reply, forward, modify, archive, trash, batch | `send_message`, `reply_to_message`, `batch_modify_messages` |
| **Drafts** | CRUD + send | `create_draft`, `update_draft`, `send_draft` |
| **Labels** | list/get/create/update/delete | `create_label`, `batch_modify_messages` |
| **Settings** | filters, vacation, send-as, import | `create_filter`, `update_vacation_settings`, `patch_send_as` |
| **Attachments** | get_attachment (size guard) | после `get_message` |

**OAuth scopes:** `gmail.modify`, `gmail.settings.basic` + calendar scopes; `gmail_ready` в `/google_status`.

**Inline-кнопки (2026-07-03):**
- **Maps:** из tool results + strip из финального текста; labels по tool/travel_mode (На машине, Панorama, …).
- **Gmail:** из tool results (`get_thread`, `search`, send/reply) + финальный текст; label = subject/snippet/«Поиск: …».
- **Drive/Sheets/Docs:** из tool results (`web_view_link`, `url`, `files[]`, `spreadsheet.url`) + финальный текст; smart labels: «Открыть таблицу», filename, «Открыть PDF», …
- URL вырезаются из текста когда есть кнопки; Maps+Gmail ≤5, Drive до 5 отдельными рядами.

**Код:** `agent/gmail_links.py`, `agent/gmail_button_urls.py`, `tools/builtins/google/gmail_urls.py`, `agent/reply_markup.py`.

**Тесты:** `test_google_gmail.py` (19), `test_gmail_links.py`.

---

### Exa — поиск в интернете (2) — tags: `web`, `search` / `web`, `exa`

| Tool | Что делает | Когда |
|------|------------|-------|
| `exa.web_search` | Live web search: title, URL, highlights (не полный текст) | Актуальная инфа, новости, факты |
| `exa.web_fetch` | Fetch полного текста страницы по URL (до ~4000 символов) | После search, когда нужны детали |

**Статус:** ✅ работает. Источники автоматически добавляются в `<details>Источники</details>`.

---

### Google Maps (18) — tags: `google`, `maps`

| Tool | Что делает | Inline-кнопка (если есть URL) |
|------|------------|--------------------------------|
| `google.maps.geocode` | Адрес → координаты | — |
| `google.maps.reverse_geocode` | Координаты → адрес | — |
| `google.maps.geocode_batch` | До 10 адресов за раз | — |
| `google.maps.places_text_search` | Поиск места по тексту (`text_query`) | — |
| `google.maps.places_nearby_search` | Места рядом с координатами | — |
| `google.maps.place_details` | Детали по `place_id` | — |
| `google.maps.place_photo` | URL фото места | **Фото места** |
| `google.maps.places_autocomplete` | Autocomplete | — |
| `google.maps.directions` | Turn-by-turn маршрут | **На машине** / **На ОТ** / … |
| `google.maps.travel_time` | ETA + расстояние | то же |
| `google.maps.compute_routes` | Routes API + polyline | то же |
| `google.maps.compute_route_matrix` | Matrix origins × destinations | — |
| `google.maps.maps_link` | URL на карту без API call | **Открыть на карте** / маршрут |
| `google.maps.static_map` | Static map image URL | **Снимок карты** |
| `google.maps.street_view_metadata` | Есть ли Street View | — |
| `google.maps.street_view_image` | Street View panorama URL | **Панорама** |
| `google.maps.timezone` | Timezone + UTC offset | — |
| `google.maps.elevation` | Высота над уровнем моря | — |

**Статус:** ✅ **полноценно работает** (2026-07-03).

**Transit (TRANSIT) в Tashkent/UZ:**
- Google Routes часто возвращает `count=0` — это норма для региона.
- Код автоматически: overlay в tool result (`route_complete`, `count=1`, hint), Yandex URL через geocode (`rtext=lat,lng~lat,lng`), inline-кнопка «На общественном транспорте».
- После успешного TRANSIT `exa.web_search` блокируется (guard) — модель не ищет автобусы в интернете.
- `MAPS_TRANSIT_LINK_PROVIDER=yandex` (default) в `.env`.

**Inline-кнопки (2026-07-03):**
- Map/media URL из **tool results** → `MapsLinkCollector` → `reply_markup`, не в текст.
- Из текста ответа URL вырезаются (`strip_maps_button_urls`).
- Подписи кнопок на русском («На машине», «На общественном транспорте», «Снимок карты», …).
- Layout: 1–2 кнопки — по одной в ряд; **3+ — по 2 в ряд** (`agent/inline_button_layout.py`).
- Суммарный cap с Gmail: **≤5 URL-кнопок** на одно сообщение.

**Telegram геолокация:**
- Пользователь шлёт 📍 → агент получает turn: «Пользователь отправил геолокацию… Координаты: lat, lng».
- Координаты **не** подмешиваются автоматически к следующему тексту — модель сама решает по history.

OAuth **не нужен** — server-side API key.

---

## Конфиг (ключевое)

| Env | Default | Назначение |
|-----|---------|------------|
| `OPENAI_MODEL` | `ag/gemini-3.5-flash-low` | LLM через 9router |
| `REASONING_EFFORT` | `high` | Reasoning mode |
| `BOT_TIMEZONE` | `Asia/Tashkent` | «Сегодня» в system prompt |
| `CHAT_MAX_HISTORY` | `50` | User turns in active-session prompt |
| `CHAT_DB_PATH` | `data/chat.sqlite` | Persistent chat (sessions + messages + traces) |
| `CHAT_MIGRATE_V1_ON_STARTUP` | `1` | Auto-import legacy `chat_history.sqlite` once |
| `MAPS_TRANSIT_LINK_PROVIDER` | `yandex` | Transit-кнопка: Yandex (default) или Google |
| `GOOGLE_MAPS_DEFAULT_REGION` | `uz` | Bias для geocode/places |
| `DRAFT_KEEPALIVE_INTERVAL` | `20` | Re-push draft каждые N сек (TTL Telegram ~30 с) |
| `GOOGLE_OAUTH_SCOPES` | calendar + gmail | OAuth scopes в `.env` |
| `AGENT_SUPERVISOR_ENABLED` | `1` | Supervisor on/off |

---

## ⚠️ Известные проблемы

### 1. Timezone — календарь (TODO)

**Проблема:** бот запущен на компьютере с **немецким системным временем**. Когда пользователь говорит «10:00 утра по немецкому времени» и создаёт событие — время может перепутаться с `BOT_TIMEZONE=Asia/Tashkent`.

**Нужно:** явно передавать timezone в create/patch или спрашивать у пользователя; не полагаться на системное время машины.

**Статус:** 🔴 отложено, исправить позже.

### 2. Google Maps Routes API — ✅ исправлено 2026-07-03

**Было:** 404 на `directions/v2/computeRoutes` (неверный URL).  
**Сейчас:** Routes API работает; `directions`, `travel_time`, `compute_routes` — OK.

### 3. History — ✅ SQLite v2 (2026-07-09)

**Было:** только RAM, терялось на рестарте.  
**Сейчас:** `data/chat.sqlite` — sessions, messages, traces; auto-migrate from `chat_history.sqlite` on first start.

**Ограничения:** summary только для sessions с traces (не для v1-migrated без новых turns). Agent tools: `chat.search`, `chat.turns.read`, `chat.session.summary`, `chat.sessions.list`.

### 4. Дубликаты процессов

Нельзя запускать `main.py` из venv **и** anaconda одновременно → `TelegramConflictError` + разная history.

### 5. Maps — несколько маршрутов → одна кнопка (TODO)

**Проблема:** если агент строит **несколько маршрутов** за один ответ (например, 3× DRIVE до разных точек), в inline-кнопках внизу остаётся **только последний**, первые два пропадают.

**Причина:** dedupe в `MapsLinkCollector` / `group_key_for_button_url` группирует маршруты по **travel_mode** (`route:DRIVE`, `route:TRANSIT`, …), а не по полной ссылке. Все DRIVE-маршруты получают один `group_key` → при добавлении нового предыдущие с тем же mode **заменяются**.

**Код:** `agent/maps_button_urls.py` → `group_key_for_button_url()`; `agent/maps_links.py` → `MapsLinkCollector.add()`.

**Нужно (fix позже):**
- dedupe только если ссылка **полностью совпадает** (origin + destination + mode + provider), т.е. один и тот же URL;
- если 3 маршрута с **разными** точками (разный `origin`/`destination`/`rtext`) — **3 отдельные кнопки** внизу;
- одинаковый mode (DRIVE/DRIVE/DRIVE) **не** повод схлопывать, если URL разные.

**Статус:** 🟡 отложено, исправить позже.

---

### 6. Draft TTL / длинные runs — ✅ исправлено 2026-07-03

**Было:** draft «Сейчас: …» пропадал каждые ~30 с на длинных agent runs (LLM думает без status update).  
**Сейчас:** фоновый **draft keepalive** (`streaming.py`) — re-push того же draft каждые ~20 с; без обычных сообщений/edit.

---

## Changelog (снизу вверх)

| Дата | Изменение |
|------|-----------|
| **2026-07-09** | **Chat storage v2:** `chat.sqlite` (sessions/messages/traces), summary on archive, v1 migration; removed `history_store.py` |
| **2026-07-03 19:00** | **Sheets-4 complete:** 11 tools — validation, conditional format, filters, charts, protection; **43/43**; registry 202 Google tools |
| **2026-07-03 18:55** | **Sheets-3:** 12 format/data tools; registry 191 Google tools |
| **2026-07-03 18:45** | **Sheets-2:** 9 structure tools (tabs, dimensions, copy/move); registry 179 Google tools |
| **2026-07-03 18:30** | **Sheets-1:** 11 tools (metadata + values + `read_sheet`); registry 170 Google tools; tests; plan wave 1 ✅ |
| **2026-07-03 13:51** | **BOT_STATUS:** итог Google Calendar + Gmail + Maps; registry ~92 tools |
| **2026-07-03 ~13:50** | **Gmail buttons:** только из финального ответа (не из tool JSON); промпт обновлён |
| **2026-07-03 ~13:35** | **Inline cap:** maps+gmail ≤5 кнопок; Gmail не сыпет кнопки из search/list |
| **2026-07-03 ~13:30** | **Draft keepalive:** фоновый re-push draft каждые 20 с — нет мигания на long runs |
| **2026-07-03 ~13:15** | **Gmail inline buttons** (Mail-UX): `GmailLinkCollector`, strip URLs, paired layout 2/row |
| **2026-07-03 ~13:08** | **Gmail complete:** get_label (Mail-2 tail) → 45/45 tools |
| **2026-07-03 ~13:05** | **Gmail Mail-5:** patch_send_as, import_message (2 new, 44 total) |
| **2026-07-03 ~13:00** | **Gmail Mail-4:** filters, vacation, send-as, permanent delete (10 new, 42 total) |
| **2026-07-03 ~12:52** | **Gmail OAuth fix:** `.env` scopes + calendar+Gmail consent |
| **2026-07-03 ~12:50** | **Gmail Mail-3:** drafts CRUD, get_attachment, batch_modify, forward, label CRUD (12 new, 32 total) |
| **2026-07-03 ~12:45** | **Gmail Mail-2:** threads, modify/mark/archive/trash, send/reply (13 new tools, 20 total) |
| **2026-07-03 ~12:40** | **Gmail Mail-1:** 7 read tools, OAuth scopes, gmail_ready, serialize, tags |
| **2026-07-03 ~12:35** | **Known issue:** несколько map-маршрутов → одна inline-кнопка (dedupe по travel_mode, не по полному URL) |
| **2026-07-03 ~12:10** | **Context Collapse** — полный раздел в doc: in-run + persist, пример before/after, RunTrace vs history |
| **2026-07-03 ~12:05** | **Maps — финал:** inline-кнопки для всех map URL (маршруты, Yandex transit, снимок карты, панорама, фото места); labels RU; strip URL из текста; Yandex transit geocode; transit guard (no Exa после TRANSIT); Telegram 📍 геолокация; `search_tools` query = описание tool, не вопрос юзера |
| 2026-07-03 ~09:56 | Maps: Yandex transit overlay, `route_complete`, Exa guard, button labels, Yandex URL strip |
| 2026-07-03 ~09:24 | Yandex `rtext` через geocode (lat,lng), не текстовые адреса |
| 2026-07-03 | Inline keyboard для маршрутов (fix `&amp;`); MapsLinkCollector; Yandex transit default |
| 2026-07-03 | Persistent history: сохраняем `use_tool` + tool results, вырезаем все `search_tools` |
| 2026-07-03 | Fix coerce `use_tool` (nested args, `str(None)` bug) |
| 2026-07-03 | Maps links auto-append, URL `&amp;` fix |
| 2026-07-03 | Agent Supervisor S-3 polish (`/trace_last`, telemetry) |
| 2026-07-02 | Exa, Calendar, Maps tools; embedding search; voice/vision |

---

*Последнее обновление: **9 июля 2026** (UTC+5)*
