# Graph Memory PR 4 — Implemented Contract

PR 4 adds shadow-only independent verification after the final PR 3 extraction pipeline.

## Implemented boundary

```text
persisted proposed/needs_confirmation candidate
  -> candidate-targeted candidate_verify job
  -> deterministic ownership/evidence/schema/epistemic preflight
  -> strict structured support verdict
  -> risk-based strict structured adversarial verdict
  -> versioned score and acceptance policy
  -> atomic routing status update
```

Verification reads the immutable candidate, resolved mentions, exact evidence, bounded
context, source type, and authority. It never verifies raw extraction JSON and never
rewrites a candidate.

## Structured verdict v1

```json
{
  "schema_version": "1",
  "verdict": "supported",
  "evidence_directness": "direct",
  "scope_errors": [],
  "ambiguities": [],
  "missing_context": [],
  "corrected_candidate": null
}
```

Allowed verdicts are `supported`, `contradicted`, `insufficient`, and `malformed`.
`corrected_candidate` is intentionally `null` in v1 so verification cannot become a
hidden second extractor.

## Persistence

Memory schema v5 adds:

- optional `target_kind` / `target_id` on persistent jobs;
- `memory_candidate_verdicts`;
- `memory_candidate_scores`.

Verdicts and scores are immutable, deterministic, versioned artifacts. The current
candidate `status` and `acceptance_policy` are a denormalized routing projection.
Verdict/score writes, candidate routing, lineage, processor-run completion, and job
completion share one SQLite transaction.

## Lifecycle

PR 4 routes candidates to:

- `ready_for_resolution`;
- `needs_confirmation`;
- `insufficient`;
- `contradicted`;
- `rejected`.

Operational model/parser failures leave the candidate unadvanced and are recorded on
the job/processor run. Source deletion invalidates candidates, verdicts, and scores.
A later explicit correction can supersede a candidate that was already verified.

## Scheduler and backfill

`VerificationScheduler` scans a bounded batch of active `proposed` and
`needs_confirmation` candidates without a current verifier verdict. Jobs are
candidate-targeted and deterministic, so repeated scans and restarts are harmless.
The same path backfills candidates created before PR 4.

## Production controls

```text
MEMORY_VERIFICATION_ENABLED=0
MEMORY_VERIFICATION_SUPPORT_MODEL_PROFILE=extraction
MEMORY_VERIFICATION_ADVERSARIAL_MODEL_PROFILE=agent
MEMORY_VERIFICATION_MAX_TOKENS=2048
MEMORY_VERIFICATION_SCAN_INTERVAL_SECONDS=30
MEMORY_VERIFICATION_SCAN_BATCH_SIZE=100
MEMORY_VERIFICATION_CONTEXT_CHARS=240
MEMORY_VERIFICATION_POLICY_VERSION=verification_policy_v1
```

Verification requires the memory worker. It remains disabled by default and never
changes Telegram prompts or answers.

## Evaluation

```text
python -m memory.eval.runner \
  --pack verification_v1 \
  --subject verification \
  --tier smoke \
  --allow-network \
  --output data/memory_eval/pr4-smoke
```

The verification subject runs the real isolated ingestion, extraction, scheduler,
worker, verifier, persistence, and scoring path. Extraction metrics remain active
independently. Verification adds false-accept/false-reject, forbidden advancement,
scope, escalation, job-completion, and ready-for-resolution precision metrics.

`memory/eval/fixtures/verification_v1.json` is intentionally `draft`. The
`verification_fixtures_reviewed` gate remains red until a human reviews and signs off
the lifecycle expectations. Do not claim PR 4 release-qualified before that sign-off
and live smoke/full runs.

## Verification commands

```text
python -m unittest test_memory test_memory_ingestion test_memory_extraction test_memory_verification -v
python -m unittest test_memory_eval_schema test_memory_eval_metrics test_memory_eval_runner test_memory_eval_subjects -v
python -m compileall -q memory bot tools scripts main.py
git diff --check
```

PR 4 does not implement entity resolution, assertions, beliefs, graph writes,
retrieval, prompt injection, utility promotion, or synthetic multi-extractor grouping.
