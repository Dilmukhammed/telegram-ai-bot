# Agent Supervisor — план

Meta-controller поверх worker agent: полный trace tool-цикла, решение «продолжить / остановить», coaching hints.  
Файл для ревью перед кодом.

---

## 1. Проблема

Сейчас worker agent крутится в `for turn in range(AGENT_MAX_TOOL_TURNS)` и при лимите вызывает `_finalize_without_tools` с internal prompt *"Stop calling tools…"*.

**Симптомы (реальный кейс coffee + calendar):**

| Turn | Действие | Проблема |
|------|----------|----------|
| 1–2 | search_tools calendar | OK |
| 3 | list_events ✓ | OK |
| 4 | search_tools maps catalog | OK |
| 5 | places_text_search с `query` | wrong arg (coerce частично чинит) |
| 6 | search_tools places rank | лишний search |
| 7 | places_text_search ✓ | OK |
| 8 | search_tools routes | лимит → stop |
| — | create_event, travel_time | **не дошли** |

Модель пересказывает пользователю internal «остановить инструменты» вместо нормального UX.

**Корневая причина:** hard cap без понимания прогресса, без coaching, без graceful stop.

---

## 2. Цель

После исчерпания worker budget (или по soft-triggers) запускать **Supervisor** — тот же LLM (`OPENAI_MODEL`), другой system prompt, **без tools**.

Supervisor:

1. Читает **полный RunTrace** (включая collapsed `search_tools`).
2. Решает: `CONTINUE` | `STOP_GRACEFUL` | `STOP_RETRY` (редко).
3. При `CONTINUE` — даёт worker'у coaching hint + extra turns.
4. При `STOP_*` — формирует instruction для финального ответа пользователю (что сделано / что вручную).

**UX:** пользователь видит статус в draft: *«Проверяю шаги агента…»* когда supervisor стартовал.

---

## 3. Архитектура

```
User message
    │
    ▼
┌─────────────────────────────────────┐
│  Worker Agent                       │
│  tools: search_tools + use_tool     │
│  budget: AGENT_MAX_TOOL_TURNS (30)  │
│  + RunTraceCollector (always on)    │
└──────────────┬──────────────────────┘
               │
     ┌─────────┴─────────┐
     │ trigger?          │
     │ • hard cap        │
     │ • soft loops      │
     │ • periodic (opt)  │
     └─────────┬─────────┘
               ▼
┌─────────────────────────────────────┐
│  Supervisor                         │
│  same LLM, NO tools                 │
│  input: RunTrace + user goal        │
│  output: structured decision JSON   │
└──────────────┬──────────────────────┘
               │
     ┌─────────┼─────────┐
     ▼         ▼         ▼
 CONTINUE  STOP_GRACEFUL STOP_RETRY
     │         │         │
     ▼         ▼         ▼
 +N turns   finalize   new worker pass
 + hint     no tools   with plan hint
```

### 3.1 Роли

| | Worker | Supervisor |
|---|--------|------------|
| Tools | `search_tools`, `use_tool` | **нет** |
| Prompt | `AGENT_SYSTEM_PROMPT` | `SUPERVISOR_SYSTEM_PROMPT` |
| Видит | `messages[]` (search collapse) | **RunTrace** (всё) |
| Действие | вызывает API | анализ + решение |
| Turns | до 30 (+ bonus) | **1 LLM call** (v1) |

### 3.2 Нужны ли supervisor'у tools / search_tools?

**Рекомендация: нет (v1–v2).**

| За tools | Против tools |
|----------|--------------|
| Может сам проверить «создалось ли событие» | Дублирует worker, side effects |
| Может «доделать» create_event | Supervisor ≠ executor — blur ответственности |
| | Trace уже содержит все tool results |
| | +latency, +cost, +race conditions |

**Supervisor = read-only analyst + coach**, не второй агент с API.

**Multi-turn supervisor без tools:** не нужен в v1. Один structured JSON call с compact trace достаточен. Если trace огромный — **compact/summarize trace in code**, не второй reasoning turn.

**Исключение (Phase 3+, optional, скорее всего не делать):** read-only meta-tool `get_run_trace_summary` — бессмысленно, trace уже в prompt.

**Вывод:** supervisor — **1× chat completion, JSON mode, без tools**.

---

## 4. RunTrace — полный лог цикла

Новый модуль: `agent/run_trace.py`

### 4.1 Структура

