# Google Gmail — план интеграции

Полный каталог tools, волны реализации, расширение OAuth и технические детали.  
Файл для ревью перед кодом. **Не MVP** — целевой scope «готов к продаже»: агент управляет почтой через Gmail API v1 так же полно, как сейчас календарём.

---

## 1. Цель

Telegram-бот (Hermes Agent) получает **полный доступ к Gmail** пользователя через **тот же Google OAuth 2.0**, что и Calendar.

Агент вызывает tools через существний flow: `search_tools` → `use_tool`.  
**Tool graph не используется** — gmail tools регистрируются в общем registry с тегами.

```json
{"mode": "catalog", "tags": ["google", "gmail"]}
{"mode": "rank", "query": "find email from bank", "tags": ["google", "gmail", "read"]}
```

Пользователь может:

- читать inbox / unread / поиск (Gmail query syntax)
- открывать письма, треды, вложения (с truncate для LLM)
- отвечать, пересылать, отправлять новые письма
- работать с черновиками
- менять labels (прочитано, архив, звёздочка, свои ярлыки)
- trash / untrash; permanent delete — только с guard
- фильтры, автоответ (vacation), send-as aliases
- batch-операции над несколькими письмами

---

## 2. Auth — расширение существующего OAuth

Сейчас: только Calendar scope → `google.calendar.*` работает, Gmail API недоступен.

### 2.1 Целевые OAuth scopes

| Scope | Зачем |
|-------|-------|
| `https://www.googleapis.com/auth/calendar` | уже есть — Calendar |
| `https://www.googleapis.com/auth/gmail.modify` | read + compose + send + labels + trash (без bypass trash) |
| `https://www.googleapis.com/auth/gmail.settings.basic` | filters, forwarding, vacation, IMAP/POP settings |

**Не используем по умолчанию** (опционально позже):

| Scope | Зачем |
|-------|-------|
| `https://mail.google.com/` | permanent delete без trash — только если явно включим + `confirm=true` guard |
| `https://www.googleapis.com/auth/gmail.readonly` | слишком узкий для «полного» агента |
| `gmail.metadata` | только headers — не подходит для чтения body |

**Env (comma-separated):**

```env
GOOGLE_OAUTH_SCOPES=https://www.googleapis.com/auth/calendar,https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/gmail.settings.basic
```

→ `config.py`, `.env.example`, `DEFAULT_GOOGLE_OAUTH_SCOPES`

### 2.2 Re-consent для существующих пользователей

Токен в SQLite хранит `scopes`. После добавления Gmail:

- старый refresh token **не** содержит gmail scopes → Gmail tools возвращают `{ok: false, error: "Gmail scope missing — run /connect_google again"}`
- `/connect_google` с `prompt=consent` (уже так) → новый consent screen с Calendar + Gmail
- `google.auth.status` показывает `scopes[]` и флаг `gmail_ready: true/false`

### 2.3 Bot commands (без изменений имён)

| Command | Действие |
|---------|----------|
| `/connect_google` | OAuth (Calendar **+ Gmail** scopes) |
| `/disconnect_google` | Revoke + delete token |
| `/google_status` | connected, email, scopes, gmail_ready |

Текст `/connect_google` обновить: «Google Calendar и Gmail».

### 2.4 Auth tools (3) — без изменений имён

| Tool | Изменение |
|------|-----------|
| `google.auth.status` | + `gmail_ready`, полный список scopes |
| `google.auth.connect_url` | тот же URL, больше scopes |
| `google.auth.disconnect` | без изменений |

### 2.5 Инфраструктура (расширение)

```
tools/builtins/google/
  auth.py                    # + build_gmail_service(), get_gmail_service()
  token_store.py             # без изменений схемы (scopes уже есть)
  gmail_client.py            # async wrapper, userId=me
  gmail_serialize.py         # Message/Thread → compact dict для LLM
  gmail_messages.py          # handlers read/write messages
  gmail_threads.py
  gmail_drafts.py
  gmail_labels.py
  gmail_send.py              # RFC2822 build, reply/forward helpers
  gmail_settings.py          # filters, vacation, send-as
  gmail_tools.py             # ToolSpec registrations
```

