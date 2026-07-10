# Chat Storage v2 — Sessions + Message Rows

Living design doc for replacing `chat_history.messages_json` blobs with normalized SQLite storage.

**Status:** implemented (phases 1–4, 6) — phase 5 agent tools pending  
**Last updated:** 2026-07-09

---

## Goal

Replace the current single-row-per-user JSON blob with:

- **Sessions** — bounded conversations with metadata and English summary when closed
- **Message rows** — one SQLite row per persisted message (addressable by `message_id` / `seq`)
- **Future agent tools** — read archived sessions / message batches (active session stays in prompt as today)

**Non-goal:** change how the active session feels to the user or the agent during an ongoing chat.

---

## Decisions (locked)

| Topic | Decision |
|-------|----------|
| Active session UX | **Unchanged** — last N turns still go into the LLM prompt (`CHAT_MAX_HISTORY`) |
| Storage vs prompt | Same persisted slice as today; only the **backend** becomes rows + sessions |
| Auto-new session on idle | **No** — new session only on explicit triggers |
| Session end triggers | `/start`, `/reset`, optional `/new_chat` |
| Summary language | **English** |
| Summary timing | When session is **archived** (end), async LLM job |
| Summary model | Cheap profile: `SUMMARIZE_*` (not agent model) |
| Storage fidelity | **Full** tool JSON in DB — no collapse/stubs in chat store |
| Exclude from storage | `search_tools`, supervisor injections, `reasoning_content` |
| Per-user tables | **No** literal table per user — use `user_id` column + indexes |
| Archived memory for agent | **Tools later** — active session remains in prompt automatically |
| In-run collapse | **Keep** for prompt/runtime (`search_tools` stripped before save) — not stored anyway |
| Timestamps | **UTC ISO-8601** in SQLite; display via `BOT_TIMEZONE` if needed |
| Message time source | Telegram `message.date` when available; server `now()` for assistant/tool rows |

---

## Time & metadata

Every session and every message row carries **explicit timestamp columns** plus optional **`metadata_json`** for extensible fields.

### Rules

- **Storage:** always UTC, `TEXT` ISO-8601 (e.g. `2026-07-09T10:15:30.123456+00:00`) — same convention as `chat_history` / token stores today.
- **Display:** bot may format for user/admin using `BOT_TIMEZONE` (`Asia/Tashkent`); DB stays UTC.
- **Two clocks for messages:**
  - `source_at` — when the event happened in Telegram / user-facing timeline (user message time from `Message.date`)
  - `created_at` — when the row was persisted on server (always set)
- For **assistant** / **tool** rows: `source_at` = end of agent turn (when reply was finalized); `created_at` = insert time (usually ms later).
- **Gap prefix** (`MESSAGE_GAP_MINUTES`): computed from previous user message `source_at`, not `created_at`.

### Session temporal fields

| Column | Meaning |
|--------|---------|
| `created_at` | Session record created (first activity or explicit open) |
| `started_at` | Timestamp of **first user message** in session (= first message `source_at`) |
| `last_message_at` | Timestamp of **last persisted message** (`source_at` preferred, else `created_at`) |
| `updated_at` | Any update to session row (new message, summary, status) |
| `archived_at` | When session was closed (`/reset`, `/start`, `/new_chat`) |
| `summary_started_at` | When summary LLM job began (NULL if not started) |
| `summary_completed_at` | When summary was written (NULL if pending/failed) |

### Message temporal & meta fields

| Column | Meaning |
|--------|---------|
| `source_at` | Event time (Telegram user message time or agent turn finish time) |
| `created_at` | Server persist time (INSERT) |
| `metadata_json` | Extensible payload (see below) |

**Typical `metadata_json` keys (v1):**

```json
{
  "telegram_message_id": 12345,
  "telegram_chat_id": 67890,
  "message_thread_id": null,
  "turn_id": "uuid-of-agent-run",
  "agent_turn_index": 3,
  "has_image": false,
  "workspace_paths": ["uploads/123_doc.pdf"],
  "content_chars": 420,
  "tool_ok": true,
  "tool_cached": false
}
```

