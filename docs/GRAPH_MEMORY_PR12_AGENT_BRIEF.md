# PR12 — Summaries & Communities (shadow-only)

Belief-snapshot summaries with sentence-level belief support, typed communities, dirty-queue refresh, and optional shadow pack enrichment. **Never mutates agent prompts** (PR13).

## Package

`memory/summaries/` — schemas, eligibility, loaders, dirty queue, invalidator, generator, verifier, processor, scheduler, communities (`typed_domain_v1`), rebuild helpers.

## Schema v11

- `graph_summaries` — active | rejected | superseded | stale
- `graph_communities` — deterministic membership + optional label
- `graph_summary_dirty` — debounced targets
- `graph_summary_user_state` — incremental ops / full rebuild counter
- `memory_shadow_retrieval_runs.summary_pack_json` (migration 11 ALTER)

## Flow

```
belief head change → graph materializer → SummaryInvalidator → graph_summary_dirty
  → SummaryDirtyScheduler → summary_generate job → generator (beliefs only)
  → fail-closed verifier → graph_summaries
  → optional shadow pack (MEMORY_SUMMARIES_SHADOW_PACK_ENABLED)
```

Generators **never** read prior `content`. Rejected summaries keep the previous active row.

## Flags (defaults off except verify-when-gen)

| Flag | Default | Requires |
|------|---------|----------|
| `MEMORY_SUMMARIES_ENABLED` | 0 | `MEMORY_GRAPH_ENABLED=1`, worker |
| `MEMORY_SUMMARIES_GENERATION_ENABLED` | 0 | summaries |
| `MEMORY_SUMMARIES_VERIFY_ENABLED` | 1 | generation |
| `MEMORY_COMMUNITIES_ENABLED` | 0 | summaries + graph |
| `MEMORY_SUMMARIES_SHADOW_PACK_ENABLED` | 0 | summaries + shadow retrieval |

See `.env.example` for scan/debounce/rebuild/model settings.

## Tests

```bash
python -m unittest test_memory_summaries test_memory_communities -v
python -m unittest discover -s . -p "test_memory*.py"
```

## Out of scope (PR13+)

Prompt injection, canary controls, Louvain clustering, summary embeddings, forget UX.