**GCP:** в том же проекте включить **Gmail API** (Google Cloud Console → APIs & Services).

**OAuth consent screen:** добавить scopes Gmail. Для личного бота — **Testing mode** + test users (как Calendar). Production verification — отдельный длинный процесс (см. §11).

---

## 3. Схема тегов

| Tag | Когда |
|-----|-------|
| `google` | **Все** Google tools |
| `gmail` | **Все** `google.gmail.*` |
| `read` | list, get, search |
| `write` | send, modify, create, delete |
| `labels` | label CRUD + modify labels on messages |
| `drafts` | draft tools |
| `settings` | filters, vacation, send-as |
| `auth` | OAuth tools |

**Фильтр:** `tags=["google", "gmail"]` → только Gmail (AND).

---

## 4. Окончательный каталог tools — **45 штук**

Naming: `google.gmail.<action>`  
Default `user_id`: `"me"` (authenticated user) — **не** передаётся моделью, подставляется в handler.

---

### 4.1 Profile (1)

#### `google.gmail.get_profile`

| | |
|---|---|
| **API** | `users.getProfile` |
| **Описание** | Email, messagesTotal, threadsTotal, historyId |
| **Returns** | `{email, messages_total, threads_total, history_id}` |
| **Wave** | Mail-1 |

---

### 4.2 Labels (5)

#### `google.gmail.list_labels`

| | |
|---|---|
| **API** | `users.labels.list` |
| **Returns** | `{count, labels: [{id, name, type, messages_total, messages_unread}]}` |
| **Wave** | Mail-1 |

#### `google.gmail.get_label`

| | |
|---|---|
| **API** | `users.labels.get` |
| **Параметры** | `label_id` (required) — id или системное имя `INBOX`, `UNREAD`, … |
| **Wave** | Mail-2 |

#### `google.gmail.create_label`

| | |
|---|---|
| **API** | `users.labels.create` |
| **Параметры** | `name` (required), `label_list_visibility`, `message_list_visibility` |
| **Wave** | Mail-3 |

#### `google.gmail.update_label`

| | |
|---|---|
| **API** | `users.labels.update` |
| **Параметры** | `label_id`, `name`, visibility fields |
| **Wave** | Mail-3 |

#### `google.gmail.delete_label`

| | |
|---|---|
| **API** | `users.labels.delete` |
| **Guard** | нельзя удалить system labels |
| **Wave** | Mail-3 |

---

### 4.3 Messages — чтение (6)

#### `google.gmail.search_messages`

| | |
|---|---|
| **API** | `users.messages.list` + `q` |
| **Описание** | Поиск Gmail query syntax (`from:`, `subject:`, `is:unread`, `after:2026/01/01`, …) |
| **Параметры** | `q`, `max_results` (default 10, max 50), `page_token`, `include_spam_trash` (default false) |
| **Returns** | `{count, messages: [{id, thread_id, snippet, label_ids, internal_date}]}` — **без body** |
| **Wave** | Mail-1 |
| **Note** | Основной tool для «найди письмо от X» |

#### `google.gmail.list_messages`

| | |
|---|---|
| **API** | `users.messages.list` |
| **Параметры** | `label_ids` (e.g. `["INBOX"]`), `max_results`, `page_token` |
| **Wave** | Mail-1 |

#### `google.gmail.get_message`

| | |
|---|---|
| **API** | `users.messages.get` |
| **Параметры** | `message_id` (required), `format` — `full` \| `metadata` \| `minimal` (default `full`) |
| **Returns** | compact: headers (from, to, cc, subject, date), `body_text`, `body_html` (truncated), `attachments: [{id, filename, mime_type, size}]`, `label_ids`, `thread_id`, `snippet` |
| **Wave** | Mail-1 |
| **Note** | Body truncate default **4000** chars text; HTML strip или plain fallback |

