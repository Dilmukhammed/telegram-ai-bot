# Tool Result Archive — plan & spec

Long-lived **per-user** storage for fat tool results. The agent keeps **full JSON in context while hot**; after collapse, only **summary + ref + recall hint** remain. Full payload is always recoverable via `tool_results.get`.

## Goals

- Context stays small on long runs and between user turns.
- No data loss — full results in SQLite.
- Summaries are **hints only** — agent must call `tool_results.get` for exact data.

## Flow

```
tool executes → full result appended to messages (agent sees full)
              → if len(content) > 150: save payload to DB (ref), start bg summarize (≤3 retries)

while hot: agent reads full result in messages

collapse triggers:
  • run finished (before history persist)
  • mid-run: current_turn - result_turn >= 10

on collapse:
  • if summarize ok → replace tool message with {ref, summary, warning, recall hint}
  • if summarize failed or timed out → collapse with summary "Summary unavailable." (full payload stays in DB via ref)
```

## Reliability warning (always in collapsed stub)

> Summary is approximate — do not rely on it for exact quotes, IDs, counts, or decisions that need precision. Use `tool_results.get({"ref":"…"})` for the full stored result.

## Database (`data/tool_results.sqlite`)

| Column | Purpose |
|--------|---------|
| `ref` | Opaque PK (`tr_<hex>`) |
| `user_id` | Owner (Telegram id) |
| `run_id` | Agent run that created the row |
| `tool_name` | e.g. `exa.web_search` |
| `turn` | Worker turn index |
| `args_json` | Normalized tool arguments |
| `payload_json` | Full tool result JSON (the `content` string body) |
| `char_count` | Size of payload |
| `summary` | LLM summary (nullable) |
| `summarize_status` | `pending` \| `ok` \| `failed` |
| `summarize_attempts` | 0–3 |
| `ok` | Tool succeeded |
| `cached` | From tool cache |
| `created_at` | ISO UTC |
| `expires_at` | TTL eviction |

## Tools

### `tool_results.get`

```json
{ "ref": "tr_abc123", "mode": "full" | "summary" }
```

- Scoped to `user_id` from run context.
- `full` → returns stored payload JSON.
- `summary` → returns summary text only.

Excluded from **new DB rows**: `tool_results.get` (recall reuses the target ref).

`tool_results.get` **full** responses in context are still collapsed (stale steps / run end):
- If the target ref already has `ok` summary → reuse it, no extra LLM call.
- If summarize failed or is pending → queue summarize on the stored payload, then collapse.

## Summarizer

- Runs **in a background queue** (default max **3** concurrent LLM calls per process).
- **Per tool family** prompts (`exa`, `yandex`, `google`, `workspace`, `skills`, `default`).
- Input capped (`TOOL_RESULT_SUMMARIZE_MAX_INPUT_CHARS`, default 12k).
- Up to **3** LLM attempts per result; on total failure → `summarize_status=unavailable`, collapse still proceeds.

## Config (.env)

| Key | Default |
|-----|---------|
| `TOOL_RESULT_DB_PATH` | `data/tool_results.sqlite` |
| `TOOL_RESULT_ARCHIVE_MIN_CHARS` | `150` |
| `TOOL_RESULT_COLLAPSE_STALE_STEPS` | `10` |
| `TOOL_RESULT_TTL_HOURS` | `72` |
| `TOOL_RESULT_SUMMARIZE_MAX_INPUT_CHARS` | `12000` |
| `TOOL_RESULT_SUMMARIZE_MAX_RETRIES` | `3` |
| `TOOL_RESULT_SUMMARIZE_MAX_CONCURRENT` | `3` |
| `TOOL_RESULT_ARCHIVE_ENABLED` | `true` |
| `TOOL_RESULT_CLEANUP_INTERVAL_SECONDS` | `3600` |
| `TOOL_RESULT_MAX_ROWS_PER_USER` | `0` (disabled) |

## Maintenance (Phase 2)

- **Startup:** one `purge_expired()` (+ optional per-user row cap) when bot starts.
- **Background loop:** same maintenance every `TOOL_RESULT_CLEANUP_INTERVAL_SECONDS` (min 60s).
- **`/reset`:** deletes all archived rows for the user (along with chat history).
- **`tool_results.get`:** expired refs return unknown (lazy delete on access).

## Implementation phases

- [x] Phase 1: store + summarize + get tool + collapser + loop wiring
- [x] Phase 2: TTL cleanup job / `/reset` purge for user
- [x] Phase 3: admin stats (stored refs count, bytes) — in `/stats`

## Wiring

| Location | Role |
|----------|------|
| `agent/loop.py` | `ToolResultCollapser` per run; register after tool append; stale + run-end collapse |
| `agent/history_persist.py` | Run-end collapse already applied in loop before persist |
| `tools/builtins/tool_results_get.py` | Recall tool |
| `tools/tool_results/*` | Store, summarize, collapser, maintenance |
| `main.py` | Startup purge + background cleanup loop |
| `/stats` (admin) | Context tokens + per-user & global archive stats |
