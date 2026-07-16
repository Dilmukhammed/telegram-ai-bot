# Graph Memory PR7 — Agent Brief (Temporal Reconciliation MVP)

## Status

Implemented (shadow-only; rides on `MEMORY_RESOLUTION_ENABLED`):

- `RECONCILIATION_POLICY_VERSION = temporal_belief_v1`
- `memory/resolution/temporal.py` — evidence-linked prior lookup + correction/cessation apply plans
- Correction apply: historicalize prior domain assertions, synthesize winner domain assertion, recompute belief heads
- Domain winner → `active` + `durable`; meta correction belief stays `deferred` (`correction_deferred` / `correction_lineage`)
- Graph outbox via existing head CAS (Italian REMOVE, German UPSERT)
- Rebuild/invalidation uses shared `reconcile_belief`

## Vertical

```text
"I like Italian food."
  → preference belief active+durable → solid preference edge

"Actually I prefer German food."  (corrects_preference, evidence supports prior segment)
  → Italian assertion/belief → historical (+ graph REMOVE)
  → German preference assertion/belief → active+durable (+ graph UPSERT)
  → corrects_* assertion kept as lineage (non-materializable)
```

## Boundary

**In**

- Field-aware preference correction winners
- Ready negative/cessation that evidence-links a prior positive (same schema)

**Out**

- TTL, alternative dates, disputed UX, cluster LLM critics
- 100-fixture corpus (unit/integration tests cover the vertical)
- PR4 `insufficient` routing for unlinked cessations
- Provisional identity promotion (PR11)

## Production-shadow hardening

- `validate_memory_config`: worker required for extract/verify/resolve; verify required
  for resolve; resolution required for graph; policy versions must match
- `/memory_status`: stage flags + assertion / belief_head / active_graph_edge counts
- Draft fixtures: `memory/eval/fixtures/resolution_v1.json` (PR7 cases still `draft`)

## Tests

```text
python -m unittest test_memory_resolution.ResolutionInvalidationTests.test_correction_promotes_winner_and_historicalizes_loser -v
python -m unittest test_memory_resolution.ResolutionInvalidationTests.test_cessation_historicalizes_prior_positive -v
python -m unittest test_memory_resolution.BeliefReconcileTests test_memory_resolution.ConfigStageGuardTests test_memory_resolution.TemporalUnitTests -v
python -m unittest test_memory_resolution test_memory_graph test_memory_resolution_eval -v
```

## Next

PR4 cessation routing when prior relation exists; PR11 entity merge; full PR7 corpus/critics; PR8 shadow retrieval.