#### `google.gmail.get_attachment`

| | |
|---|---|
| **API** | `users.messages.attachments.get` |
| **Параметры** | `message_id`, `attachment_id` |
| **Returns** | `{filename, mime_type, size, data_base64}` или `{ok: false, error: "too large"}` если > N MB |
| **Wave** | Mail-3 |
| **Guard** | max size config `GMAIL_MAX_ATTACHMENT_BYTES` |

#### `google.gmail.list_inbox`

| | |
|---|---|
| **API** | Sugar → `list` с `labelIds=INBOX` |
| **Описание** | Последние письма во входящих |
| **Параметры** | `max_results` (default 10) |
| **Wave** | Mail-1 |

#### `google.gmail.list_unread`

| | |
|---|---|
| **API** | Sugar → `list` с `q=is:unread` |
| **Wave** | Mail-1 |

---

### 4.4 Threads (2)

#### `google.gmail.list_threads`

| | |
|---|---|
| **API** | `users.threads.list` |
| **Параметры** | `q`, `label_ids`, `max_results`, `page_token` |
| **Returns** | `{count, threads: [{id, snippet, history_id}]}` |
| **Wave** | Mail-2 |

#### `google.gmail.get_thread`

| | |
|---|---|
| **API** | `users.threads.get` |
| **Параметры** | `thread_id`, `format` |
| **Returns** | `{id, messages: [compact message, ...]}` — каждое сообщение через serialize (truncate) |
| **Wave** | Mail-2 |

---

### 4.5 Messages — labels / state (9)

#### `google.gmail.modify_message`

| | |
|---|---|
| **API** | `users.messages.modify` |
| **Параметры** | `message_id`, `add_label_ids[]`, `remove_label_ids[]` |
| **Wave** | Mail-2 |

#### `google.gmail.modify_thread`

| | |
|---|---|
| **API** | `users.threads.modify` |
| **Параметры** | `thread_id`, `add_label_ids[]`, `remove_label_ids[]` |
| **Wave** | Mail-2 |

#### `google.gmail.batch_modify_messages`

| | |
|---|---|
| **API** | `users.messages.batchModify` |
| **Параметры** | `message_ids[]` (max 1000), `add_label_ids`, `remove_label_ids` |
| **Wave** | Mail-3 |

#### `google.gmail.mark_read`

| | |
|---|---|
| **API** | Sugar → modify, remove `UNREAD` |
| **Параметры** | `message_id` или `thread_id` (one of) |
| **Wave** | Mail-2 |

#### `google.gmail.mark_unread`

| | |
|---|---|
| **API** | Sugar → modify, add `UNREAD` |
| **Wave** | Mail-2 |

#### `google.gmail.archive_message`

| | |
|---|---|
| **API** | Sugar → remove `INBOX` |
| **Параметры** | `message_id` или `thread_id` |
| **Wave** | Mail-2 |

#### `google.gmail.trash_message`

| | |
|---|---|
| **API** | `users.messages.trash` |
| **Wave** | Mail-2 |

#### `google.gmail.untrash_message`

| | |
|---|---|
| **API** | `users.messages.untrash` |
| **Wave** | Mail-2 |

#### `google.gmail.trash_thread` / `google.gmail.untrash_thread`

| | |
|---|---|
| **API** | `users.threads.trash` / `untrash` |
| **Wave** | Mail-2 |

---

### 4.6 Messages — удаление (2)

#### `google.gmail.delete_message`

| | |
|---|---|
| **API** | `users.messages.delete` — **permanent** |
| **Параметры** | `message_id`, `confirm` (required `true`) |
| **Wave** | Mail-4 |
| **Guard** | `confirm=true`; scope `mail.google.com` **или** только если API позволяет с gmail.modify (delete = permanent in API) |
| **Note** | Gmail API `messages.delete` permanently deletes — всегда требовать confirm + предупреждение в tool description |

