---
skill_id: chat.history
description: Archived chat memory — sessions, period digests (day/week/month), search, turn reads
tags: chat, history, archive
---

# Chat history skill

Use when the user asks about **past conversations**, what you did yesterday/this week/last month, or needs a fact from earlier chats.

**Not this skill:** live Calendar/Gmail/Drive data → use those Google skills. Exact archived tool payloads → `tool_results.get`.

## Discovery

Load once per run: `skills.load` → `skill_id: "chat.history"`.

`search_tools` tags (AND):

| Need | search_tools |
|------|----------------|
| Full chat memory catalog | `{"mode":"catalog","tags":["chat","history"]}` |
| Period digests only | `{"mode":"catalog","tags":["chat","periods"]}` |
| Rank by task | `{"mode":"rank","query":"what did we do yesterday","tags":["chat"]}` |

## Tools

| Tool | Use for |
|------|---------|
| `chat.period.summary` | Precomputed **day / week / month** digest (prefer for broad time questions) |
| `chat.periods.list` | List available period digests |
| `chat.sessions.list` | Discover sessions (+ per-session summary); optional `date` |
| `chat.session.summary` | One session's LLM summary |
| `chat.search` | Find needles across turns; optional `session_id` / `date` |
| `chat.turns.read` | Raw turns for exact quotes |
| `tool_results.get` | Exact archived tool payload via `tool_ref` from search hits |

## Period keys (bot timezone)

Boundaries use `BOT_TIMEZONE` (not UTC unless configured as UTC).

| `period_type` | `period_key` | Example |
|---------------|--------------|---------|
| `day` | `YYYY-MM-DD` | `2026-07-09` |
| `week` | `YYYY-Www` (ISO week) | `2026-W28` |
| `month` | `YYYY-MM` | `2026-07` |

Digests are built from **archived session summaries**.

**When they become ready**
1. **Boundary close (automatic):** after local midnight / ISO week roll / month roll (`BOT_TIMEZONE`), a background loop closes the previous day/week/month for all users.
2. **After session archive:** closed periods for that session's date are refreshed.
3. **On-demand:** `chat.period.summary` generates if missing.

Current open day/week/month may still be incomplete until the period closes.

## Standard flows

### Broad overview ("what did we do yesterday / this week / last month")

```
1. Resolve the period_key in bot timezone from "today" in the system context
2. chat.period.summary({period_type, period_key})
3. Only if the user needs specifics → chat.sessions.list / chat.search / chat.turns.read
```

### Specific fact / code / ID from the past

```
1. chat.search({query, date?})
2. If hit has tool_ref → tool_results.get({ref, mode:"full"})
3. Else chat.turns.read or chat.session.summary for that session_id
```

### Explore unknown past chats

```
1. chat.sessions.list or chat.periods.list
2. chat.session.summary / chat.period.summary
3. chat.search / chat.turns.read for detail
```

## Rules

- Answer only from retrieved memory evidence; do not invent dates or details.
- Prefer **latest** user statement when facts conflict ("actually no", corrections).
- Period digests are rollups — good for overview, not for exact IDs/quotes (drill down).
- Session list summaries are approximate; exact payloads need `tool_results.get`.
- Multi-fact questions → multiple searches when one query misses evidence.