Only set keys that apply; omit nulls. Schema stays forward-compatible without migrations for new meta keys.

---

## Problem with v1 (`chat_history`)

Current schema (`bot/history_store.py`):

```sql
chat_history (user_id PK, messages_json, last_message_at, updated_at)
```

Issues:

- No session boundaries — one endless stream per user
- Cannot address message #47 or read a batch by range
- No place for “what this conversation was about” (summary)
- JSON blob is bad for search, pagination, and future tools
- Trim by turns rewrites the whole blob; old sessions are not first-class

---

## Target architecture

```
Telegram user
  → ChatService (unchanged active-session prompt behavior)
  → Agent.run(history = last N turns from active session)
  → append_turn_messages (same collapse rules as today)
  → ChatStore: INSERT message rows + update session counters
  → on /reset|/start: archive session → summary job → new active session
```

### Active session (unchanged behavior)

```
User message
  → load last N turns from active session → agent prompt
  → agent replies
  → persist the same worker slice we save today → SQLite rows
```

Follow-ups (“да”, “ещё”, “то же самое”) work without memory tools.

### Archived sessions (new)

- Closed on `/start`, `/reset`, `/new_chat`
- English summary generated once at archive time
- Agent accesses via **future tools** (`chat.sessions.list`, `chat.messages.read`, …)

---

## Database

**File:** `data/chat.sqlite` (env: `CHAT_DB_PATH`)  
Replace: `data/chat_history.sqlite` after migration.

Optional: keep separate DBs for tokens / access / tool_results — only chat moves to this schema.

### Table: `chat_sessions`

```sql
CREATE TABLE chat_sessions (
    session_id              TEXT PRIMARY KEY,       -- uuid or ulid
    user_id                 INTEGER NOT NULL,
    status                  TEXT NOT NULL,          -- active | archived
    summary                 TEXT,                   -- English; NULL while active
    summary_status          TEXT,                   -- pending | done | failed | NULL (active)
    title                   TEXT,                   -- optional short title (future)
    message_count           INTEGER NOT NULL DEFAULT 0,
    -- temporal (all UTC ISO-8601)
    created_at              TEXT NOT NULL,
    started_at              TEXT,                   -- first user message source_at
    last_message_at         TEXT,                   -- last message in session
    updated_at              TEXT NOT NULL,
    archived_at             TEXT,
    summary_started_at      TEXT,
    summary_completed_at    TEXT,
    -- extensible meta (timezone label at open, archive reason, etc.)
    metadata_json           TEXT
);

CREATE INDEX idx_chat_sessions_user_status
    ON chat_sessions(user_id, status, last_message_at DESC);

CREATE INDEX idx_chat_sessions_user_started
    ON chat_sessions(user_id, started_at DESC);
```

**Session `metadata_json` examples:**

```json
{
  "opened_by": "first_message",
  "closed_by": "reset",
  "bot_timezone": "Asia/Tashkent",
  "first_telegram_message_id": 1001,
  "last_telegram_message_id": 1042
}
```

**Invariant:** at most **one** `active` session per `user_id`.

**Session key for messages:** `session_id` (FK from `chat_messages`).

### Table: `chat_messages`