#### `google.gmail.batch_delete_messages`

| | |
|---|---|
| **API** | `users.messages.batchDelete` |
| **Параметры** | `message_ids[]`, `confirm=true` |
| **Wave** | Mail-4 |

---

### 4.7 Send & reply (3)

#### `google.gmail.send_message`

| | |
|---|---|
| **API** | `users.messages.send` |
| **Параметры** | `to[]` (required), `subject`, `body_text` и/или `body_html`, `cc[]`, `bcc[]`, `from_send_as` (optional alias email) |
| **Returns** | `{sent: true, message_id, thread_id}` |
| **Wave** | Mail-2 |
| **Note** | Handler собирает RFC 2822 → base64url raw |

#### `google.gmail.reply_to_message`

| | |
|---|---|
| **API** | `messages.send` + headers `In-Reply-To`, `References`, `threadId` |
| **Параметры** | `message_id` (required), `body_text`/`body_html`, `reply_all` (default false) |
| **Wave** | Mail-2 |

#### `google.gmail.forward_message`

| | |
|---|---|
| **API** | `messages.send` |
| **Параметры** | `message_id`, `to[]`, optional `body_text` prefix |
| **Wave** | Mail-3 |

---

### 4.8 Drafts (6)

#### `google.gmail.list_drafts`

| | |
|---|---|
| **API** | `users.drafts.list` |
| **Wave** | Mail-3 |

#### `google.gmail.get_draft`

| | |
|---|---|
| **API** | `users.drafts.get` |
| **Wave** | Mail-3 |

#### `google.gmail.create_draft`

| | |
|---|---|
| **API** | `users.drafts.create` |
| **Параметры** | same as send_message fields |
| **Wave** | Mail-3 |

#### `google.gmail.update_draft`

| | |
|---|---|
| **API** | `users.drafts.update` |
| **Параметры** | `draft_id` + message fields |
| **Wave** | Mail-3 |

#### `google.gmail.delete_draft`

| | |
|---|---|
| **API** | `users.drafts.delete` |
| **Wave** | Mail-3 |

#### `google.gmail.send_draft`

| | |
|---|---|
| **API** | `users.drafts.send` |
| **Параметры** | `draft_id` |
| **Wave** | Mail-3 |

---

### 4.9 Settings (9)

#### `google.gmail.list_filters`

| | |
|---|---|
| **API** | `users.settings.filters.list` |
| **Wave** | Mail-4 |

#### `google.gmail.get_filter`

| | |
|---|---|
| **API** | `users.settings.filters.get` |
| **Wave** | Mail-4 |

#### `google.gmail.create_filter`

| | |
|---|---|
| **API** | `users.settings.filters.create` |
| **Параметры** | `criteria` (from, to, subject, query, …), `action` (addLabelIds, removeLabelIds, forward) |
| **Wave** | Mail-4 |

#### `google.gmail.delete_filter`

| | |
|---|---|
| **API** | `users.settings.filters.delete` |
| **Wave** | Mail-4 |

#### `google.gmail.get_vacation_settings`

| | |
|---|---|
| **API** | `users.settings.vacation.get` |
| **Wave** | Mail-4 |

#### `google.gmail.update_vacation_settings`

| | |
|---|---|
| **API** | `users.settings.vacation.update` |
| **Параметры** | `enable`, `response_subject`, `response_body_html`, `start_time`, `end_time`, … |
| **Wave** | Mail-4 |

#### `google.gmail.list_send_as`

| | |
|---|---|
| **API** | `users.settings.sendAs.list` |
| **Wave** | Mail-4 |

#### `google.gmail.get_send_as`

| | |
|---|---|
| **API** | `users.settings.sendAs.get` |
| **Wave** | Mail-4 |

