# Graph Memory PR 3 — Implemented Contract

PR 3 adds shadow-only immediate text extraction on top of PR 0–2.

## Implemented boundary

```text
active normalized chat/tool segment
  -> candidate_extract job
  -> strict versioned model JSON
  -> exact-span validation
  -> deterministic mentions and typed candidates
  -> atomic persistence with job completion
```

Supported candidate kinds:

- `entity_attribute`
- `preference`
- `relation`
- `goal`
- `task`
- `state`
- `correction`
- `event`

No entity resolution, verification, graph writes, retrieval, or prompt injection is included.

## Production controls

```text
MEMORY_EXTRACTION_ENABLED=0
MEMORY_EXTRACTION_MODEL_PROFILE=summarize
MEMORY_EXTRACTION_MAX_TOKENS=4096
```

Extraction reuses the existing `LLMClient` profiles (`summarize` by default, or `agent` / `checker`).
No separate extraction model endpoint is required.

Extraction requires the memory worker. The default remains disabled. Normalization schedules extraction only for:

- `user_direct_statement` chat evidence;
- `tool_api_result` exact archived payloads.

Assistant prose, assistant tool arguments, conversation tool summaries, legacy payloads, and unsupported modalities do not call the extraction model.

## Persistence

Memory schema v4 adds:

- `memory_mentions`
- `memory_claim_candidates`
- `memory_candidate_evidence`

Mention and candidate IDs are deterministic over exact evidence, semantic content, extractor version, and prompt version. Persistence, lineage links, and job completion share one SQLite transaction. Source invalidation propagates to mentions and candidates.

## Evaluation

The PR 2 runner supports:

```text
python -m memory.eval.runner \
  --pack text_v1 \
  --subject extraction \
  --tier smoke \
  --allow-network \
  --output data/memory_eval/pr3-smoke
```

Network access is denied unless `--allow-network` is explicit. The production ingestion, worker, prompt, parser, and persistence path run inside isolated temporary databases. Runtime mention IDs are mapped to gold semantic mention references before candidate scoring.

The checked-in `text_v1` corpus is human-reviewed. Extraction gates are active for the
`extraction` subject. A live run is release-qualified only after smoke/full extraction eval
passes with `--allow-network`.

## Verification

```text
python -m unittest test_memory test_memory_ingestion test_memory_extraction -v
python -m unittest test_memory_eval_schema test_memory_eval_metrics test_memory_eval_runner test_memory_eval_subjects -v
python -m compileall -q memory bot tools scripts main.py
git diff --check
```