```sql
CREATE TABLE chat_messages (
    message_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL REFERENCES chat_sessions(session_id),
    user_id             INTEGER NOT NULL,       -- denorm for guards / indexes
    seq                 INTEGER NOT NULL,       -- 1..N order within session
    role                TEXT NOT NULL,          -- user | assistant | tool | system
    content             TEXT,                   -- text or JSON string
    content_type        TEXT NOT NULL DEFAULT 'text',
                        -- text | tool_calls | tool_result | image_placeholder
    tool_call_id        TEXT,
    tool_name           TEXT,                   -- denorm from use_tool when applicable
    -- temporal (all UTC ISO-8601)
    source_at           TEXT NOT NULL,          -- Telegram / turn event time
    created_at          TEXT NOT NULL,          -- server persist time
    metadata_json       TEXT,                   -- telegram ids, turn_id, workspace, etc.
    UNIQUE(session_id, seq)
);

CREATE INDEX idx_chat_messages_session_seq
    ON chat_messages(session_id, seq);

CREATE INDEX idx_chat_messages_user
    ON chat_messages(user_id, session_id);

CREATE INDEX idx_chat_messages_source_at
    ON chat_messages(user_id, source_at DESC);
```

### Table: `schema_migrations`

```sql
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

---

## What gets persisted (message rows)

Same rules as current `extract_worker_history_for_persist` + `append_turn_messages`:

| Persist | Do not persist |
|---------|----------------|
| `user` messages (incl. `[image]` placeholder, workspace path in text/metadata) | `search_tools` + catalog results |
| `assistant` + `tool` pairs for each `use_tool` with **full tool JSON** | Supervisor review injections |
| Final `assistant` reply to user | `reasoning_content` on assistant messages |

**No collapse in DB:** tool results are stored verbatim (not `{archived, ref}` stubs).

**Note:** `tools/tool_results.sqlite` archive may still exist for in-run context management; chat store saves the persisted worker slice as-is.

---

## Session lifecycle

### Create active session

- First message from an approved user with no active session → insert `chat_sessions` (`status=active`)

### During active session

- Each turn after agent completes → insert 1..N `chat_messages` rows (increment `seq`)
  - Set `source_at` from Telegram `Message.date` (user) or turn finish time (assistant/tool)
  - Set `created_at` at INSERT
  - Fill `metadata_json` (telegram ids, turn_id, tool flags, workspace paths)
- Update session: `message_count`, `last_message_at`, `updated_at`
  - On **first user message:** set `started_at = source_at`
- **Prompt:** load last `CHAT_MAX_HISTORY` **user turns** from active session (same trim as `trim_history_to_turns`)
- **Gap prefix:** use last user message `source_at` from DB (or RAM cache synced with DB)
- **In-run collapse** in agent loop unchanged; collapsed items never reach persist layer

### End session (archive)

Triggers:

- `/reset`
- `/start` (also clears queue / skills as today)
- `/new_chat` (optional explicit command)

Steps:

1. Set `status=archived`, `archived_at=now`, `updated_at=now`
2. Set `metadata_json.closed_by` = `reset` | `start` | `new_chat`
3. Set `summary_status=pending`
4. Enqueue async summary job (English)
5. Create new empty `active` session for user
6. `ChatService` in-memory cache points at new session

### Summary job

- **When:** immediately after archive (async, non-blocking)
- **Model:** `SUMMARIZE_*` — default `accounts/fireworks/models/deepseek-v4-flash`
- **Language:** English only
- **Input:** all **persisted session traces** (`chat_session_traces`), formatted like coach cycle logs
  - Each turn: `user_message`, `assistant_reply`, `build_run_cycle_log(trace)`
  - Oldest turns dropped first if total exceeds `CHAT_SESSION_SUMMARY_MAX_INPUT_CHARS`
  - Per-turn cap: `CHAT_SESSION_SUMMARY_PER_TURN_MAX_CHARS`
- **Not used for summary:** raw `chat_messages` tool JSON (kept for prompt reload + future tools)
- **Output:** 2–4 sentences → `chat_sessions.summary`, `summary_status=done`, `summary_completed_at=now`
- **On start:** set `summary_started_at=now`
- **On failure:** `summary_status=failed` (no traces, LLM error, or summary too short)

### Session traces (persisted per turn)

Table `chat_session_traces`:

| Column | Meaning |
|--------|---------|
| `turn_seq` | 1..N user turn within session |
| `user_message` | Prepared user text (from `RunTrace.user_message`) |
| `assistant_reply` | Final reply shown to user (`RunResult.reply`) |
| `trace_json` | Full `RunTrace.to_dict()` snapshot |
| `source_at` | User message time (Telegram) |

Saved in `ChatService.generate_reply()` after each agent run.

Draft prompt:

```
Summarize the chat session in 2-4 English sentences.
Focus on user goals, tools used, key outcomes, and open items.
Do not invent facts.