#### `google.gmail.patch_send_as`

| | |
|---|---|
| **API** | `users.settings.sendAs.patch` |
| **Параметры** | `send_as_email`, display fields |
| **Wave** | Mail-5 |

---

### 4.10 Import (1) — редкий

#### `google.gmail.import_message`

| | |
|---|---|
| **API** | `users.messages.import` |
| **Параметры** | raw RFC2822 или structured fields, `label_ids`, `never_mark_spam` |
| **Wave** | Mail-5 |

---

## 5. Сводная таблица (все 45 tools)

| # | Tool | Wave | R/W | Tags | Gmail API |
|---|------|------|-----|------|-----------|
| 1 | `google.gmail.get_profile` | Mail-1 | R | gmail, read | users.getProfile |
| 2 | `google.gmail.list_labels` | Mail-1 | R | gmail, labels, read | labels.list |
| 3 | `google.gmail.search_messages` | Mail-1 | R | gmail, read | messages.list?q= |
| 4 | `google.gmail.list_messages` | Mail-1 | R | gmail, read | messages.list |
| 5 | `google.gmail.get_message` | Mail-1 | R | gmail, read | messages.get |
| 6 | `google.gmail.list_inbox` | Mail-1 | R | gmail, read | sugar |
| 7 | `google.gmail.list_unread` | Mail-1 | R | gmail, read | sugar |
| 8 | `google.gmail.list_threads` | Mail-2 | R | gmail, read | threads.list |
| 9 | `google.gmail.get_thread` | Mail-2 | R | gmail, read | threads.get |
| 10 | `google.gmail.get_label` | Mail-2 | R | gmail, labels, read | labels.get |
| 11 | `google.gmail.modify_message` | Mail-2 | W | gmail, labels, write | messages.modify |
| 12 | `google.gmail.modify_thread` | Mail-2 | W | gmail, labels, write | threads.modify |
| 13 | `google.gmail.mark_read` | Mail-2 | W | gmail, write | sugar |
| 14 | `google.gmail.mark_unread` | Mail-2 | W | gmail, write | sugar |
| 15 | `google.gmail.archive_message` | Mail-2 | W | gmail, write | sugar |
| 16 | `google.gmail.trash_message` | Mail-2 | W | gmail, write | messages.trash |
| 17 | `google.gmail.untrash_message` | Mail-2 | W | gmail, write | messages.untrash |
| 18 | `google.gmail.trash_thread` | Mail-2 | W | gmail, write | threads.trash |
| 19 | `google.gmail.untrash_thread` | Mail-2 | W | gmail, write | threads.untrash |
| 20 | `google.gmail.send_message` | Mail-2 | W | gmail, write | messages.send |
| 21 | `google.gmail.reply_to_message` | Mail-2 | W | gmail, write | messages.send |
| 22 | `google.gmail.create_label` | Mail-3 | W | gmail, labels, write | labels.create |
| 23 | `google.gmail.update_label` | Mail-3 | W | gmail, labels, write | labels.update |
| 24 | `google.gmail.delete_label` | Mail-3 | W | gmail, labels, write | labels.delete |
| 25 | `google.gmail.get_attachment` | Mail-3 | R | gmail, read | attachments.get |
| 26 | `google.gmail.batch_modify_messages` | Mail-3 | W | gmail, write | messages.batchModify |
| 27 | `google.gmail.forward_message` | Mail-3 | W | gmail, write | messages.send |
| 28 | `google.gmail.list_drafts` | Mail-3 | R | gmail, drafts, read | drafts.list |
| 29 | `google.gmail.get_draft` | Mail-3 | R | gmail, drafts, read | drafts.get |
| 30 | `google.gmail.create_draft` | Mail-3 | W | gmail, drafts, write | drafts.create |
| 31 | `google.gmail.update_draft` | Mail-3 | W | gmail, drafts, write | drafts.update |
| 32 | `google.gmail.delete_draft` | Mail-3 | W | gmail, drafts, write | drafts.delete |
| 33 | `google.gmail.send_draft` | Mail-3 | W | gmail, drafts, write | drafts.send |
| 34 | `google.gmail.delete_message` | Mail-4 | W | gmail, write | messages.delete |
| 35 | `google.gmail.batch_delete_messages` | Mail-4 | W | gmail, write | messages.batchDelete |
| 36 | `google.gmail.list_filters` | Mail-4 | R | gmail, settings, read | filters.list |
| 37 | `google.gmail.get_filter` | Mail-4 | R | gmail, settings, read | filters.get |
| 38 | `google.gmail.create_filter` | Mail-4 | W | gmail, settings, write | filters.create |
| 39 | `google.gmail.delete_filter` | Mail-4 | W | gmail, settings, write | filters.delete |
| 40 | `google.gmail.get_vacation_settings` | Mail-4 | R | gmail, settings, read | vacation.get |
| 41 | `google.gmail.update_vacation_settings` | Mail-4 | W | gmail, settings, write | vacation.update |
| 42 | `google.gmail.list_send_as` | Mail-4 | R | gmail, settings, read | sendAs.list |
| 43 | `google.gmail.get_send_as` | Mail-4 | R | gmail, settings, read | sendAs.get |
| 44 | `google.gmail.patch_send_as` | Mail-5 | W | gmail, settings, write | sendAs.patch |
| 45 | `google.gmail.import_message` | Mail-5 | W | gmail, write | messages.import |