```python
@dataclass
class ToolStep:
    turn: int
    meta_tool: str                    # search_tools | use_tool
    target_tool: str | None           # google.calendar.* после normalize
    arguments_raw: dict
    arguments_normalized: dict
    result_ok: bool | None
    result_cached: bool
    result_error: str | None
    result_preview: str               # truncated JSON
    duration_ms: int
    timestamp: float

@dataclass
class RunTrace:
    user_id: int | None
    user_message: str
    started_at: float
    steps: list[ToolStep]
    worker_turns_used: int
    worker_turns_budget: int
    final_outcome: str | None         # completed | cap_hit | supervisor_stop | error

    # derived (computed before supervisor)
    search_history: list[dict]        # все search_tools calls
    successful_tools: list[str]
    failed_tools: list[str]
    repeated_patterns: list[str]      # e.g. "search_tools×3 same tags"
    progress_summary: str             # human-readable для supervisor prompt
```

### 4.2 Сбор

`RunTraceCollector` в `agent/loop.py`:

- `on_tool_dispatch(turn, meta_tool, args_raw, args_normalized)`
- `on_tool_result(turn, result_json, duration_ms, telemetry_fields)`
- `build() -> RunTrace`

**Важно:** логировать **до и после coerce** — supervisor видит `query` vs `text_query` mistakes.

**Collapsed search_tools:** collector пишет **до** collapse в messages; supervisor trace не теряет search history.

### 4.3 Compact для prompt

`RunTrace.to_supervisor_text(max_chars=12000)`:

```
Goal: {user_message}

Progress: list_events OK | places OK | travel_time MISSING | create_event MISSING

Turn 1: search_tools tags=[google,calendar] mode=catalog → 23 tools
Turn 2: search_tools query="list events" mode=rank → google.calendar.list_events
Turn 3: use_tool google.calendar.list_events {...} → ok, 4 events
...
Turn 5: use_tool google.maps.places_text_search {query: "..."} → FAIL missing text_query
Turn 6: search_tools (duplicate search, unnecessary)
...

Patterns: 3× search_tools after successful use; wrong arg alias on turn 5
Budget: 30/30 turns used
```

Raw JSON — в DEBUG log / optional file, не в supervisor prompt целиком.

---

## 5. Supervisor — prompt & output

Новый файл: `agent/supervisor.py`

### 5.1 System prompt (черновик)

```
You are a supervisor reviewing an AI agent's tool-use run.

You receive:
- The user's original request
- A full trace of every tool call and result
- How many turns the worker used

You do NOT call tools. You decide what happens next.

Decisions:
- CONTINUE: worker is on track but ran out of turns; give specific coaching
- STOP_GRACEFUL: worker is stuck, looping, or further tools won't help; tell worker how to reply to user
- STOP_RETRY: only if worker went completely wrong direction and a fresh attempt with new plan is needed (rare)

For CONTINUE, include:
- remaining_steps: ordered list of what worker should do next
- hints: concrete mistakes (wrong arg names, unnecessary search_tools, etc.)
- do_not: things to avoid repeating

For STOP_GRACEFUL, include:
- user_reply_brief: what worker should tell user (done / not done / manual steps)
- do not mention internal limits or "stop calling tools"

Output valid JSON only.
```

### 5.2 Response schema

```json
{
  "decision": "CONTINUE" | "STOP_GRACEFUL" | "STOP_RETRY",
  "confidence": 0.0,
  "reasoning": "short internal",
  "remaining_steps": ["google.maps.travel_time", "google.calendar.create_event"],
  "hints": [
    "Turn 5: places_text_search needs text_query, not query",
    "Do not search_tools for maps routes — you already have schemas from turn 8 search"
  ],
  "do_not": ["search_tools with same tags again"],
  "bonus_turns": 10,
  "user_reply_brief": "only for STOP_*"
}
```

Parse with `json.loads` + validation; fallback → `STOP_GRACEFUL` с generic brief.

### 5.3 LLM call

- Тот же `LLMClient` / `OPENAI_MODEL`
- `chat(messages)` **без** `tools=`
- Optional: `response_format: json_object` если провайдер поддерживает

---

## 6. Worker integration

Изменения в `agent/loop.py`:

### 6.1 Замена `_finalize_without_tools`

