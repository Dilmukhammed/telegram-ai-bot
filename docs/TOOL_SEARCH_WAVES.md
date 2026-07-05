# Tool search improvement — wave plan

**Goal:** Hit@1 ≥ 99% on benchmark, prod queries stable at #1, rules scale without 400 aliases.

**Principle:** intent → one winner → penalty siblings. Eval-driven, not blanket coverage.

**Baseline (Wave 4 complete):** 54 cases, Hit@1 ≥98.1%, MRR ~0.987, 0 misses.

**Gate before deploy:**
```bash
.venv\Scripts\python.exe scripts\check_tool_search_eval.py
```

**Artifacts:**
| Path | Purpose |
|------|---------|
| `tools/ranking/` | Keyword bonus rules (search, antonym, list, auth, io) |
| `tools/ranking/constants.py` | Declarative tables: SEARCH_SIBLINGS, DOMAIN_SEARCH_WINNERS, … |
| `eval_tool_search_benchmark.py` | Benchmark cases |
| `eval_tool_search.py` | Full eval report |
| `scripts/check_tool_search_eval.py` | CI gate |
| `scripts/probe_search.py` | Ad-hoc probes (`data/probe_queries.json`) |
| `scripts/export_tool_registry_audit.py` | Regen `data/tool_registry_audit.json` |
| `test_keyword_ranking.py` | Unit tests for ranking rules |
| `test_tool_aliases.py` | Alias coverage + ≤45 budget gate |

---

## Wave 0 — Infrastructure ✅

**Done.**

- Split `keyword_action_bonus` → `tools/ranking/{search,antonym,list,auth,io}_rules.py`
- Declarative tables stubbed in `constants.py`
- Probe harness, audit export, eval gate, unit tests
- **Exit:** refactor without regression (Hit@1 ≥ 97.4%)

---

## Wave 1 — Search sibling penalty ✅

**Done.**

- `detect_search_domain()` + sibling penalty on `SEARCH_SIBLINGS` (-2.5)
- Domain winner extra boost (+2.0)
- Generic `search` → exa +2, siblings -2.5
- `tasks` domain → `google.tasks.search_tasks`
- Fix: skip bare `search`/`list`/… token in multi-word `expand_query_terms` (exa was winning via isolated term)
- +5 benchmark cases

**Results (44 cases):** Hit@1 **97.7%** (api), MRR 0.989, 0 misses. All domain+search #1. Only #2: reverse geocode (Wave 2).

---

## Wave 2 — Antonym & antagonist pairs ✅

**Done.**

- `AntonymRuleSpec` engine + `ANTONYM_RULES` table (with `any_query_tokens` / `unless_query_tokens`)
- Yandex likes/dislikes: 5 entities, write-intent penalty on `*_add/remove`
- Pairs: geocode/reverse, sheets read↔append, tasks↔tasklists, downloads (music/drive/gmail), telegram↔gmail send, google↔yandex auth
- Aliases: `users_likes_albums`, `users_likes_artists`, `users_dislikes_tracks`
- +5 benchmark cases → **49 total**

**Results (api):** Hit@1 **98.0%**, MRR 0.986, 0 misses. Reverse geocode fixed.

---

## Wave 3 — List intent disambiguation ✅

**Done.**

- `ListIntentRuleSpec` engine + `LIST_INTENT_RULES` table in `constants.py`
- Rules: list+files/drive → drive.list_*; list+events/calendar → calendar.list_*; list+inbox → gmail.list_*; list+user+playlists → users_playlists_list; bare `list` → penalize tasks CRUD, boost skills.list
- Aliases: `google.drive.list_files`, `google.drive.list_folder`
- +4 benchmark cases → **53 total**

**Results (api):** Hit@1 **≥98.0%**, MRR ~0.987, 0 misses. list files/events/user playlists #1.

---

## Wave 4 — Targeted aliases (~35–45 max) ✅

**Done.**

- +14 aliases for benchmark collision victims (44 total, ≤45 budget)
- Drive: search_files, download_file, export_file
- Tasks: search_tasks, list_tasks, list_default_tasks
- Calendar: list_today, list_upcoming, freebusy, find_free_slots, search_events
- Sheets: append_values (fixes append vs get_values)
- Workspace: find
- Telegram: send_file
- Each alias includes negative phrases for noisy neighbors
- +1 benchmark case: `find workspace files by pattern` → **54 total**
- `test_tool_aliases.py` — coverage + budget gate