---

## 6. Волны реализации

### Mail-1 — Read core (7 tools + auth)

1. OAuth scopes + `get_gmail_service` + GCP Gmail API enable
2. `gmail_serialize.py` (compact message)
3. Tools: `get_profile`, `list_labels`, `search_messages`, `list_messages`, `get_message`, `list_inbox`, `list_unread`
4. Tests + `test_google_gmail.py` smoke
5. `google.auth.status` → `gmail_ready`

**Deliverable:** «покажи inbox», «найди письмо от X», «прочитай письмо».

---

### Mail-2 — Threads + actions + send (12 tools)

1. `list_threads`, `get_thread`
2. `modify_*`, `mark_read/unread`, `archive`, trash/untrash message+thread
3. `send_message`, `reply_to_message`
4. Agent prompt block для Gmail

**Deliverable:** ответить на письмо, архивировать, прочитать тред.

---

### Mail-3 — Drafts + batch + attachments + labels CRUD (12 tools)

1. Full drafts cycle
2. `batch_modify_messages`, `forward_message`, `get_attachment`
3. `create/update/delete_label`

**Deliverable:** черновики, вложения, свои ярлыки.

---

### Mail-4 — Settings + permanent delete (11 tools)

1. Filters CRUD
2. Vacation get/update
3. send-as list/get
4. `delete_message`, `batch_delete_messages` с `confirm=true`

**Deliverable:** автоответ, фильтры, осторожное удаление.

---

### Mail-5 — Advanced (2 tools)

1. `patch_send_as`
2. `import_message`

**Deliverable:** edge cases, миграция.

---

## 7. Технические детали

### 7.1 Serialize для LLM

```python
# gmail_serialize.py — принцип как calendar compact_event
{
  "id": "...",
  "thread_id": "...",
  "from": "...",
  "to": ["..."],
  "subject": "...",
  "date": "2026-07-03T10:00:00Z",
  "snippet": "...",
  "body_text": "...(truncated)",
  "label_ids": ["INBOX", "UNREAD"],
  "attachments": [{"id", "filename", "mime_type", "size"}],
}
```

- HTML body → optional strip tags → text fallback
- `GMAIL_MAX_BODY_CHARS` default 4000
- Не отдавать raw base64 full message в tool result

### 7.2 RFC 2822 send helper

