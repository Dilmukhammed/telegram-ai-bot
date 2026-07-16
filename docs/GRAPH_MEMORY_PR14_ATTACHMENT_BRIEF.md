# Graph Memory PR14 — Attachment Engine (Full)

Status: **to implement** (shadow-only, default off).  
Depends on: PR5–12 (beliefs, graph, hybrid retrieval patterns, ER critics, summaries corpus).  
Out: PR10 photos, PR13 prompt injection, person name-merge.

---

## 1. Goal

After a durable belief/concept is resolved, decide **where it attaches** in the existing user graph:

```text
alias_of | instance_of | subtype_of | cuisine_of | topic_of
| part_of | located_in | same_as (concepts only)
| inferred_preference | corroborates | abstain
```

Preserve specificity (Kartoffelsalat stays). Prefer abstain over wrong link.  
**Never** use this engine for person identity (that stays PR11 stable-id only).

Example:

```text
likes(Kartoffelsalat)  →  cuisine_of → German
                       →  (later) inferred_preference likes_cuisine(German) [deferred]
```

---

## 2. Strength principles

1. **Many cheap retrievals → few LLM calls → even fewer graph writes.**
2. LLM may only choose ops/targets from a **closed shortlist** (no invent).
3. Extra LLM layers are **veto/disambiguation**, not creativity.
4. All writes go through a **reversible ledger** (`memory_attachment_events`).
5. Gradual promote: first hit ≠ durable inferred preference.
6. Domain packs (food/geo/org/topic) beat infinite generic layers.
7. Budget cascade: low risk skips deep critics; high risk runs full committee.

---

## 3. Pipeline layers (L0–L11)

```text
new durable belief / concept mention
  L0  Trigger gate
  L1  Local context pack (graph + beliefs + corrections)
  L2  Hybrid retrieval (exact/alias/lex/vector/graph/taxonomy) → RRF
  L3  Blocking & type firewall → shortlist K≤12
  L4  Hypothesis generator(s) LLM — ops over shortlist
  L5  Support critic LLM
  L6  Adversarial critic LLM
  L7  Alternative-hypothesis critic LLM
  L8  Cluster / taxonomy critic LLM
  L9  Gradual promote policy (deterministic)
  L10 Commit AttachmentEvent (+ optional deferred belief)
  L11 Telemetry / shadow eval
```

### L0 Trigger gate (no LLM)

Run only for schemas/kinds in:

- `preference`, `product`, `place`, `organization`, `project`, `topic`, `document_assertion` (optional)

Skip: person (non-stable), root self literals, pure typed literals with no attach domain, low-info tokens.

Output: `attach_domains[]` ∈ `{food, geo, org, topic, synonym, software}`.

### L1 Local context pack

Deterministic load:

- belief statement, schema, polarity, epistemic, entity ids/labels
- self active preferences in same domain family
- 1–2 hop graph neighbors for subject entities
- existing cuisine/topic/alias edges on those entities
- recent corrections/cessations in same cluster_key

### L2 Hybrid retrieval (parallel)

| Channel | Source |
|---------|--------|
| exact/alias | `memory_entity_aliases` + normalized labels |
| lexical | BM25-ish / token overlap on labels+aliases+summary text |
| vector | embeddings of entity labels + PR12 summaries + taxonomy nodes |
| graph | neighborhood priors (already likes German?) |
| curated taxonomy | offline triples `(child, relation, parent)` |

Fuse with RRF (reuse `memory/retrieval/fusion.py` patterns). Cap raw hits before L3.

### L3 Firewall

Drop:

- cross-user
- incompatible types (dish↛person, etc.)
- provisional-only targets for durable ops
- self-loops / duplicate of existing active attachment
- blocked domains

Keep ≤12. Empty shortlist → **abstain** (no LLM).

### L4–L8 LLM committee

All structured JSON. Shared shortlist. Fail-closed.

| Layer | Job | Allowed |
|-------|-----|---------|
| L4 Hypothesis | 1–3 `(op, target_id, promote_preference?)` | shortlist ids only |
| L4b (optional flag) | second generator, different model profile | same; disagreement → abstain |
| L5 Support | supported / insufficient / malformed | no new targets |
| L6 Adversarial | attack link; supported means “attack failed / link ok” OR use contradicted=reject — **pick one schema and keep consistent with resolution critics** | no invent |
| L7 Alt-hyp | best competing target/op from shortlist | no invent |
| L8 Cluster | taxonomy/consistency veto | veto only |

**Accept rule:**

```text
L4 non-empty unique winner
AND L5 supported
AND L6 does not reject
AND L7 does not strictly prefer another target
AND L8 ok
```