Session trace log:
{formatted turns}
```

---

## Code layout (planned)

```
bot/chat_store/
  __init__.py
  schema.py           -- DDL + migrations
  sessions.py         -- active/archive, get_or_create_active
  messages.py         -- append, read range, get by id
  migrate_v1.py       -- chat_history blob → sessions + rows
  summary.py          -- archive summary worker (session traces → SUMMARIZE_*)

bot/chat_service.py   -- wire store instead of history_store blob
bot/history_store.py  -- deprecate after migration (or thin adapter)
```

`ChatService` public behavior for Telegram users **unchanged**; internal persist/load swap only.

---

## Config (planned)

```env
# Chat storage v2
CHAT_DB_PATH=data/chat.sqlite
CHAT_SESSION_SUMMARY_ON_ARCHIVE=1
CHAT_SESSION_SUMMARY_MAX_INPUT_CHARS=80000
CHAT_SESSION_SUMMARY_PER_TURN_MAX_CHARS=12000
CHAT_SUMMARY_LANGUAGE=en

# Unchanged — affects prompt only, not DB retention
CHAT_MAX_HISTORY=20
MESSAGE_GAP_MINUTES=20

# Optional retention (0 = unlimited archived sessions)
CHAT_MAX_ARCHIVED_SESSIONS=0
```

**Not used:** `CHAT_SESSION_IDLE_HOURS` — no auto-close on idle.

---

## Migration from v1

Source: `data/chat_history.sqlite` → table `chat_history`.

**Startup:** `run_v1_migration_if_needed()` in `main.py` (env `CHAT_MIGRATE_V1_ON_STARTUP=1`).

**Manual:** `python scripts/migrate_chat_v1.py [--verify-only] [--target active|archived]`

For each v1 row (`user_id`, `messages_json`, `last_message_at`):

1. Skip if user already has any row in `chat_sessions`
2. Import messages into one session with synthetic monotonic timestamps anchored at `last_message_at`
3. Default **`CHAT_MIGRATE_V1_TARGET=active`** — seamless prompt continuity (v1 blob → active session)
4. Optional **`archived`** — archived import + new empty active (plan doc mode)
5. `metadata_json`: `{"migrated_from": "chat_history_v1", ...}`
6. **No summary job** for migrated sessions (no traces; `summary_status` stays NULL)
7. Marker in `chat_store_meta` key `history_v1_import` — idempotent
8. Optional backup: `chat_history.sqlite.bak`

After verification:

- v1 DB no longer written (already true since Phase 2)
- Keep `.bak` one release for rollback
- Phase 6: retire `bot/history_store.py`

---

## Future agent tools (Phase 5 — separate PR)

For **archived** sessions and deep reads. Active session remains in prompt.

| Tool | Purpose |
|------|---------|
| `chat.sessions.list` | List sessions for current user (summary, **started_at**, **archived_at**, message_count) |
| `chat.session.summary` | Get summary + **temporal metadata** for one `session_id` |
| `chat.messages.read` | Batch read: `session_id`, `from_seq`, `limit` (includes **source_at**, metadata) |
| `chat.message.get` | Single row by `message_id` (full content + times + metadata) |
| `chat.messages.search` | Text/regex search within session or all user sessions |
| `chat.messages.read_range_time` | (optional) filter by `source_at` window — later if needed |

**Guards:** always filter by `RunContext.user_id`; never trust `user_id` from LLM args alone.

**Checker questions:** per-tool verification plan (later).

---

## Prompt vs storage (clarification)

| Layer | Behavior |
|-------|----------|
| **LLM prompt (active session)** | Unchanged — last N user turns from active session |
| **SQLite chat store** | Full persisted worker slice per turn, no search_tools/supervisor/reasoning |
| **In-run agent loop** | Existing collapse for `search_tools` etc. — runtime only |
| **Archived sessions** | Not in prompt; accessed via tools when implemented |

---

## Implementation phases

### Phase 1 — Storage layer

- [x] `bot/chat_store/` schema + migrations
- [x] `sessions.py` — get/create active, archive
- [x] `messages.py` — append rows, read range for prompt load
- [x] Unit tests (in-memory SQLite)

### Phase 2 — ChatService integration

- [x] Replace `history_store` blob read/write with chat_store
- [x] `get_history()` builds `list[dict]` from active session rows (same shape as today)
- [x] `append_turn_messages()` inserts rows after trim logic
- [x] `reset_history()` archives + new session + delete behavior aligned with today

### Phase 3 — Summary on archive

- [x] `summary.py` async worker on archive
- [x] English summary via `SUMMARIZE_*` from session traces
- [x] `chat_session_traces` table + persist trace per turn
- [x] `summary_status` handling + logging

### Phase 4 — Migration

- [x] `migrate_v1.py` script or startup one-shot
- [x] Verify row counts vs JSON message counts
- [x] Document rollback (keep v1 backup)

### Phase 5 — Agent tools (later)

- [ ] Register tools + handlers + tests
- [ ] Skill/playbook snippet for when to list/read archived sessions
- [ ] Optional bot commands: `/sessions`, `/session <id>` for humans

### Phase 6 — Cleanup

- [x] Remove `bot/history_store.py` (v1 read via `migrate_v1.seed_v1_history_db` / `_load_v1_rows` only)
- [x] Update `BOT_STATUS.md`, `.env.example`
- [x] Retire `CHAT_HISTORY_DB_PATH` → `CHAT_MIGRATE_V1_SOURCE_PATH` (+ deprecated fallback in config)

---

## Testing plan

- Session invariants: one active per user
- Append + load round-trip matches current `test_history_persist` expectations
- **Timestamps:** user row `source_at` = Telegram date; session `started_at` / `last_message_at` updated correctly
- **metadata_json** round-trip for telegram_message_id, turn_id
- Trim: prompt sees last N turns; DB retains full session (unless we later add DB trim — **not in v1**)
- Archive on `/reset` creates new active session + archived old
- Summary job mocked in tests; one integration test with real summarize model optional
- Migration test: sample blob → rows count and roles
- Access control: unapproved users do not create sessions (align with `access_store`)

---

## Open items (minor — can decide during implementation)

- [ ] `session_id` format: UUID v4 vs ULID (ULID nicer for sort)
- [ ] `/new_chat` command — ship with v2 or only `/reset`?
- [ ] Summary retry on failure
- [ ] `CHAT_MAX_ARCHIVED_SESSIONS` enforcement job (if non-zero)
- [ ] Admin command to read any user's session (out of scope unless requested)

---

## Related docs / code (current)

| Path | Role |
|------|------|
| `bot/chat_store/` | v2 SQLite sessions + messages + traces + summary |
| `bot/chat_store/migrate_v1.py` | One-shot import from legacy `chat_history` blob |
| `bot/chat_service.py` | History load/save orchestration |
| `agent/history_persist.py` | What gets into worker persist slice |
| `bot/history_persist.py` | Turn trim for prompt |
| `agent/context_collapse.py` | In-run search_tools collapse |
| `config.py` | `CHAT_DB_PATH`, `CHAT_MAX_HISTORY`, `CHAT_MIGRATE_V1_*` |

---

## Summary

**Active chat stays exactly as it works now in the prompt.** We only replace the persistence layer with sessions + per-message rows, add English summaries when a session ends, and later expose archived data to the agent via tools.
