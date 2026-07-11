# PR4 evaluation and anti-overfitting policy

## Purpose

PR4 quality is measured on semantic verification behavior, not on agreement with a
pack that was repeatedly edited after observing model output. A score from a
development pack is diagnostic only and cannot establish the 95% release target.

## Pack roles

- `verification_v1`: reviewed PR4 smoke regression pack.
- `verification_v2`: development/stability regression pack. Its cases and gold have
  already been used to drive implementation changes, so it is not a holdout.
- `verification_v3`: development scenario pack. Its draft gold was calibrated from
  live extraction output, so it is not a holdout.
- The next independent pack must use a new pack id and cases that have not been used
  to change prompts, post-processors, contracts, or verifier routing.

## Semantic policy fixed before holdout creation

1. A one-shot action command is context-scoped and is not a durable preference.
   It becomes a task only when the user explicitly creates a reminder/to-do/task or
   states an open responsibility.
2. A habitual statement such as "I only drink ..." is a durable preference. The
   complete bounded value is retained; it must not be generalized into a global
   dietary restriction.
3. Intolerance and allergy are different concepts. Intolerance maps to a bounded
   dietary constraint; it must not map to `allergic_to`.
4. Explicit negation is preserved. For a negative proposition containing
   `no longer`/`больше не`, the negative state is valid from the source timestamp.
5. Reported speech keeps the proposition subject separate from the reporter and
   uses `reported`, unknown polarity, possible commitment, and confirmation.
6. Direct quotes remain `quoted` and are never flattened into reported assertions.
7. `sibling_of` uses the established canonical orientation: the named person is
   `person`; the counterpart is `related_to`. Symmetry is semantic, but argument
   orientation must remain deterministic.
8. Corrections require explicit `old` and `new`. Post-processing may stitch prior
   evidence and normalize entity references but must not invent a missing value.
9. Tool facts may bypass the LLM verifier only when every material literal and
   normalized event time is copied from an authoritative JSON payload.
10. Temporal precision must reflect the cue (`month`, `season`, `day`, etc.); an ISO
    value or `second` precision must not be invented from a coarse cue.

## Holdout construction rules

- 40 cases minimum: at least 18 Russian, 18 English, and 4 mixed/multilingual.
- At least 12 hard negatives and 8 multi-turn cases.
- Cover negation, correction, reported/quoted speech, uncertainty, kinship,
  preferences, tasks/goals, temporal scope, tool authority, and abstention.
- Do not copy names, objects, places, dates, or exact templates from v1-v3.
- Gold is written from the semantic policy above before the first live run.
- Every fixture receives human review. The pack is not eligible for release gating
  while any fixture or expectation is `draft`.
- After the first live run, fixture text, expected candidates, and expected verifier
  outcomes are immutable. A genuine gold defect requires a new pack version and a
  written review note; it is never silently corrected in place.

## Release gate

Run the locked holdout three times with the production model profile and medium
reasoning. Each run must satisfy:

- case pass rate >= 95%;
- candidate precision and recall >= 95%;
- verification precision and recall >= 95%;
- ready-for-resolution precision >= 95%;
- forbidden advancement count = 0;
- wrong speaker count = 0;
- malformed accepted output count = 0;
- pointer ownership, dereference, and exact quote accuracy = 100%;
- harness errors = 0.

The release result is the minimum score across the three runs, not the average or
best run.