Else abstain (or write `possible` audit event without graph edge — flag-gated).

### L9 Gradual promote (deterministic)

| Op | 1st accepted | Corroboration (2+ / cluster) | User explicit same claim |
|----|--------------|------------------------------|---------------------------|
| `alias_of` | deferred edge | durable | durable |
| `cuisine_of` / `topic_of` / `instance_of` / `subtype_of` / `part_of` / `located_in` | deferred edge | durable | durable |
| `same_as` (concepts) | always full critics; deferred first | durable rare | — |
| `inferred_preference` | **never** on first dish alone | deferred after policy | durable |
| `corroborates` | belief-support link only | — | — |

Corroboration examples:

- ≥2 distinct dishes with `cuisine_of` → same cuisine
- existing durable `likes_cuisine(German)` + new dish
- user text explicitly states cuisine

### L10 Commit

1. Insert `memory_attachment_events` (active)
2. Optionally insert deferred/durable inferred belief via resolution-compatible path **or** graph-only typed edge from attachment materializer
3. Enqueue graph outbox / summary dirty for endpoints
4. Store critic verdicts for explainability

### L11 Telemetry

Counters: attach attempts, abstain, accept by op, LLM calls/belief, false-link rate (eval), veto by layer.

---

## 4. Budget cascade

| Risk class | Layers run | Max LLM calls |
|------------|------------|---------------|
| curated taxonomy exact + high lexical | L5 only or deterministic accept | 0–1 |
| mid hybrid score | L4+L5+L6 | 3 |
| `inferred_preference` / `same_as` | L4–L8 (+L4b if enabled) | 6 |
| ambiguous / near person | abstain | 0 |

Config: `MEMORY_ATTACHMENT_MAX_LLM_CALLS` (default 6). Exceed → abstain + log.

---

## 5. Negative knowledge

Persist rejected pairs from L6/L7/L8:

```text
(user_id, source_entity_id, op, target_entity_id, reason, created_at)
```

Skip re-proposing for TTL / until new corroborating evidence arrives.

---

## 6. Domain packs

Prompt + allowed ops + curated prior files per domain:

| Pack | Allowed ops (subset) |
|------|----------------------|
| `food` | cuisine_of, alias_of, topic_of, inferred_preference |
| `geo` | located_in, part_of, alias_of |
| `org` | alias_of, same_as, part_of |
| `topic` | topic_of, subtype_of, alias_of |
| `software` | subtype_of, alias_of, topic_of |

Curated taxonomy seed (food): `memory/attachment/taxonomy/food_v1.jsonl`  
Format: `{"child":"kartoffelsalat","child_aliases":["картофельный салат"],"op":"cuisine_of","parent":"german_cuisine","parent_aliases":["немецкая","german"],"language":"de"}`

---

## 7. Package layout

```text
memory/attachment/
  __init__.py
  schemas.py              # versions, ops, records, AttachmentConfig
  ids.py                  # or memory/ids.py helpers
  trigger.py              # L0
  context.py              # L1 pack
  retrieve.py             # L2 hybrid
  firewall.py             # L3
  hypotheses.py           # L4 prompts/parser/json_schema
  critics.py              # L5–L8
  policy.py               # L9 gradual + risk class
  negative.py             # rejected pairs
  taxonomy.py             # curated loaders
  events_store.py         # ledger CRUD
  store.py                # optional inferred belief helpers
  jobs.py                 # attach_analyze stage
  processor.py            # worker processor
  scheduler.py            # enqueue on durable belief heads / outbox hook
  materializer.py         # events → graph edges / deferred beliefs
  telemetry.py
  taxonomy/
    food_v1.jsonl
    geo_v1.jsonl          # optional small seed
```

Wire hooks:

- After durable belief head commit / graph materialize success → mark attach dirty or enqueue job
- Prefer job stage `attach_analyze` with maintenance source (mirror summaries)
- `main.py` + `scripts/graph_lab.py` register when flags on

---

## 8. Schema v12

Bump `SCHEMA_VERSION = 12`.

