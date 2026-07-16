# Graph Memory PR11 — Full Entity Resolution

## Status

**Implemented** (schema v10, opt-in flags, shadow-only).

Core ER modules live under `memory/resolution/`:

- `er_types.py`, `candidates.py`, `pairwise.py`, `cluster.py`, `canonical.py`
- `events_store.py`, `er_resolve.py`, `normalization_lang.py`

Wiring touches `schema.py`, `ids.py`, `config.py`, `pipeline.py`, `store.py`,
`rebuild.py`, `sources.py`, `jobs.py`, `scheduler.py`, and `main.py`.

## Config (`MEMORY_RESOLUTION_*`)

All PR11 flags default **off** so PR5 classic resolution stays byte-identical.

| Variable | Default | Notes |
|----------|---------|-------|
| `MEMORY_RESOLUTION_CANDIDATE_GENERATION_ENABLED` | `0` | Master ER switch |
| `MEMORY_RESOLUTION_MERGE_EVENTS_ENABLED` | `0` | Required when candidate generation is on |
| `MEMORY_RESOLUTION_FUZZY_BLOCKING_ENABLED` | `0` | Requires candidate generation |
| `MEMORY_RESOLUTION_FUZZY_MIN_TRIGRAM` | `0.6` | 0..1 |
| `MEMORY_RESOLUTION_CROSS_LANGUAGE_ENABLED` | `0` | Requires candidate generation |
| `MEMORY_RESOLUTION_CLUSTER_CRITIC_ENABLED` | `0` | Requires candidate generation |
| `MEMORY_RESOLUTION_RELINK_ON_INVALIDATION` | `0` | Re-enqueue ready candidates after source invalidation |
| `MEMORY_RESOLUTION_MAX_CANDIDATES` | `8` | >= 1 |

`RESOLVER_VERSION` stays **`2`** (flag-off compatibility). `ER_POLICY_VERSION` is **`1`**
and is included in job input/config hashes only when any PR11 flag is enabled.

## Schema v10

- `memory_entity_resolution_events` — reversible merge/split audit log
- `memory_entity_alias_equivalences` — cross-language alias pairs

## Tests

```bash
python -m unittest test_memory_resolution test_memory_resolution_pr11 test_memory_resolution_eval -v
python -m unittest discover -s . -p "test_memory*.py"
```

`test_memory_resolution_pr11.py` covers schema v10, trigram Jaccard, stable-id extraction,
person name-only blocking, unique-winner rule, canonical merge/split, config guards, and
flag-off classic smoke.

## Out of scope (this PR)

- Online Telegram prompt injection
- Adversarial identity model beyond existing link critics
- Full cross-language equivalence seeding at scale
- Lineage links for resolution events (optional; not wired)
- Production canary rollout (PR13)

## Enable shadow stack with ER (example)

```env
MEMORY_WORKER_ENABLED=1
MEMORY_VERIFICATION_ENABLED=1
MEMORY_RESOLUTION_ENABLED=1
MEMORY_RESOLUTION_CANDIDATE_GENERATION_ENABLED=1
MEMORY_RESOLUTION_MERGE_EVENTS_ENABLED=1
```

Add fuzzy / cross-language / cluster-critic flags only after candidate generation is on.
