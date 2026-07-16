# Graph Memory PR6 — Agent Brief (MVP)

## Status

Implemented (shadow-only, default off):

- schema v8: `graph_nodes`, `graph_edges`, `graph_outbox`, `graph_revisions`
- package `memory/graph/` — store, outbox, materializer, rebuild, explain, scheduler
- outbox enqueue on belief head CAS (resolution commit + invalidation recompute)
- eligibility: `belief_status=active` AND `utility_class=durable`
- free-field edges: `edge_type = "{kind}:{schema_name}"`
- `MEMORY_GRAPH_ENABLED=0` by default; `/memory_explain <belief_id>` admin read-only

Not in this slice: summaries, communities, retrieval, Telegram injection, event nodes.

PR7 correction/cessation winners ride the same outbox (historical REMOVE + durable UPSERT).

## Vertical

`"I like Italian food."` → durable preference belief → `preference:likes` edge
(`self` → `Italian food`) → `explain` returns exact quote.

## Config

```text
MEMORY_RESOLUTION_ENABLED=1   # required when graph is on
MEMORY_GRAPH_ENABLED=0
MEMORY_GRAPH_SCAN_INTERVAL_SECONDS=30
MEMORY_GRAPH_SCAN_BATCH_SIZE=100
```

## Tests

```text
python -m unittest test_memory_graph -v
```

## Next

PR8 shadow retrieval after graph + PR7 MVP are review-stable.