```sql
CREATE TABLE IF NOT EXISTS memory_attachment_events (
    event_id              TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    op                    TEXT NOT NULL,
    source_belief_id      TEXT,
    source_entity_id      TEXT NOT NULL,
    target_entity_id      TEXT NOT NULL,
    domain_pack           TEXT NOT NULL,
    tier                  TEXT NOT NULL,  -- curated|hybrid|llm_committee
    status                TEXT NOT NULL,  -- active|reverted|possible
    utility_class         TEXT NOT NULL,  -- deferred|durable
    evidence_json         TEXT NOT NULL,  -- belief_ids, hit_ids, scores
    evidence_hash         TEXT NOT NULL,
    critic_report_json    TEXT,
    layer_trace_json      TEXT NOT NULL,  -- per-layer verdicts
    input_hash            TEXT NOT NULL,
    resolver_version      TEXT NOT NULL,
    attachment_version    TEXT NOT NULL,
    supersedes_event_id   TEXT,
    graph_revision        INTEGER,
    created_at            TEXT NOT NULL,
    UNIQUE(user_id, op, source_entity_id, target_entity_id, evidence_hash, attachment_version)
);

CREATE INDEX IF NOT EXISTS idx_memory_attach_user_status
    ON memory_attachment_events(user_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_attach_source
    ON memory_attachment_events(source_entity_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_attach_target
    ON memory_attachment_events(target_entity_id, status);

CREATE TABLE IF NOT EXISTS memory_attachment_negatives (
    negative_id           TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    source_entity_id      TEXT NOT NULL,
    op                    TEXT NOT NULL,
    target_entity_id      TEXT NOT NULL,
    reason                TEXT NOT NULL,
    layer                 TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'active',
    expires_at            TEXT,
    created_at            TEXT NOT NULL,
    UNIQUE(user_id, source_entity_id, op, target_entity_id)
);

CREATE TABLE IF NOT EXISTS memory_attachment_dirty (
    dirty_id              TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    belief_id             TEXT NOT NULL,
    not_before            TEXT NOT NULL,
    lease_until           TEXT,
    reason                TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE(user_id, belief_id)
);

-- optional embedding cache for attachment corpus
CREATE TABLE IF NOT EXISTS memory_attachment_embeddings (
    embed_id              TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    object_kind           TEXT NOT NULL,  -- entity|taxonomy|summary
    object_id             TEXT NOT NULL,
    model_name            TEXT NOT NULL,
    embedding_json        TEXT NOT NULL,
    content_hash          TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE(user_id, object_kind, object_id, model_name)
);
```

IDs: `make_attachment_event_id`, `make_attachment_negative_id`, `make_attachment_dirty_id` in `memory/ids.py`.

Downgrade: flags off; tables additive.

---

## 9. Config flags (all default off except verify-when-gen pattern)

```text
MEMORY_ATTACHMENT_ENABLED=0
MEMORY_ATTACHMENT_GENERATION_ENABLED=0
MEMORY_ATTACHMENT_VERIFY_ENABLED=1
MEMORY_ATTACHMENT_TWO_GENERATOR_ENABLED=0
MEMORY_ATTACHMENT_VECTOR_ENABLED=1
MEMORY_ATTACHMENT_CURATED_TAXONOMY_ENABLED=1
MEMORY_ATTACHMENT_INFERRED_PREFERENCE_ENABLED=1
MEMORY_ATTACHMENT_WRITE_GRAPH_EDGES=1
MEMORY_ATTACHMENT_WRITE_POSSIBLE_EVENTS=0
MEMORY_ATTACHMENT_SCAN_INTERVAL_SECONDS=30
MEMORY_ATTACHMENT_SCAN_BATCH_SIZE=20
MEMORY_ATTACHMENT_DEBOUNCE_SECONDS=2
MEMORY_ATTACHMENT_MAX_CANDIDATES=12
MEMORY_ATTACHMENT_MAX_LLM_CALLS=6
MEMORY_ATTACHMENT_MODEL_PROFILE=extraction
MEMORY_ATTACHMENT_SUPPORT_MODEL_PROFILE=extraction
MEMORY_ATTACHMENT_ADVERSARIAL_MODEL_PROFILE=agent
MEMORY_ATTACHMENT_CLUSTER_MODEL_PROFILE=agent
MEMORY_ATTACHMENT_MAX_TOKENS=1536
```

`validate_memory_config`:

- attachment → graph + worker + resolution
- generation → attachment
- verify → generation
- inferred_preference → generation
- vector → attachment (soft; if embeddings unavailable, lexical+taxonomy only)

Versions: `ATTACHMENT_VERSION="1"`, `ATTACHMENT_PROMPT_VERSION="attachment_committee_v1"`.

---

## 10. Graph materialization

Typed edges from active attachment events:

```text
edge_type = f"attach:{op}"   # e.g. attach:cuisine_of
from = source_entity node
to   = target_entity node
properties = {event_id, utility_class, domain_pack, tier}
```

Deferred attachments → dashed overlay in graph_lab (like deferred beliefs) OR materialize with `status=deferred` if graph schema allows; else lab overlay from events table.

Inferred preference beliefs (optional path): create deferred assertion/belief only when policy says so; reuse resolution utility=`deferred`.