```python
# gmail_send.py
build_raw_message(to, subject, body_text, cc, bcc, in_reply_to, references, thread_id)
→ base64url encoded raw for API
```

### 7.3 Errors

| Error | Когда |
|-------|-------|
| `GoogleNotConnectedError` | нет token |
| `GmailScopeMissingError` | token без gmail scopes |
| `GmailNotConfiguredError` | Gmail API disabled in GCP |

Reuse `tools/builtins/google/errors.py`.

### 7.4 Rate limits & cache

| Group | cache_ttl | rate_limit |
|-------|-----------|------------|
| Read (search, list, get) | 30–60s | 60/min per user |
| get_message body | 120s | same |
| Write (send, modify) | none | 30/min per user |
| Settings | 300s | 10/min |

Gmail API quota: 1B units/day project — personal bot OK.

### 7.5 Env (новое)

```env
GMAIL_MAX_BODY_CHARS=4000
GMAIL_MAX_ATTACHMENT_BYTES=5242880
GMAIL_DEFAULT_MAX_RESULTS=10
```

---

## 8. Agent prompt hints (добавить в `agent/prompts.py`)

- **Google Gmail** — OAuth same as Calendar; `tags: ["google", "gmail"]`.
- Search: `google.gmail.search_messages` with Gmail `q` syntax — not generic web search.
- Read flow: `search_messages` → `get_message` (or `get_thread` for conversation).
- Before send/reply: read original if user refers to «это письмо» / «ответь».
- Prefer `list_inbox` / `list_unread` for «что во входящих» / «непрочитанные».
- `archive_message` = remove INBOX; `trash_*` = корзина; `delete_*` = permanent + `confirm=true`.
- Do not invent message IDs — from tool results only.
- Large attachments: `get_attachment` only when user asks; warn about size.

---

## 9. Регистрация

```
tools/builtins/google/__init__.py   # GOOGLE_TOOLS += GMAIL_TOOLS
tools/search_enrichment.py          # + ("google", "gmail") tag profile
```

После регистрации: embedding index, `search_tools(tags=["google","gmail"])`.

**Не трогаем** Maps (API key, no OAuth).

---

## 10. Guards & safety

| Action | Guard |
|--------|-------|
| `delete_message`, `batch_delete_messages` | `confirm=true` |
| `send_message`, `reply_to_message`, `send_draft` | optional `confirm=true` for first version — **решить при Mail-2** |
| System labels delete | reject |
| Attachment download | size cap |

---

## 11. Google OAuth verification (production)

| Mode | Кто может подключить | Gmail restricted scopes |
|------|----------------------|-------------------------|
| **Testing** | до 100 test users в consent screen | OK для личного бота |
| **Production** | любой Google user | Security assessment, weeks/months |

**Сейчас:** Testing mode достаточно. В плане зафиксировано: перед публичным релизом — verification.

Restricted scopes: `gmail.modify`, `gmail.settings.basic` — sensitive; document privacy policy URL в consent screen когда пойдём в production.

---

## 12. Checklist перед Mail-1

- [ ] GCP: Enable Gmail API
- [ ] OAuth consent: add gmail scopes
- [ ] `.env`: расширить `GOOGLE_OAUTH_SCOPES`
- [ ] Re-connect тестового user
- [ ] `auth.py`: `get_gmail_service()`
- [ ] `gmail_tools.py` Mail-1 subset
- [ ] Tests
- [ ] BOT_STATUS.md после Mail-1

---

## 13. Связь с Calendar

| | Calendar | Gmail |
|---|----------|-------|
| Auth | OAuth per user | **тот же token** |
| Scopes | calendar | + gmail.modify + gmail.settings.basic |
| Disconnect | `/disconnect_google` | revokes **всё** |
| Tools prefix | `google.calendar.*` | `google.gmail.*` |

Один `/connect_google` → Calendar + Gmail together.

---

*Документ для ревью. После OK — начинаем **Mail-1**.*
