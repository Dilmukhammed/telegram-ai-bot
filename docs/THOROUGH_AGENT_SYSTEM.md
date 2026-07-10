# Thorough Multi-Agent System (draft)

> Отдельная система для **долгих, тщательных** заданий.  
> **Не подключена к Telegram-боту** — проектируем и обсуждаем постепенно.  
> Референсный запрос: [§ Референс — кофейни Ташкент](#референс--кофейни-ташкент).

---

## Зачем отдельно от текущего бота

Текущий worker-агент оптимизирован под **интерактивный run**: мало turns, collapse контекста, coach/supervisor на ходу.  
Для задач «собери 5 сущностей, **проверь каждое поле**, отфильтруй мусорные источники» нужен другой режим:

- явный **контракт готовности** (что считать done);
- **долгая память** вне chat context (факты, источники, статусы проверки);
- **параллельные** суб-агенты с узкой ролью;
- **quality gate** перед отдачей пользователю.

---

## Стек (черновик)

| # | Этап | Одна фраза | Статус |
|---|------|------------|--------|
| **1** | **Parallel phase planners** | 3 модели параллельно → логические фазы работы | 🟢 черновик готов |
| **2** | **Plan merge** | 1 merger → `MasterPhasePlan` | 🟡 проектируем |
| 3 | Execution | Исполнение по фазам (workers, tools) | ⚪ позже |
| 4 | Verification | Факт-чек внутри/между фазами | ⚪ позже |
| 5 | Synthesis & delivery | Финальные артефакты и ответ пользователю | ⚪ позже |
| 6 | Quality gate | Закрытие job / эскалация | ⚪ позже |

**Фаза 1** — не исполнение. Три модели **одновременно** читают запрос и выдают **независимые** планы из **логических фаз**. Слияние — фаза 2.

---

## Фаза 1 — три параллельных планировщика

### Идея

Один запрос → **три независимых ответа**. Каждая модель:

1. Делит работу на **логические фазы** (сколько нужно — столько и пишет; фиксированного числа нет).
2. Внутри фазы — **логические блоки** (что происходит по смыслу, не по tool call).
3. Учитывает **как устроен context collapse** у worker-агента (см. ниже).
4. Знает **каталог возможностей** (tools в system prompt) — только чтобы понимать *что вообще возможно*, **не** чтобы писать «вызови exa.web_search».

```
                    ┌──► [P1] Unit planner      ──► PhasePlan
User request ───────├──► [P2] Surface planner  ──► PhasePlan     → Фаза 2: merge
+ collapse brief    └──► [P3] Hot-window planner ──► PhasePlan
+ tools catalog (read-only awareness)
```

### Общий блок в system prompt (всем трём)

#### A. Каталог инструментов — только осведомлённость

Краткий список **областей**, не пошаговый recipe:

- web search / fetch (Exa)
- Google: sheets, docs, calendar, drive, gmail, maps, tasks
- workspace files, PDF, telegram delivery, tool_results.get (recall archived)
- skills playbooks

**Запрет в выходе фаз:** имена tools, `use_tool`, `search_tools`, JSON аргументов.

#### B. Как работает context у worker-агента (обязательно учитывать)

| Механизм | Поведение | Следствие для фаз |
|----------|-----------|-------------------|
| **Tool result archive** | Результат > ~150 chars сохраняется в DB; в messages пока **полный JSON** | Пока «hot» — можно читать из контекста |
| **Stale collapse** | Через **~10 worker turns** после вызова полный JSON → `{archived, ref, summary}` | Summary **неточный**; точность только через recall |
| **Run-end collapse** | В конце run всё тяжёлое схлопывается перед persist history | Между сообщениями пользователя — только stubs |
| **search_tools collapse** | После **первого успешного** `use_tool` в run все `search_tools` пары **удаляются** из messages | Каталог tools в контексте не вечный |
| **Duplicate use_tool** | Повтор с тем же результатом → footnote, старый схлопывается | Не полагаться на «я видел это 20 шагов назад» |
| **Large tool arguments** | Толстые args тоже архивируются | То же окно hot/cold |
| **Skills** | Expanded skill сворачивается при смене / idle | Playbook не бесконечен в контексте |

**Правило для планировщиков:** фаза должна явно говорить, **что должно быть уже вынесено в долгую память** (sheet, doc, fact store) до того, как сырые fetch/search уйдут в summary.

**Hot window (рабочая эвристика):** ~8–10 worker turns на пакет тяжёлых чтений без persist наружу — рискованно.

---

### Три модели — три угла на одни и те же фазы

Одна задача, **три разных логики нарезки**. Ответы не согласовываются внутри фазы 1.

| ID | Имя | Что оптимизирует | Типичная нарезка |
|----|-----|------------------|------------------|
| **P1** | **Unit / Substance** | Единицы содержания | 1 фаза = 1 сущность end-to-end (найти → проверить → зафиксировать → следующая) |
| **P2** | **Surface / Delivery** | Выходы и «что где живёт» | Фазы: черновик → проверенный dataset → публичный артефакт → короткий ответ пользователю |
| **P3** | **Hot-window / Context** | Жизнь данных в контексте | Фазы укладываются в окна collapse; явные точки «persist сейчас» |

### Модели (Fireworks serverless)

| Роль | Модель | `MODEL` env |
|------|--------|-------------|
| **P1** Unit | Kimi K2.6 | `accounts/fireworks/models/kimi-k2p6` |
| **P2** Surface | GLM 5.2 | `accounts/fireworks/models/glm-5p2` |
| **P3** Hot | Qwen3.7 Plus | `accounts/fireworks/models/qwen3p7-plus` |

Три разных семьи (Moonshot / Z.ai / Qwen) — независимые углы на одну задачу.

Количество фаз **не фиксировано**. P1 на кофейнях может дать 6 фаз (5 кофеен + синтез), P2 — 4, P3 — 3 широких окна.

---

### Выход каждой модели: `PhasePlan`

Общими словами, структурированно:

```yaml
phase_plan:
  planner_id: unit | surface | hot_window
  summary: "Одним абзацем — как нарезана работа"

  phase_count: 4
  phases:
    - id: phase_1
      name: "Кофейня 1 — полный цикл"
      goal: "Одна кофейня полностью в таблице, прежде чем открывать следующую"
      logical_blocks:
        - "Собрать кандидатов и критерии laptop-friendly"
        - "Проверить адрес, часы, wifi/розетки по источникам"
        - "Зафиксировать строку в основном dataset"
      entry_condition: "Пустой dataset или предыдущая единица закрыта"
      exit_condition: "Строка 1 заполнена, источник привязан"
      collapse_risk: medium
      must_persist_before_exit:
        - "Факты по единице вне chat context (dataset row)"
      context_notes: "Не копить fetch по 5 кофейням — после collapse summary ненадёжен"

    - id: phase_2
      # ...

  delivery_atmosphere:   # опционально, богаче у P2
    tone: "RU, дружелюбно-деловой"
    user_facing: "Вердикт + компактная таблица, без простыни URL"

  non_goals: ["Маршруты", "Бронь"]

  assumptions: ["..."]
```

**Поля `collapse_risk` / `must_persist_before_exit` / `context_notes`** — обязательны у **P3**; P1 и P2 тоже заполняют, но P3 самый строгий.

---

### Чего модели фазы 1 НЕ делают

- Не выбирают tools и не пишут tool calls.
- Не мержат планы друг с другом (это фаза 2).
- Не исполняют и не верифицируют факты.
- Не диктуют точное число фаз друг другу — три независимых мнения.

---

### Пример: кофейни Ташкент (три независимых плана, сжато)

**P1 (unit)** — 6 фаз: `setup schema` → `cafe 1..5` (каждая: discover+verify+row) → `verdict`.

**P2 (surface)** — 4 фазы: `internal research notes` → `verified sheet` → `user summary` → `optional calendar null`.

**P3 (hot window)** — 3 фазы:
1. Схема + 2 кофейни (всё записано до следующего тяжёлого search batch)
2. Ещё 2 кофейни (тот же принцип)
3. Пятая + вердикт + финальная подача (пока последние fetch hot)

---

## Фаза 2 — merge трёх планов

### Идея

На входе — три независимых `PhasePlan` (P1, P2, P3) + исходный запрос.  
На выходе — один **`MasterPhasePlan`**: последовательность **логических фаз** для execution, без tool names.

**Одна модель — Merger (M).** Не голосование кодом, не усреднение: merger **читает все три мнения** и собирает план по **явным правилам приоритета** (ниже). При конфликте — фиксирует решение в `merge_log`.

```
PhasePlan (P1 unit)     ─┐
PhasePlan (P2 surface)  ─┼──► [M] Merger ──► MasterPhasePlan ──► Фаза 3: execution
PhasePlan (P3 hot)      ─┘         ▲
User request + collapse brief ─────┘
```

Merger **не исполняет** и **не добавляет** новые сущности (5-я кофейня из головы). Только синтез уже предложенного.

---

### Правила приоритета (жёсткие)

| Вопрос | Кто главный | Правило |
|--------|-------------|---------|
| **Сколько фаз и границы единиц** | **P1** | Не сливать в одну фазу то, что P1 разнес по сущностям (5 кофеен ≠ 1 batch search) |
| **Размер hot-batch внутри фазы** | **P3** | Если P1 дал 5 отдельных фаз, P3 может сказать «не больше 2 единиц за окно» → merger **группирует** P1-фазы в master-фазы по 2, но **не** теряет persist между группами |
| **Финальная подача пользователю** | **P2** | Отдельная master-фаза в конце, если P2 предложил `user summary` / delivery surface |
| **`must_persist_before_exit`** | **P3** (строже) | Берётся **максимум** строгости: union всех persist-требований на ту же логическую единицу |
| **`delivery_atmosphere`, tone** | **P2** | Копируется в master как глобальные поля |
| **`non_goals`, `assumptions`** | **пересечение** | В master только то, что не противоречит; при расхождении — assumption + `merge_log` |
| **Collapse risk** | **P3** | На master-фазу: `max(p1, p2, p3)` по уровню (low < medium < high) |

**Запрещено merger'у:** уменьшить число persist-точек ради «короче план».

---

### Алгоритм merge (для промпта M и для кода позже)

```
1. PARSE три PhasePlan → валидный JSON.

2. SKELETON из P1
   - Взять фазы P1 как основной каркас (порядок единиц).
   - Фазы P1 типа setup / verdict сохранить как первую/последнюю логические точки.

3. WINDOW GROUPING (P3 поверх P1)
   - Прочитать P3: сколько единиц допустимо до обязательного persist.
   - Если P1.many_phases и P3.batch_size = 2 → объединить соседние unit-фазы P1
     в одну master-фазу, НО logical_blocks = конкатенация блоков каждой единицы
     и must_persist_before_exit после КАЖДОЙ единицы внутри списка.

4. SURFACE OVERLAY (P2)
   - Сопоставить фазы P2 с master-фазами по смыслу (research → ранние, sheet → середина, user → конец).
   - На каждую master-фазу добавить секцию delivery: { surface, visible_to_user, format_notes }.
   - Если P2 имеет финальную фазу без аналога в P1 — append как последняя master-фаза.

5. COLLAPSE OVERLAY (P3)
   - На каждую master-фазу: context_notes, collapse_risk, must_persist из P3
     для пересекающегося окна.

6. DEDUP metadata
   - non_goals: intersection; если пусто — union с пометкой в merge_log.
   - assumptions: union уникальных.

7. EMIT MasterPhasePlan + merge_log (каждое нетривиальное решение).
```

---

### Выход: `MasterPhasePlan`

```yaml
master_phase_plan:
  version: 1
  source_plans: [unit, surface, hot_window]

  merge_summary: >
    Каркас из P1 (по одной кофейне). P3 сгруппировал 2+2+1 в три execution-окна.
    P2 добавил отдельную финальную фазу для короткого ответа в Telegram.

  phase_count: 5
  phases:
    - id: m1_setup
      name: "Подготовка dataset"
      goal: "Схема таблицы и критерии laptop-friendly зафиксированы"
      logical_blocks:
        - "Определить колонки и формат unknown (✅/❌/❓)"
        - "Согласовать критерии отбора кандидатов"
      entry_condition: "Старт job"
      exit_condition: "Пустой sheet с заголовками готов"
      must_persist_before_exit:
        - "Заголовки и имя sheet в долгой памяти"
      collapse_risk: low
      delivery:
        surface: google_sheet
        visible_to_user: false
        format_notes: "Только header row, freeze"
      contributed_by: { structure: unit, delivery: surface, collapse: hot_window }

    - id: m2_cafes_1_2
      name: "Кофейни 1–2 (hot window A)"
      goal: "Две кофейни полностью в таблице до следующего search batch"
      logical_blocks:
        - "Кофейня 1: discover → verify → row + source"
        - "Кофейня 2: discover → verify → row + source"
      exit_condition: "2 строки данных, у каждой source"
      must_persist_before_exit:
        - "Строка кофейни 1 в sheet"
        - "Строка кофейни 2 в sheet"
      collapse_risk: high
      context_notes: "Не начинать кофейню 3, пока 1–2 не persisted"
      delivery:
        surface: google_sheet
        visible_to_user: false

    - id: m3_cafes_3_4
      name: "Кофейни 3–4 (hot window B)"
      # ... аналогично m2

    - id: m4_cafe_5
      name: "Кофейня 5 (hot window C)"
      # ... одна единица + проверка полноты таблицы

    - id: m5_user_delivery
      name: "Ответ пользователю"
      goal: "Вердикт и компактная выдача без простыни sources"
      logical_blocks:
        - "Выбрать лучшую для длинной работы с обоснованием по фактам из sheet"
        - "Короткая таблица или ссылка на sheet"
      entry_condition: "5 строк verified в sheet"
      exit_condition: "Пользователь получил финальное сообщение"
      collapse_risk: low
      delivery:
        surface: telegram_message
        visible_to_user: true
        format_notes: "Вердикт 2–3 предложения → compact table → одна ссылка"
      contributed_by: { structure: surface, delivery: surface }

  delivery_atmosphere:
    tone: "RU, дружелюбно-деловой"
    forbid: ["raw_source_dump", "duplicate_full_sheet"]

  non_goals: ["Маршруты", "Бронь"]
  assumptions: ["..."]

  merge_log:
    - rule: "P1 skeleton"
      detail: "6 unit-фаз свернуты в 3 hot-window + setup + delivery"
    - rule: "P3 persist"
      detail: "must_persist после каждой кофейни, не только после пары"
    - rule: "P2 final phase"
      detail: "m5_user_delivery добавлена из P2, в P1 была частью verdict"
```

---

### Модель Merger (M) — system prompt (скелет)

**Роль:** synthesis planner. Вход: user request, collapse brief, три JSON `PhasePlan`. Выход: один JSON `MasterPhasePlan`.

**Жёстко:**
- Следовать таблице приоритетов выше.
- Не упоминать tools.
- Каждая master-фаза имеет `logical_blocks`, `exit_condition`, `must_persist_before_exit` (может быть пустым только если collapse_risk low и фаза чисто delivery).
- `merge_log` минимум 2 записи при любой группировке фаз.

**Мягко:**
- Имена фаз — человекочитаемые на языке запроса.
- `phase_count` = len(phases).

---

### Валидация после merge (детерминированная, без LLM)

Перед фазой 3 execution прогонять **MergeValidator**:

| Check | Fail если |
|-------|-----------|
| `has_setup` | Нет фазы с подготовкой артефакта, когда P1/P2 требовали dataset |
| `has_user_delivery` | P2 просил user-facing фазу, а в master нет `visible_to_user: true` |
| `persist_coverage` | P3 требовал persist per unit, а в grouped фазе < N persist points |
| `no_tool_names` | В тексте есть `use_tool`, `exa.`, `google.` |
| `non_empty_blocks` | У фазы нет `logical_blocks` |

При fail → один retry merger с ошибками validator **или** эскалация human.

---

### Human-in-the-loop (опционально)

Перед execution показать:
- `merge_summary` + список master-фаз (имя + goal + persist bullets);
- свёрнуто — три исходных плана.

Approve / правка одной фразой → amend master (версия +1).

---

### Чего фаза 2 НЕ делает

- Не запускает workers.
- Не меняет user request.
- Не переписывает фазу 1 (нет обратной связи в P1/P2/P3 в v1).

---

## Референс — кофейни Ташкент (post-mortem)

| Проблема бот-run | Какой планировщик фазы 1 это ловит |
|------------------|-------------------------------------|
| 5 search, потом sheets | **P1** — одна кофейня = одна фаза с persist |
| 30 URL в ответе | **P2** — отдельная фаза «короткий user summary» |
| Bishkek в sources, забытые fetch | **P3** — `must_persist_before_exit` до collapse |
| Цены без меню | **P1** logical block «проверить по источнику» в фазе единицы |

**Идеальный путь:** три `PhasePlan` → **merge (5 master-фаз)** → execution.

| После merge | Что это даёт |
|-------------|--------------|
| m2–m4 hot windows | Не 5 search подряд; persist каждые 2 кофейни |
| m5_user_delivery | Нет 30 URL в чате |
| must_persist на каждую единицу | Collapse не убивает незаписанные fetch |

### Архив идей (отложено)

Ранние **DeliveryBrief** / **TaskContract** как отдельные модели — частично в P2 и P1. Acceptance predicates → quality gate, не phase 1.

## Связь с текущим ботом (пока none)

| Thorough system | Telegram bot today |
|-----------------|-------------------|
| `PhasePlan` × 3 | `user_message` string |
| Долгая память фактов | `RunTrace` + tool result store + sheets/docs |
| Фазы с persist до collapse | Один chat context, stale ~10 turns |
| Verifier (позже) | supervisor + coach |

Возможная будущая интеграция: бот распознаёт «тяжёлое» задание → создаёт contract → отдаёт job id. **Не в scope сейчас.**

### Config (`.env`)

| Модель | Profile `LLMClient` | Default `MODEL` | Env prefix |
|--------|---------------------|-----------------|------------|
| P1 unit | `thorough_planner_unit` | `kimi-k2p6` | `THOROUGH_PLANNER_UNIT_{BASE_URL,API_KEY,MODEL}` |
| P2 surface | `thorough_planner_surface` | `glm-5p2` | `THOROUGH_PLANNER_SURFACE_*` |
| P3 hot | `thorough_planner_hot` | `qwen3p7-plus` | `THOROUGH_PLANNER_HOT_*` |
| Merger M | `thorough_merger` | `glm-5p2` | `THOROUGH_MERGER_*` |

`THOROUGH_ENABLED=0` по умолчанию. Пустые `BASE_URL` / `API_KEY` → fallback на `SUMMARIZE_*` (как coach).

| Env | Default | Назначение |
|-----|---------|------------|
| `THOROUGH_PLANNER_MAX_OUTPUT_TOKENS` | `4096` | max output фазы 1 (каждый planner) |
| `THOROUGH_MERGER_MAX_OUTPUT_TOKENS` | `8192` | max output фазы 2 (merger) |

Вывод planners/merger: **только YAML**, без thinking/reasoning в ответе; post-process отрезает preamble и markdown fences.

---

## Открытые вопросы

1. **Retry merger:** один retry после validator или цикл до 3?
2. **Tools catalog в prompt фазы 1:** полный список имён или только области?
3. **Human approve:** обязателен в v1 или только debug?
4. **Amend master:** пользователь правит текстом — снова M или детерминированный patch?
5. **Четвёртая модель фазы 1:** отдельная «атмосфера» или хватит P2 + merger?

---

## Changelog

| Дата | Что |
|------|-----|
| 2026-07-07 | **Merger:** GLM 5.2 вместо Kimi (чистый YAML без thinking). |
| 2026-07-07 | **Фаза 1 модели:** P1 Kimi K2.6, P2 GLM 5.2, P3 Qwen3.7 Plus (defaults в config). |
| 2026-07-07 | **Фаза 2 merge:** модель Merger (M), правила приоритета P1/P2/P3, алгоритм, `MasterPhasePlan`, validator, пример 5 фаз на кофейнях. |
| 2026-07-07 | **Фаза 1 переделана:** 3 параллельных planner → `PhasePlan`. |