---

## 11. graph_lab wiring

- Enable attachment flags in lab MemoryConfig (short debounce)
- Register processor + scheduler
- Toolbar: `attach_events`, `attach_dirty`
- API: `GET /api/attach?belief_id=` dry-run (run L0–L8, no commit)
- API: `GET /api/attach/events`
- After message settle (graph): show last attachment decisions in stack panel
- Dry-run UI button **Attach** on last belief

---

## 12. Tests

`test_memory_attachment.py`:

- L0 skips person
- L3 firewall drops cross-type
- curated Kartoffelsalat → German cuisine_of deterministic/high prior
- empty shortlist abstain (no LLM call)
- L7 prefers other target → abstain
- gradual: first cuisine_of deferred; second dish promotes inferred_preference deferred
- negative pair suppresses retry
- schema v12
- flag-off no jobs
- accept rule unique winner

`test_memory_attachment_critics.py` (optional): fake LLM models for L4–L8.

Eval fixtures: `memory/eval/fixtures/attachment_v1/`  
Gates: `false_attach=0`, `false_inferred_preference=0`, `person_attach=0`.

---

## 13. Implementation order

1. Schema v12 + ids + events/negatives/dirty stores  
2. Taxonomy loader + L0/L1/L3 deterministic unit tests  
3. L2 retrieve (lexical+alias+taxonomy first; vector behind flag)  
4. L4–L8 prompts/schemas/parsers + fake-model tests  
5. L9 policy + commit path  
6. Processor/scheduler/jobs + hook from graph/belief commit  
7. Graph materializer / lab overlay  
8. Config + main + graph_lab  
9. Eval fixtures + brief PLAN footer  
10. Full `test_memory*.py` green  

---

## 14. Production readiness checklist

- [ ] Flags default off; validate_memory_config guards  
- [ ] Closed shortlist enforced in parser (reject unknown target_id)  
- [ ] Person never attached via this engine  
- [ ] First dish never durable inferred_preference  
- [ ] Reversible events (reverted status)  
- [ ] Negatives suppress loops  
- [ ] Budget cascade respected  
- [ ] graph_lab dry-run explainable layer_trace  
- [ ] Eval gates green  
- [ ] No prompt injection  

---

## 15. Explicit non-goals

- Face/photo identity  
- Person name merge / attachment  
- Embedding-only auto-write  
- Infinite uncapped LLM layers in default path  
- Using summaries as sole evidence for attach  
- PR13 canary inject  

---

## 16. One-sentence contract

**Hybrid retrieve a closed shortlist, run a budgeted multi-critic LLM committee that may only veto or choose among those candidates, commit reversible gradual attachments, and never invent entities or merge people.**

## 17. PR14 v2 hardening amendment (schema v13)

The original unique-winner contract above is retained as historical v1 context.
The production v2 contract supersedes it in these areas:

- L2 is multi-source: curated, alias, lexical, stored-vector, bidirectional
  two-hop graph paths, and semantic communities are fused deterministically;
- L4 returns up to five scored hypotheses with reason codes and evidence ids;
- the policy selects a compatible set (functional relations have one target;
  group/corroboration operations may fan out);
- L5 and L6 critique the complete set in two bounded calls and return a verdict
  for every `(op, target_id)`; only the supported subset is committed;
- schema v13 adds attachment dependencies and explicit constraints;
- negative preferences revert dependent inferred preferences and block stale
  rematerialization while keeping objective taxonomy edges;
- materialization is a diff/reconciliation operation and does not bump graph
  revision when the desired state is unchanged;
- a newer event supersedes the prior active event for the same relation;
- no network/LLM wait may run while an immediate SQLite write transaction is held.

Release evidence (2026-07-13): 296 memory regression tests passed; live smoke
10/10; three-run stability 30/30; focused historical safety 3/3; forbidden-edge
false positives 0. Runtime identifiers: attachment v2,
`attachment_committee_v2`, processor v4.

## 18. ReAct research integration (shadow v1)

An optional bounded read-only research phase now runs after L2 retrieval and
before L3 firewall. It can search entities, inspect directed edges, traverse at
most three hops, inspect communities, attachment history, conflicts and graph
revision. The phase receives no write tool and its output cannot alter the
shortlist, committee verdicts, policy, event ledger or graph materializer.

The trace and model-written conclusion are stored in the `attach_analyze` job
output under `research`. Provider failures, malformed actions, budget exhaustion
and internal tool errors fail open to the existing PR14 pipeline while the
research result itself records an abstaining/error status. `expand` and
`propose` are reserved configuration values; production v1 behavior remains
shadow-only until dedicated evaluation gates pass.
