# Agent Tool Checker — план

Per-tool verification layer: у каждого инструмента — checklist вопросов; отдельная модель (checker) проверяет **конкретный вызов** `use_tool` с evidence из других tool results того же run.

Файл для ревью перед кодом.

---

## 1. Проблема

Supervisor и Trajectory Coach смотрят на **run в целом** (loops, cap, алгоритм, hot data до collapse). Они **не** проверяют микро-корректность отдельного tool call:

| Ситуация | Supervisor / Coach | Tool Checker |
|----------|-------------------|--------------|
| 30 search подряд | ✓ soft trigger | — |
| create_event, слот занят (live) | может не заметить | ✓ fail: overlap |
| delete как repair после bad create | coach может не понять | checker: n_a + cycle context |
| timezone UTC вместо user TZ | — | ✓ fail |
| send gmail не тому thread | — | ✓ fail |

**Корневая причина:** worker видит `{ok: true}` и идёт дальше; никто не сверяет **outcome** и **контекст цикла** (repair loop, self-correction, согласованность checker'ов).

---

## 2. Цель

**Два LLM-слоя + общий cycle log:**

1. **Tool Checker** (micro) — background после selected `use_tool`, **не блокирует worker**.
   - Один call × verification questions × evidence (+ live fetch где нужно).
   - Input включает **run cycle log** (worker + prior checker pass/fail).
   - Output: `ToolCheckerReview` → `trace.checker_reviews[]`.

2. **Checker Arbiter** (macro) — отдельная модель, **как coach**, каждые N tool calls.
   - Input: **полный cycle log** (worker + все checker lines, pass и fail).
   - Решает: intervene? worker уже исправил? несколько fail — одна root cause?
   - Output: один merged hint worker'у (rate limit), не per-checker spam.

**Не дублирует** supervisor/coach: checker = micro ground truth; arbiter = когда вмешаться; coach = алгоритм/trajectory.

---

## 3. Архитектура

```
User message → Worker (use_tool, не ждёт checker)
                    ↓
              RunTraceCollector
                    ↓
         asyncio.create_task (background)
                    ↓
    EvidenceResolver + live fetch (list_events)
                    ↓
    ToolChecker LLM (cycle_log slice + evidence)
                    ↓
         trace.checker_reviews[] + cycle_log snapshot

    every N tool calls (как coach):
                    ↓
    CheckerArbiter LLM (full cycle log + open issues)
                    ↓
         intervene? → один hint в worker messages[]
```

### 3.1 Роли

| | Worker | Supervisor | Coach | Tool Checker | **Checker Arbiter** |
|---|--------|------------|-------|--------------|---------------------|
| Granularity | turn | run | trajectory | **1 tool call** | **run slice + all checkers** |
| Блокирует worker? | — | cap | нет | **нет** | **нет** |
| Input | messages | supervisor trace | coach trace | cycle slice + Q evidence | **full cycle log** |
| Когда | always | cap/triggers | every N | after use_tool async | **every N** |

### 3.2 Run cycle log (`agent/run_cycle_log.py`)

Shared compact log — worker + checker interleaved:

```
[turn 2] worker → quick_add_event OK | args: ... → event id=evt_a
↓
[turn 2] checker → quick_add_event | overall=pass | slot_not_busy=pass
↓
[turn 3] worker → delete_event OK | args: event_id=evt_a
```

- **Coach:** `build_coach_trace()` — wrapper (+ sheets, coach replies).
- **Checker:** snapshot at spawn — worker through current turn, prior checker reviews only.
- **Arbiter:** full log, all pass/fail, группировка open issues.

### 3.3 Ground truth, не process order

| Было (отвергнуто) | Стало |
|-------------------|--------|
| fail если нет prior freebusy в trace | **live fetch** slot conflicts |
| skip freebusy, слот свободен | **pass** |
| skip freebusy, overlap | **fail** |

```python
EvidenceRef(kind="live_fetch", fetch="calendar_slot_conflicts", ...)
```

Rule-based overlap → fail без LLM. Checker prompt: repair loops (`delete` после bad `create` → `n_a`).

### 3.4 Question + declared evidence (без required prior freebusy)

Каждый вопрос декларирует evidence refs; `prior_tool_result` — optional context, не process gate.

```python
VerificationQuestion(
    id="slot_not_busy",
    evidence=(
        EvidenceRef(kind="live_fetch", fetch="calendar_slot_conflicts", ...),
        EvidenceRef(kind="call_under_review", fields=("start", "end", "event", ...)),
        EvidenceRef(kind="user_goal", optional=True),
    ),
)
```

---

## 4. Модель данных

Новые типы: `tools/verification.py` (или `agent/tool_checker_types.py`).

### 4.1 EvidenceRef

```python
@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    # prior_tool_result | call_under_review | user_goal | runtime_context | prior_step_by_field

    tool_names: tuple[str, ...] = ()           # для prior_tool_result
    tool_name_pattern: str | None = None         # e.g. "google.calendar.*"
    match: dict[str, str] = ()                   # "$call.calendar_id" → resolve from current call
    time_overlap: str | None = None              # "$call.start..$call.end"
    fields: tuple[str, ...] = ()                 # для call_under_review — какие args/result keys
    required: bool = False
    optional: bool = False
    max_age_steps: int | None = None             # только последние N tool steps
    label: str = ""                              # для prompt: "availability_check"
```

**Kinds (v1):**

| kind | Источник |
|------|----------|
| `prior_tool_result` | Optional context из trace (не process gate для slot) |
| `live_fetch` | Checker self-fetch (calendar list_events для slot conflicts) |
| `call_under_review` | args + result текущего вызова |
| `user_goal` | `RunTrace.user_message` |
| `runtime_context` | timezone бота |

**Kinds (v2+):** `prior_step_by_field` (event_id из get_event@turn 2 == patch@turn 5), `archived_tool_result` (ref из collapsed stub).

### 4.2 VerificationQuestion

```python
@dataclass(frozen=True)
class VerificationQuestion:
    id: str
    text: str
    severity: str  # critical | warn | info
    evidence: tuple[EvidenceRef, ...] = ()
    fail_if_evidence_missing: bool = True   # required ref missing → fail, not unknown
    llm_required: bool = True               # False = только rule-based (evidence presence)
```

### 4.3 ToolSpec extension

```python
@dataclass(frozen=True)
class ToolSpec:
    ...
    verification_questions: tuple[VerificationQuestion, ...] = ()
    checker_enabled: bool = True   # per-tool opt-out (echo, skills.load)
```

Questions живут **в том же файле**, что и `ToolSpec` (e.g. `calendar_tools.py`), не в SKILL.md — SKILL для worker, questions для checker.

### 4.4 CheckerDecision

```python
@dataclass
class QuestionVerdict:
    question_id: str
    verdict: str          # pass | fail | unknown | n_a
    severity: str
    reason: str
    evidence_used: list[str]  # labels resolved
    evidence_missing: list[str]

@dataclass
class ToolCheckerReview:
    tool_name: str
    turn: int
    step_index: int
    overall: str          # pass | fail | warn | unknown
    verdicts: list[QuestionVerdict]
    checker_input: str
    cycle_log: str        # snapshot для arbiter / debug
    rule_based_only: bool

@dataclass
class ArbiterDecision:   # Wave C-3 — TODO
    intervene: bool
    issue_resolved: bool  # worker уже починил — не inject
    assessment: str
    focus_now: str
    do_not: list[str]
    resolved_issues: list[str]
    open_issues: list[str]
```

### 4.5 RunTrace extension

```python
@dataclass
class RunTrace:
    ...
    checker_reviews: list[dict[str, Any]] = field(default_factory=list)
```

`ToolStep` (optional v2): `checker_review_id: str | None`.

---

## 5. EvidenceResolver — алгоритм

Модуль: `agent/tool_checker_evidence.py`

### 5.1 Resolve flow

```
resolve(question, current_step, trace, runtime) -> ResolvedQuestion
  for each EvidenceRef:
    if kind == prior_tool_result:
      candidates = trace.steps[:current_index] filtered by tool_names
      candidates = apply_match(candidates, ref.match, current_step)
      candidates = apply_time_overlap(candidates, ref.time_overlap, current_step)
      pick most recent ok result (or all if small)
    if kind == call_under_review:
      extract fields from current_step.arguments_normalized + result_json
    if kind == user_goal:
      trace.user_message
    if kind == runtime_context:
      settings.bot_timezone, etc.
  return ResolvedQuestion(text, evidence_snippets[], missing_required[])
```

### 5.2 Matchers (v1, heuristic)

| Matcher | Логика |
|---------|--------|
| `calendar_id` | arg `calendarId` / `calendar_id` совпадает с prior call |
| `time_overlap` | ISO start/end текущего call пересекается с window prior list_events/freebusy |
| `event_id` | string equality в args |
| `same_day` | date part start совпадает с prior query range |

Без ML. False negative → `unknown`, не `pass`.

### 5.3 Rule-based (до LLM)

- **slot_not_busy:** live fetch → overlapping events (exclude created id) → pass/fail.
- **Не** fail на missing prior freebusy в trace.
- Parse/unwrapping use_tool envelope в evidence (`result.event`).

---

## 6. ToolChecker LLM

Модуль: `agent/tool_checker.py`, prompt: `agent/tool_checker_prompt.py`

### 6.1 Profile

Как coach: `LLMClient(settings, profile="checker")`.

Env prefix: `CHECKER_{BASE_URL,API_KEY,MODEL}` — fallback на `SUMMARIZE_*` если пусто.

### 6.1 System prompt (sketch)

```
You are a tool-use checker. You verify ONE tool call against specific questions.
You do NOT call tools. Use ONLY provided evidence snippets.
For each question return pass | fail | unknown | n_a with a one-line reason.
- pass: evidence supports correct usage
- fail: evidence shows mistake or ignored data
- unknown: evidence insufficient or ambiguous (NOT pass)
- n_a: question does not apply to this call
Do not invent facts not in evidence.
```

### 6.2 User payload (checker)

```
Goal: {user_message}

Run cycle log (worker + prior checker verdicts):
  [turn 2] worker → quick_add_event OK ...
  [turn 2] checker → quick_add_event | overall=pass | ...

Call under review: tool, turn

Questions + evidence snippets...
```

Output JSON:

```json
{
  "verdicts": [
    {"question_id": "slot_not_busy", "verdict": "pass", "reason": "freebusy turn 4 shows slot free at 15:00"},
    {"question_id": "timezone_correct", "verdict": "pass", "reason": "timeZone matches bot timezone Asia/Tashkent"}
  ],
  "overall": "pass",
  "hint_for_worker": ""
}
```

Parse failure → `overall: unknown`, log warning, не блокировать run.

---

## 7. Интеграция в agent loop

Файл: `agent/loop.py` — hook после `trace.on_tool_result`, только для billable `use_tool`.

### 7.1 Trigger conditions

```python
def should_run_tool_checker(spec: ToolSpec, step: ToolStep, settings) -> bool:
    if not settings.agent_checker_enabled:
        return False
    if not spec.verification_questions:
        return False
    if not spec.checker_enabled:
        return False
    if step.result_cached:
        return False  # optional: skip cache hits
    if settings.checker_tools_allowlist and spec.name not in allowlist:
        return False
    return True
```

### 7.2 Placement

```
_execute_tool_turn:
  trace.on_tool_result(...)
  if should_run_tool_checker:
    asyncio.create_task(checker.review_step(...))  # не await
    trace.record_checker_review(...)  # в task callback

every N tool calls (parallel hook с coach):
  if new checker_reviews since last arbiter:
    decision = await checker_arbiter.review(trace)  # один LLM
    if decision.intervene and not decision.issue_resolved:
      append merged hint (max CHECKER_MAX_HINTS_PER_RUN)
```

**Worker никогда не ждёт checker tasks.** Gather checkers только в `finally` (trace completeness).

### 7.4 Interaction с coach / supervisor

| Event | Поведение |
|-------|-----------|
| Checker fail | только в trace; hint — через **arbiter** |
| Worker self-fix | arbiter: `issue_resolved=true`, skip inject |
| 2–3 fail подряд | arbiter группирует root cause → **один** hint |
| Coach interval | arbiter на том же N или offset; не дублировать hints |

---

## 8. Pilot: Google Calendar

Первый полный пакет — write + supporting reads.

### 8.1 `google.calendar.create_event`

| id | severity | question | evidence |
|----|----------|----------|----------|
| `slot_not_busy` | critical | Was the slot actually free? | **live_fetch** slot_conflicts |
| `time_matches_user` | critical | Does start/end match user request? | user_goal, call start/end |
| `timezone_correct` | critical | Is timeZone correct vs user/bot TZ? | call timeZone, runtime_context |
| `calendar_correct` | warn | Right calendar (not random/shared by mistake)? | call calendarId, prior list_calendars optional |
| `duration_sane` | warn | Duration reasonable (not 0 / multi-day mistake)? | call start/end |
| `summary_present` | info | Title/summary non-empty and meaningful? | call summary |

**Fail scenarios:**

- Live fetch shows overlap at 15:00 → `slot_not_busy` **fail**
- No overlap → **pass** (даже без prior freebusy в trace)
- User «завтра 15:00», create at 10:00 → **fail** `time_matches_user`
- Delete после bad create в cycle log → `user_intent_to_delete` **n_a**

### 8.2 `google.calendar.freebusy` / `find_free_slots` (read verify)

| id | question | evidence |
|----|----------|----------|
| `range_covers_intent` | Query range covers the day/time user asked? | user_goal, call timeMin/timeMax |
| `calendars_included` | Checked the calendar that will be written to? | call items, prior list_calendars |

Reads checker'ят **достаточность** сбора данных перед write.

### 8.3 Other calendar writes (wave C-2)

| Tool | Top questions |
|------|---------------|
| `patch_event` / `update_event` | correct event_id? only intended fields changed? |
| `delete_event` | right event? user intent to delete? not recurring master by mistake? |
| `quick_add_event` | natural language parsed correctly? |
| `move_event` | target calendar exists? |

### 8.4 Question templates (reuse)

```python
CALENDAR_AVAILABILITY_EVIDENCE = EvidenceRef(
    kind="prior_tool_result",
    tool_names=("google.calendar.freebusy", "google.calendar.find_free_slots"),
    ...
)
WRITE_REQUIRES_AVAILABILITY = VerificationQuestion(
    id="slot_not_busy",
    text="Was availability checked and slot free?",
    evidence=(CALENDAR_AVAILABILITY_EVIDENCE, ...),
)
```

---

## 9. Rollout по семьям (после calendar)

| Wave | Family | Notes |
|------|--------|-------|
| **C-3** | **Checker Arbiter** | intervene decision, merged hints, open issues |
| C-4 | Gmail + Sheets | send/reply recipient+thread; range/overwrite |
| C-5 | Polish | stats, debug, metrics |
| C-6 | Drive / Maps / Tasks / … | по приоритету |

**Не checker'ить v1:** `search_tools`, `skills.*`, `echo.test`, `coach.reply`, `tool_results.get`.

---

## 10. Файлы

```
tools/
  schema.py                    # + verification_questions on ToolSpec
  verification.py              # VerificationQuestion, EvidenceRef (NEW)

agent/
  run_cycle_log.py             # shared worker+checker timeline (NEW)
  tool_checker.py
  tool_checker_live.py           # live fetch + rule overlap (NEW)
  tool_checker_prompt.py
  tool_checker_evidence.py
  tool_checker_format.py         # hint text (for arbiter)
  checker_arbiter.py             # Wave C-3 TODO
  checker_arbiter_prompt.py        # Wave C-3 TODO
  coach_trace.py                 # thin wrapper over run_cycle_log
  loop.py
  run_trace.py
  trace_store.py

tools/builtins/google/
  calendar_checker.py          # CALENDAR_* questions constants (NEW)
  gmail_checker.py             # GMAIL_* write questions (C-4)
  sheets_checker.py            # SHEETS_* write questions (C-4)
  calendar_tools.py            # attach questions to ToolSpecs

config.py                      # AGENT_CHECKER_* settings
.env.example

test_tool_checker_evidence.py  # resolver unit tests
test_tool_checker.py           # parse, verdict logic, mock LLM
test_tool_checker_calendar.py  # create_event scenarios
```

---

## 11. Волны реализации

### Wave C-0 — Schema + evidence resolver (no LLM)

- [x] `tools/verification.py` — dataclasses
- [x] Extend `ToolSpec` with `verification_questions`
- [x] `EvidenceResolver` + matchers for calendar_id, time_overlap
- [x] Unit tests: mock trace, resolve freebusy before create
- [x] `calendar_checker.py` — question constants for create_event
- [x] Attach questions to `GOOGLE_CALENDAR_CREATE_EVENT` (disabled checker call)

**Deliverable:** resolver tests green; questions defined; checker не вызывается.

---

### Wave C-1 — Checker LLM + trace (observe only)

- [x] `ToolChecker` + prompt + `profile="checker"` in `llm.py`
- [x] Config: `AGENT_CHECKER_ENABLED`, `CHECKER_*` model env
- [x] Hook in `loop.py` — run after create_event (+ freebusy optional)
- [x] `RunTrace.checker_reviews` + log
- [x] Admin `/checker_last` (or section in `/trace_last`)
- [x] Tests: mock LLM, JSON parse, evidence-missing → fail without LLM

**Deliverable:** create_event calls produce checker reviews in trace; no worker hints.

---

### Wave C-2 — Calendar pack + live fetch

- [x] Questions for 8 calendar tools (read + write)
- [x] Live fetch `list_events` для `slot_not_busy` (ground truth)
- [x] Background checker (не блокирует worker)
- [x] `CHECKER_TOOLS_ALLOWLIST=google.calendar.*`
- [x] Unwrap use_tool envelope в evidence
- [ ] Manual E2E в Telegram

---

### Wave C-2b — Run cycle log (shared)

- [x] `agent/run_cycle_log.py` — worker + checker interleaved
- [x] Coach migrated to shared log
- [x] Checker получает cycle_log snapshot + prior checker verdicts
- [x] `cycle_log` в `checker_reviews[]`
- [x] Repair loop guidance в checker prompt
- [x] `test_run_cycle_log.py`

---

### Wave C-3 — Checker Arbiter

- [x] `CheckerArbiter` LLM + prompt
- [x] Shared hook with coach (`coach_every_n_tool_calls`)
- [x] Flush pending checker tasks only at periodic hook (not every turn)
- [x] Input: full cycle log + new checker summaries
- [x] `ArbiterDecision` — intervene / issue_resolved
- [x] `CHECKER_INJECT_HINTS=1` → merged hint; coach hint skipped if arbiter injected
- [x] Rate limit `CHECKER_MAX_HINTS_PER_RUN`
- [x] `arbiter_reviews[]` in trace
- [ ] Manual E2E

**Deliverable:** arbiter decides intervention; worker not blocked between hooks.

---

### Wave C-4 — Gmail + Sheets (partial) + Universal registry (fallback)

- [x] Gmail send-family explicit (4 tools)
- [x] Sheets values write explicit (5 tools)
- [x] **`tools/checker/registry.py`** — explicit override OR generic template fallback
- [ ] **Handcrafted packs by group** (see below)

### Wave C-4b — Calendar full pack (23/23) ✅

Per-tool questions in `calendar_checker.py` — not templates. Each tool reviewed for:
- read: query scope, timezone, calendar_id, prior context
- write: user intent, target id from trace, live slot check (after create/patch)
- destructive: confirm, not-primary, intent vs clear/delete
- **No live fetch after delete** (checker runs post-call; get_event would always 404)

| Tool kind | Live fetch |
|-----------|------------|
| create/quick_add/import/patch time change | `calendar_slot_conflicts` |
| patch mutation verify | `calendar_event_exists` → event JSON for LLM |
| delete/move/get | trace + user_goal only |

### Wave C-5 — Polish ✅

- [x] Checker stats in `/stats`
- [x] `AGENT_CHECKER_DEBUG=1` — full evidence bundle in logs
- [x] Skip checker on cached results (`CHECKER_SKIP_CACHED=1`, configurable)
- [x] Metrics: pass/fail rate per tool name (`CheckerTelemetry`)

---

## 12. Config summary

```env
# Tool Checker
AGENT_CHECKER_ENABLED=1
CHECKER_BASE_URL=              # fallback SUMMARIZE_BASE_URL
CHECKER_API_KEY=
CHECKER_MODEL=                 # fallback SUMMARIZE_MODEL (deepseek-v4-flash)
CHECKER_MAX_OUTPUT_TOKENS=1024
CHECKER_INJECT_HINTS=0         # arbiter inject (C-3), not per-checker
CHECKER_MAX_HINTS_PER_RUN=3
CHECKER_TOOLS_ALLOWLIST=       # empty = all tools with questions
CHECKER_SKIP_CACHED=1
CHECKER_EVIDENCE_MAX_CHARS=8000
AGENT_CHECKER_DEBUG=0
```

---

## 13. Тесты

### Unit — EvidenceResolver

- [ ] freebusy turn 4 + create turn 5 → resolves availability_check
- [ ] create turn 3 without prior freebusy → missing required
- [ ] wrong calendar_id in freebusy → no match → unknown/fail
- [ ] time overlap matcher edge cases (all-day, TZ offset)

### Unit — Checker parse

- [ ] Valid JSON → QuestionVerdict list
- [ ] Invalid JSON → overall unknown, no crash
- [ ] Rule-based fail skips LLM for that question (optional optimization)

### Integration (mock LLM)

- [ ] Live overlap → fail slot_not_busy
- [ ] Cycle log shows repair delete → delete checker n_a
- [ ] `CHECKER_INJECT_HINTS=1` → arbiter inject, not per-checker

### Manual

- [ ] Telegram: «создай встречу завтра 15:00» — with agent that skips freebusy → fail in `/trace_last`
- [ ] Same with freebusy first → pass

---

## 14. Риски

| Risk | Mitigation |
|------|------------|
| +latency on worker | checkers **background**; arbiter 1× per N tools |
| False fail on repair delete | cycle log + n_a in checker; arbiter sees self-fix |
| Multiple/consecutive fails | arbiter groups root cause; one merged hint |
| Hint spam | arbiter rate limit; not per-checker inject |
| 434 tools × questions maintenance | templates; rollout by family; questions colocated with ToolSpec |
| Collapsed archived evidence | v2: resolve via tool_results.get ref in trace |

---

## 15. Non-goals (v1)

- Blocking worker on checker completion
- Direct inject on every checker critical fail (→ arbiter instead)
- Auto-rollback (delete event on fail)
- Checking every tool in registry
- Replacing supervisor or coach

**In scope (изменено):** checker live fetch для ground truth; cycle log shared с coach.

---

## 16. Открытые вопросы

1. **Arbiter vs coach same N?** Shared interval или offset (+2 tool calls)?
2. **Arbiter input size:** full run vs window since first open issue?
3. **Coach + cycle log:** показывать checker lines coach'у?
4. **Failed tool calls (`ok: false`):** checker'ить?
5. **Archived collapsed evidence:** достаточно summary в cycle log?

---

## 17. Статус

| | |
|---|---|
| **Статус** | **341 explicit packs + Wave C-5 polish (telemetry, debug, metrics)** |
| **Next group** | Yandex Music Tier 3+ (80 on template) — optional |

---

*Last updated: 2026-07-08*