```python
async def _handle_budget_exhausted(self, trace, messages, on_status, sources):
    if on_status:
        await on_status("Проверяю шаги агента…")

    decision = await self._supervisor.review(trace)

    if decision.decision == "CONTINUE" and self._supervisor_cycles_left > 0:
        if on_status:
            await on_status("Продолжаю выполнение…")
        messages.append({
            "role": "user",
            "content": format_supervisor_coaching(decision),
        })
        self._supervisor_cycles_left -= 1
        # ещё decision.bonus_turns worker loop (без reset messages)
        ...
    elif decision.decision == "STOP_RETRY" and ...:
        ...
    else:
        if on_status:
            await on_status("Формирую ответ…")
        messages.append({
            "role": "user",
            "content": format_supervisor_stop(decision),
        })
        return append_sources(await self._llm.chat(messages), sources)
```

### 6.2 Coaching message (worker видит)

```
Supervisor review (continue):

Remaining steps:
1. google.maps.travel_time from {A} to {B}
2. google.calendar.create_event with ...

Hints:
- Turn 5: you used "query" but places_text_search requires "text_query"
- Skip search_tools unless you need a tool you haven't discovered

Do not:
- Repeat search_tools for google.maps routes

Continue with use_tool only. You have 10 more turns.
```

### 6.3 Stop message (worker видит)

```
Supervisor review (stop):

Reply to the user without calling any more tools.

Include:
- What you already accomplished (list events, found coffee shop, route ETA)
- What you could not complete (calendar event not created)
- Exact manual steps if needed

Do NOT mention tool limits, supervisor, or "stop calling tools".

Brief from supervisor: {user_reply_brief}
```

---

## 7. Triggers — когда вызывать supervisor

### Phase 1 (MVP)

| Trigger | When |
|---------|------|
| `HARD_CAP` | worker turns exhausted |

### Phase 2

| Trigger | When |
|---------|------|
| `LOOP_SEARCH` | ≥3 `search_tools` in last 4 turns without successful `use_tool` |
| `LOOP_FAIL` | ≥2 failed `use_tool` same tool same error |
| `PERIODIC` | every 15 turns proactive check (optional, costs extra) |

Phase 2 triggers → supervisor early, может `CONTINUE` с hint **до** cap.

---

## 8. Limits & safety

| Param | Default | Env |
|-------|---------|-----|
| Worker turns | 30 | `AGENT_MAX_TOOL_TURNS` |
| Bonus turns per CONTINUE | 10 | `AGENT_SUPERVISOR_BONUS_TURNS` |
| Max supervisor cycles per run | 2 | `AGENT_SUPERVISOR_MAX_CYCLES` |
| Max supervisor calls total | 3 | hard cap in code |
| Trace preview max chars | 12000 | `AGENT_SUPERVISOR_TRACE_MAX_CHARS` |

**Cost guard:** после 2× CONTINUE без финального ответа → force `STOP_GRACEFUL`.

**Side effects:** supervisor **никогда** не вызывает tools → не создаёт duplicate events.

---

## 9. UX — статусы в Telegram draft

| Момент | `on_status` text |
|--------|------------------|
| Worker start | `Думаю…` (как сейчас) |
| Tool running | `Запускаю google.calendar…` (как сейчас) |
| **Supervisor start** | **`Проверяю шаги агента…`** |
| CONTINUE | `Продолжаю выполнение…` |
| Finalize after STOP | `Формирую ответ…` |

Реализация: `on_status` callback уже есть в `Agent.run` → `streamer.stream_status`.

---

## 10. Logging

### 10.1 Structured logs

```
INFO:agent.run_trace:run_trace_step turn=3 tool=google.calendar.list_events ok=true duration_ms=660
INFO:agent.supervisor:supervisor_decision decision=CONTINUE bonus_turns=10 cycles_left=1
INFO:agent.supervisor:supervisor_hints hints=[...]
```

### 10.2 Full trace dump (debug)

```
DEBUG:agent.run_trace:run_trace_json {...full RunTrace...}
```

Opt-in: `AGENT_SUPERVISOR_DEBUG_TRACE=1`

### 10.3 Chat history

RunTrace **не** пишется в persisted chat history — только worker final reply.

---

## 11. Файлы (target layout)

```
agent/
  loop.py              # worker loop + supervisor hooks
  run_trace.py         # RunTraceCollector, dataclasses, compact
  supervisor.py        # Supervisor.review(), prompt, parse JSON
  supervisor_prompt.py # SUPERVISOR_SYSTEM_PROMPT
  context_collapse.py  # unchanged; collector logs before collapse

config.py              # AGENT_SUPERVISOR_* settings
.env.example

test_run_trace.py
test_supervisor.py     # mock LLM, decision parsing, coaching format
test_supervisor_integration.py  # optional, mock worker cap scenario
```

