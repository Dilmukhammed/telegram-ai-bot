# Hermes Agent — Tool System Plan

## Goal

Telegram bot with an agent that can use many tools without passing all tool schemas to the LLM on every request.

The model sees only two meta-tools:

- `search_tools` — find relevant tools by task description
- `use_tool` — execute a tool by name with JSON arguments

Tool discovery uses embeddings (Phase 2). Phase 0 uses keyword search as a placeholder.

## Architecture

```
Telegram Bot (aiogram)          [Phase 3]
        ↓
Agent Loop (orchestrator)       [Phase 0]
        ↓
LLM (9router / OpenAI SDK)      [existing]
        ↓  only meta-tools
Tool Runtime                    [Phase 0]
        ↓
Tool Registry + Tool Index      [Phase 0 / Phase 2]
        ↓
Concrete tools (echo, exa, …)   [Phase 0 mock / Phase 1 real]
```

Principle: the bot does not know about individual tools. It calls the agent. Tools live in `tools/` and are registered centrally.

## Directory Layout (target)

```
telegram-ai-bot/
  PLAN.md
  bot/                 # Phase 3 — thin Telegram adapter (optional split)
  agent/
    loop.py            # tool-calling loop
    prompts.py
    cli.py             # local testing without Telegram
  tools/
    schema.py          # ToolSpec
    registry.py
    index.py           # search (keyword → embeddings)
    runtime.py         # search_tools + use_tool execution
    meta_tools.py      # OpenAI tool definitions for the LLM
    bootstrap.py       # register all builtins
    builtins/
      echo.py          # Phase 0
      exa_search.py    # Phase 1
      exa_fetch.py     # Phase 1
  config.py
  llm.py
  main.py
  streaming.py
```

## Meta-tool Flow

1. User sends a message
2. Agent sends history + user message to LLM with `tools=[search_tools, use_tool]`
3. LLM may call `search_tools(query="…")` → runtime returns matching tool specs
4. LLM calls `use_tool(tool_name="echo.test", arguments={…})` → runtime validates and runs handler
5. Tool result is appended to messages; loop continues until the model returns text
6. Final text is streamed/sent to Telegram (Phase 3)

## ToolSpec Contract

Each tool defines:

| Field | Purpose |
|-------|---------|
| `name` | Unique id, e.g. `exa.web_search` |
| `description` | For embedding index and LLM selection |
| `parameters` | JSON Schema for arguments |
| `handler` | Async function `(arguments) -> result` |
| `tags` | Optional categories: `web`, `search`, … |
| `examples` | Optional; improves retrieval quality |

## Phases

### Phase 0 — Skeleton ✅

- [x] `ToolSpec`, `ToolRegistry`, `ToolRuntime`
- [x] Keyword-based `ToolIndex` (placeholder for embeddings)
- [x] Meta-tools: `search_tools`, `use_tool`
- [x] Mock tool: `echo.test`
- [x] Agent loop + CLI
- [x] Tool calling via 9router

### Phase 1 — Exa ✅

- [x] Register `exa.web_search`, `exa.web_fetch`
- [x] `AsyncExa` handlers, `EXA_API_KEY` in `.env`
- [x] Search type `instant` for chat latency
- [x] Verify agent answers live web questions via CLI / Telegram

### Phase 2 — Embedding Index ✅

- [x] Hybrid tool search: embeddings + keyword fallback
- [x] API embeddings via OpenAI-compatible `/embeddings`
- [x] Local fallback via `fastembed` when API unavailable
- [x] Async index build on first search
- [x] `TOOL_EMBEDDING_PROVIDER=auto|api|local|keyword`

### Phase 3 — Bot Integration ✅

- [x] Telegram handler → `Agent.run()` via `ChatService`
- [x] Rich message streaming for final answer
- [x] Status updates in draft during tool calls
- [x] Per-user dialog history
- [x] End-to-end test in Telegram (web search + page fetch confirmed)

### Phase 4 — Scale (mostly done)

- [x] Result caching with per-tool TTL (max 1 day via `TOOL_CACHE_MAX_TTL`)
- [x] Observability: structured tool call logs + in-memory summary
- [x] Parallel tool calls in the same agent turn when safe
- [x] Rate limits per tool and per user hour
- [ ] Tool categories and permissions per user

## Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| LLM tool surface | 2 meta-tools only | Scales to hundreds of tools |
| Tool location | `tools/builtins/` | One registry, no bot coupling |
| Phase 0 search | Keyword overlap | No API key / embedding deps yet |
| Agent loop | Non-streaming internally | Tool calls need full messages; stream final answer in Phase 3 |
| Validation | JSON Schema on `use_tool` | Security before handler execution |

## Environment Variables

| Variable | Phase | Required |
|----------|-------|----------|
| `TELEGRAM_BOT_TOKEN` | 3 | for bot |
| `OPENAI_BASE_URL` | 0 | yes |
| `OPENAI_API_KEY` | 0 | yes |
| `OPENAI_MODEL` | 0 | yes |
| `EXA_API_KEY` | 1 | for web search |
| `EMBEDDING_BASE_URL` | 2 | embeddings API base (Fireworks) |
| `EMBEDDING_API_KEY` | 2 | embeddings API key |
| `OPENAI_EMBEDDING_MODEL` | 2 | e.g. `fireworks/qwen3-embedding-8b` |
| `LOCAL_EMBEDDING_MODEL` | 2 | local fallback model |
| `TOOL_EMBEDDING_PROVIDER` | 2 | auto / api / local / keyword |
| `AGENT_MAX_TOOL_TURNS` | 0 | optional, default 8 |
| `TOOL_CACHE_MAX_TTL` | 4 | max cache lifetime in seconds, default 86400 (1 day) |
| `EXA_SEARCH_CACHE_TTL` | 4 | override for `exa.web_search`, default 300 |
| `EXA_FETCH_CACHE_TTL` | 4 | override for `exa.web_fetch`, default 3600 |
| `RATE_LIMIT_EXA_SEARCH` | 4 | e.g. `10/60` |
| `RATE_LIMIT_EXA_FETCH` | 4 | e.g. `20/60` |
| `MAX_TOOL_CALLS_PER_USER_HOUR` | 4 | global cap, default 100 |
| `ADMIN_USER_IDS` | 4 | comma-separated Telegram user ids for `/stats` |

## Success Criteria

### Phase 0

```bash
python -m agent.cli "use echo to repeat hello world"
```

Agent should: `search_tools` → find `echo.test` → `use_tool` → respond with echoed text.

### Phase 1

```bash
python -m agent.cli "what happened in AI news this week?"
```

Agent uses Exa and returns an answer with sources.

### Phase 3

Same behavior inside Telegram with streaming rich markdown reply.

---

## Status Summary (2026-07-02)

**Original plan (Phases 0–4): complete for daily use.** Further ideas live in `ROADMAP.md`.

### Done ✅

| Area | What |
|------|------|
| Phase 0 | Registry, runtime, meta-tools, echo, agent loop, CLI |
| Phase 1 | `exa.web_search`, `exa.web_fetch`, live Exa integration |
| Phase 2 | Hybrid embedding index (Fireworks API + keyword/local fallback) |
| Phase 3 | Telegram bot, rich streaming, activity status in draft, per-user history |
| Phase 4 | Cache (per-tool TTL, max 1 day), telemetry, parallel tool calls, rate limits, `/stats` |
| Extra | Argument coercion for malformed `use_tool` calls, max-turns fallback, GFM tables → HTML, Telegram-safe math rules in system prompt |

### Registered tools (current)

| Tool | Purpose |
|------|---------|
| `echo.test` | Debug / test runtime |
| `exa.web_search` | Search the live web |
| `exa.web_fetch` | Fetch a specific page by URL |

### Not done / deferred ❌

| Item | Notes |
|------|-------|
| Phase 4 permissions | Per-user tool categories / allowlists — only needed for a public multi-user bot |
| Tool graph recommendations | See `ROADMAP.md` — suggest 2–3 related tools when one is used |
| Many more tools | Intentionally open-ended; add to `tools/builtins/` + registry as needed |

### Verified in production

- Web search + fetch (e.g. Python Tutorial via `exa.web_fetch`)
- Rich Markdown replies in Telegram
- `/stats` for admin user