**Exit:** ≤45 aliases, each tied to benchmark case.

---

## Wave 5 — Auth & status noise

- Penalty `.auth.*` on calendar/drive/gmail/sheets intent without oauth tokens
- yandex vs google provider disambiguation (partially done)
- Penalty `yandex.music.*_status` on oauth queries without music context

**Benchmark additions:** calendar today (no auth in top-3), status yandex/google.

---

## Wave 6 — Download / export / send cluster

| Intent | Winner | Penalty competitors |
|--------|--------|---------------------|
| download + drive | drive.download_file | track_download, get_attachment |
| download + gmail | gmail.get_attachment | drive.download |
| download + mp3 | track_download | tracks_download_info |
| export + drive | export_file | auth.* |
| send + telegram | telegram.send_file | gmail.send_message |
| send + email | gmail.send_message | telegram.send_file |

**Benchmark additions:** ~5 cases.

---

## Wave 7 — Yandex Music deep pass (142 tools → 8 clusters)

| Cluster | Action |
|---------|--------|
| search (2) | Wave 1 |
| likes/dislikes (21) | Wave 2 |
| playlists (23) | Wave 3 + aliases |
| tracks generic (8) | existing penalties |
| users other (4) | presaves if needed |
| artists/albums browse (~30) | benchmark-driven only |
| rotor/history/charts (~20) | low priority |
| account/settings (~10) | Wave 5 |

**Exit:** Top prod yandex.music queries all Hit@5.

---

## Wave 8 — Google families bulk audit

70 drive + 45 gmail + 43 sheets + 24 tasks + 23 calendar + 18 maps.

Per family: 5–10 probe queries covering ~90% agent usage. Most CRUD tools never need rules — discovered via catalog+tags after skills.load.

**Deliverable:** Coverage matrix family × intent in this doc or audit notes.

---

## Wave 9 — Agent behavior layer

- Prompt search phrasing (`agent/prompts.py`)
- Tag hints: yandex.music, google.drive (`TAG_HINT_PROFILES`)
- search_tools_hint after use_tool
- Supervisor: N× search without use_tool
- skills.load before deep yandex.music

---

## Wave 10 — Monitoring & regression

- Benchmark ≥ 60 cases
- `eval_tool_search.py --providers api,keyword`
- Prod log: search query + top-5 + chosen tool
- Budget alerts: TOOL_ALIASES > 50, rules > 200 lines
- Bot restart after alias changes (embeddings rebuild)

---

## Timeline

| Wave | Focus | Cases | Hit@1 target |
|------|-------|-------|--------------|
| 0 ✅ | Refactor | 39 | ≥ 97% |
| 1 ✅ | Search siblings | 44 | ≥ 97% |
| 2 ✅ | Antonyms | 49 | ≥ 98% |
| 3 | List intent | ~65 | ≥ 98% |
| 4 | Aliases | ~65 | ≥ 99% |
| 5 | Auth noise | ~69 | ≥ 99% |
| 6 | Download/send | ~74 | ≥ 99% |
| 7 | Yandex clusters | ~85 | ≥ 99% |
| 8 | Google audit | ~95 | maintain |
| 9 | Agent prompts | — | prod |
| 10 | Monitoring | 60+ | sustained |

---

## Explicitly NOT doing

- Aliases on all 396 tools
- LLM rerank
- top_k > 5 as primary fix
- Per-tool rules for obscure CRUD (drive.create_reply, …)
- Embedding model change unless keyword ceiling hit

---

## Definition of Done (whole project)

1. Benchmark 60+ cases, Hit@1 ≥ 99%, MRR ≥ 0.99
2. Prod: liked tracks, search gmail/drive/tasks, list files → #1
3. Rules declarative, maintainable modules
4. Aliases ≤ 45, each traceable to a case
5. New tool checklist: probe → benchmark → rule/alias if collision

---

## New tool onboarding checklist

1. Add tool to registry
2. Run `scripts/export_tool_registry_audit.py`
3. Probe: `scripts/probe_search.py "agent-style query"`
4. If wrong #1 in top-5 → add benchmark case
5. Fix: alias (single-tool collision) or rule (pattern)
6. Run `scripts/check_tool_search_eval.py`