---

## 12. Волны реализации

### Wave S-0 — RunTrace collector

- [x] `RunTraceCollector` wired in `agent/loop.py`
- [x] Log every tool call (raw + normalized + result preview)
- [x] `search_history` preserved despite context collapse (`collapsed_from_context` flag)
- [x] Unit tests: trace from mock turns

**Deliverable:** полные логи в терминале, supervisor ещё не подключён.

---

### Wave S-1 — Supervisor on hard cap (MVP)

- [x] `agent/supervisor.py` + prompt
- [x] Replace `_finalize_without_tools` with supervisor flow
- [x] Decisions: `CONTINUE` (+bonus turns + coaching) | `STOP_GRACEFUL`
- [x] UX: `Проверяю шаги агента…` / `Продолжаю выполнение…`
- [x] Config: `AGENT_SUPERVISOR_BONUS_TURNS`, `AGENT_SUPERVISOR_MAX_CYCLES`
- [x] Fallback if JSON parse fails → STOP_GRACEFUL
- [x] Tests: coffee+calendar scenario mock

**Deliverable:** cap hit → supervisor → часто CONTINUE → create_event успевает.

---

### Wave S-2 — Soft triggers

- [x] Loop detection (search spam, repeated failures)
- [x] Early supervisor before cap
- [x] `STOP_RETRY` (optional, 1 retry max)

**Deliverable:** меньше wasted turns до cap.

---

### Wave S-3 — Polish (optional)

- [x] Periodic supervisor every N turns (off by default via `AGENT_SUPERVISOR_PERIODIC_EVERY=0`)
- [x] Admin command `/trace_last` — last RunTrace for user (debug)
- [x] Metrics: supervisor decision counts in telemetry (`/stats` section)
- [x] `AGENT_SUPERVISOR_DEBUG_TRACE=1` — full JSON trace in logs

---

## 13. Тесты

### Unit

- [x] `RunTraceCollector` records collapsed searches
- [x] `to_supervisor_text` truncates safely
- [x] coerce mistake visible in trace (query → normalized)
- [x] Supervisor JSON parse + invalid fallback
- [x] `format_supervisor_coaching` output shape
- [x] `TraceStore` + `SupervisorTelemetry`

### Integration (mock LLM)

- [ ] 30 turns cap → supervisor CONTINUE → worker gets 10 more → final answer without "stop tools"
- [ ] Loop pattern → supervisor STOP_GRACEFUL → user-friendly partial reply
- [ ] 2 supervisor cycles → force stop

### Manual

- [ ] Coffee + calendar flow end-to-end in Telegram
- [ ] Draft shows «Проверяю шаги агента…»

---

## 14. Config summary

```env
# Worker
AGENT_MAX_TOOL_TURNS=30

# Supervisor
AGENT_SUPERVISOR_ENABLED=1
AGENT_SUPERVISOR_BONUS_TURNS=10
AGENT_SUPERVISOR_MAX_CYCLES=2
AGENT_SUPERVISOR_TRACE_MAX_CHARS=12000
AGENT_SUPERVISOR_DEBUG_TRACE=0

# Phase 2
AGENT_SUPERVISOR_SOFT_TRIGGERS=0
AGENT_SUPERVISOR_PERIODIC_EVERY=0
```

---

## 15. Риски

| Risk | Mitigation |
|------|------------|
| Supervisor wrong CONTINUE → ещё 10 wasted turns | max 2 cycles, then force STOP |
| Trace too large for context | compact text, preview truncation |
| +latency (~2–5s per supervisor call) | status UX, only on cap/trigger |
| Supervisor hallucinates mistakes | trace shows raw args; hints are suggestions |
| Same model bias | structured JSON + explicit schema |

---

## 16. Non-goals (v1)

- Supervisor with tools / search_tools
- Supervisor executing calendar/maps actions directly
- Persisting RunTrace in DB
- Replacing context collapse
- Changing system prompt worker'а (coaching via injected user msgs only)

---

## 17. Статус

| | |
|---|---|
| **Статус** | **S-3 done** — `/trace_last`, supervisor stats, debug trace |
| **Next step** | Manual E2E (coffee + calendar), optional Maps-5 |
| **Depends on** | current agent loop, telemetry, coerce |

---

*Last updated: 2026-07-03*
