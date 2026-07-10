# Graph Memory PR 2 — Implementation Agent Brief

Implement PR 2 exactly as specified in `docs/GRAPH_MEMORY_PLAN.md`, section `23. Detailed PR 2 Design — Evaluation harness`.

## Read first

1. `docs/GRAPH_MEMORY_PLAN.md`
   - PR 0 evidence foundation;
   - PR 1 text-ingestion contract;
   - section 23 PR 2 contract.
2. Current PR 1 implementation:
   - `memory/ingestion/`;
   - `bot/memory_chat_adapter.py`;
   - `tools/tool_results/memory_adapter.py`;
   - `test_memory_ingestion.py`.
3. Existing memory primitives:
   - `memory/models.py`;
   - `memory/pointers.py`;
   - `memory/service.py`;
   - `memory/worker.py`.

Treat the checked-in implementation as evidence, not as the specification. If PR 1 disagrees with a strict fixture or invariant, fix PR 1 and add a focused regression test; do not weaken the fixture.

## Scope

Create:

```text
memory/eval/__init__.py
memory/eval/schemas.py
memory/eval/loader.py
memory/eval/subjects.py
memory/eval/matching.py
memory/eval/metrics.py
memory/eval/gates.py
memory/eval/runner.py
memory/eval/reports.py
memory/eval/fixtures/schema_v1.json
memory/eval/fixtures/text_v1/manifest.json
memory/eval/fixtures/text_v1/cases/*.json
memory/eval/fixtures/gates/text_v1.json
scripts/run_graph_memory_eval.py
test_memory_eval_schema.py
test_memory_eval_metrics.py
test_memory_eval_runner.py
```

Update `.gitignore` only if needed for `data/memory_eval/`.

## Hard boundaries

- No production extractor.
- No provider SDK or LLM call in the default path.
- No schema migration for production memory tables.
- No retrieval or prompt injection.
- No production database paths.
- No generated fixture padding.
- No fuzzy matching or LLM-as-judge in core scoring.
- No fake/gold-echo subject in the production CLI.
- No weakening gold expectations to fit current output.
- No fabricated human review metadata.

## Required implementation behavior

### Schemas and loader

- Use strict immutable dataclasses or equivalent typed models.
- Reject unknown fields and versions.
- Validate all symbolic references and Unicode spans.
- Compute canonical pack and gate hashes.
- Enforce the exact 64-case/16-smoke coverage contract.
- Keep fixture parsing independent from production stores.

### PR1IngestionSubject

- Use isolated temporary file-backed `chat.sqlite`, `tool_results.sqlite`, and `memory.sqlite` per fixture.
- Construct the real `ChatStore`, `ToolResultStore`, adapters, `MemoryService`, `TextIngestionRuntime`, and memory worker.
- Start ingestion first so the live-only baseline is established; then seed fixture events.
- Send actual post-commit notifications for normal cases.
- Omit notifications and wake the scanner for explicit catch-up cases.
- Resolve symbolic event aliases to actual message IDs/tool refs.
- Poll bounded deterministic completion conditions; do not rely on fixed sleeps as the success condition.
- Return actual sources, versions, jobs, segments, and pointer-verification results.
- Stop runtimes/workers and reset global stores in `finally`.

### CapturedOutputSubject

- Accept only strict, versioned JSON.
- Reject malformed candidates before scoring.
- Preserve subject/pipeline/processor metadata in reports.
- Never import a provider package.

### Matching and metrics

- Implement deterministic one-to-one matching.
- Count duplicate actual items as extras.
- Score forbidden patterns independently.
- Store raw numerator/denominator for every metric.
- Report micro, macro, language, slice, kind, and criticality breakdowns.
- Implement deterministic 95% Wilson intervals.
- Emit the stable failure codes from the PR 2 contract.

### Runner and reports

- Stable fixture ordering, filtering, sharding, case seeds, and output ordering.
- Network denied by default.
- Exit codes `0`, `1`, and `2` exactly as documented.
- Emit `run_manifest.json`, `cases.jsonl`, `summary.json`, `report.md`, and `junit.xml`.
- Implement compatible baseline comparison.
- Never write unbounded fixture payloads into JUnit failures.

## Corpus implementation

1. Author the 16 smoke fixtures first.
2. Make schema, coverage, matcher, and PR 1 ingestion tests pass for smoke.
3. Expand to exactly 64 fixtures using the required RU/EN/mixed and slice distribution.
4. Keep all fixtures `draft` until an actual human reviews them.
5. Run the full validation and generate a review report listing every fixture, expected candidates, forbidden candidates, and unresolved review notes.

The implementation can be code-complete with draft fixtures, but the release gate must continue to fail until all 64 fixtures have truthful human sign-off.

## Tests that must exist

- Strict schema acceptance/rejection matrix.
- Stable pack/gate hashes.
- Exact corpus and smoke coverage.
- Perfect, missing, extra, duplicate, forbidden, abstention, negation, uncertainty, speaker, temporal, and ambiguous one-to-one matching cases.
- Correct micro/macro/slice denominators and Wilson intervals.
- Deterministic replay and shard equivalence.
- Timeout, subject exception, malformed captured output, baseline incompatibility, and exit-code cases.
- File-backed PR 1 integration for chat/tool authority, chunking, pointer ownership/dereference, user isolation, catch-up, image placeholders, assistant tool calls, and atomic normalization.

## Verification

Run:

```text
python -m unittest test_memory test_memory_ingestion -v
python -m unittest test_memory_eval_schema test_memory_eval_metrics test_memory_eval_runner -v
python -m unittest test_chat_store test_chat_service_storage test_history_persist -v
python -m unittest test_tool_result_archive test_tool_call_arguments_archive test_tool_result_summarize_queue -v
python -m unittest test_run_trace test_llm_client -v
python -m compileall -q memory bot tools scripts main.py
git diff --check
```

Then run:

```text
python -m memory.eval.runner --pack text_v1 --subject ingestion --tier smoke --output data/memory_eval/pr2-smoke
python -m memory.eval.runner --pack text_v1 --subject ingestion --tier full --output data/memory_eval/pr2-full
```

Report:

- exact commands and exit codes;
- failed fixture IDs and stable failure codes;
- any PR 1 defects fixed;
- corpus review status;
- files intentionally left generated/untracked.

Do not claim PR 2 complete while the human-review gate is failing.
