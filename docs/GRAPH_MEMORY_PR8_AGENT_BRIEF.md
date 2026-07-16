# Graph Memory PR8 — Agent Brief (Shadow Retrieval)

## Status

Implemented (shadow-only, default off):

- schema v9: `memory_shadow_retrieval_runs`
- package `memory/retrieval/` — planner, entity/lexical/vector/graph/temporal/goal/chat/tool/document channels, RRF fusion, context pack, shadow runner
- `MEMORY_SHADOW_RETRIEVAL_ENABLED=0` by default
- `ChatService.generate_reply` schedules fire-and-forget preflight **before** `agent.run`
- **Hard rule:** pack is persisted + logged; prompt/history are never mutated (`prompt_mutated=False`)

## Channels

| Channel | Behavior |
|---------|----------|
| entity | exact alias / canonical label lookup |
| lexical | BM25 over belief heads + evidence quotes |
| vector | runtime embeddings over belief text (skipped if keyword-only / no provider) |
| graph | bounded 1–N hop traversal over active edges |
| temporal | validity windows + historical heads |
| goal | active goal/task schema/kind filter |
| chat | `search_chat_chunks` baseline |
| tool | `tool_ref` from chat hits + summarized tool results |
| document | explicit no-op until PR9/PR10 (`skip_reason=documents_and_images_require_pr9_pr10`) |

## Config

```text
MEMORY_SHADOW_RETRIEVAL_ENABLED=0
MEMORY_SHADOW_RETRIEVAL_TIMEOUT_SECONDS=2.0
MEMORY_SHADOW_RETRIEVAL_TOKEN_BUDGET=4000
MEMORY_SHADOW_RETRIEVAL_MAX_BELIEFS=24
MEMORY_SHADOW_RETRIEVAL_MAX_HOPS=3
```

Requires `MEMORY_RESOLUTION_ENABLED=1` or `MEMORY_GRAPH_ENABLED=1`.

## Pack

Bounded untrusted Memory Context Pack (`graph_revision`, entities, beliefs, uncertainties, contradictions, timelines, chat/tool hits, evidence pointers). Encoded with `untrusted=true` and an explicit non-executable instruction banner.

## Tests

```text
python -m unittest test_memory_retrieval -v
python -m unittest test_memory_resolution test_memory_graph test_memory_retrieval -q
```

## Out of this PR

- prompt injection / auto-inject (PR13)
- admin deep tools `memory.search` / `neighborhood` (PR13)
- core profile / summaries / communities (PR12)
- document/image evidence bodies (PR9/PR10)
- canary allowlists

## Next

PR9 documents, or PR13 canary after shadow telemetry review.
