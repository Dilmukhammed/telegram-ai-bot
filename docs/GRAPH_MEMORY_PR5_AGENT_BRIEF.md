# Graph Memory PR 5 — Detailed Implementation Plan

Status: **MVP A1 implemented (generic free-field resolution); critics wave in progress / landed.**
Closed `SCHEMA_CONTRACTS` catalog deferred — resolution uses role/mention/literal heuristics.

PR 5 is the first Stage 3 slice. It consumes final persisted PR 3 candidates that passed
independent PR 4 verification and produces user-scoped entities, immutable assertions, and
auditable belief revisions. It remains shadow-only and cannot affect Telegram answers.

## 1. Why the original PR 5 plan must change

The roadmap was written before the real PR 3/PR 4 boundary existed. The implemented boundary
is now:

```text
exact evidence
  -> strict structured extraction
  -> deterministic enrichment/contracts/discourse/temporal normalization
  -> persisted mentions and typed candidates
  -> deterministic verification preflight
  -> semantic support verdict
  -> risk-based adversarial verdict
  -> immutable verifier score
  -> candidate.status = ready_for_resolution
```

PR 5 must consume that final persisted representation. It must never read raw extraction JSON,
re-extract facts from evidence, or let a resolver rewrite the candidate.

Upstream changes that affect PR 5:

- arguments may be mention-backed or literal-backed while being semantically equivalent;
- normalized temporal values carry exact evidence/source-time provenance;
- verified uncertainty remains a valid candidate and must remain uncertain downstream;
- exact tool facts can be deterministically supported;
- correction extraction can supersede earlier candidates;
- verdicts/scores are immutable and versioned, while candidate status is a routing projection;
- model/policy changes require cache-busting input hashes;
- PR 4's verifier is not a hidden second extractor.

Current audited baseline:

- `verification_v1` is human-reviewed by `dimaa`;
- live `candidate_verification_v3` smoke passed 16/16 with no harness errors;
- the repository also contains a 30-case `verification_v2` draft. Draft v2 expectations must
  not be treated as reviewed release gold until separately signed.

## 2. Goal and boundary

```text
active ready_for_resolution candidate
  + active accepted PR 4 score/verdicts
  -> candidate_resolve job
  -> deterministic low-risk resolution
  -> conditional independent LLM link critic for risky exact alias reuse
  -> user-scoped entities and aliases
  -> immutable assertion
  -> versioned proposition/cluster keys
  -> minimal belief reconciliation
  -> immutable belief revision + current head
  -> separate utility decision
```

First vertical example:

```text
"I like Italian food."
  -> deterministic root user entity
  -> deterministic exact concept entity
  -> immutable preference assertion
  -> active belief revision
  -> utility = durable / graph_eligible
```

PR 5 writes no graph nodes or edges. PR 6 materializes eligible belief heads.

## 3. Quality strategy: deterministic core plus conservative LLM critic

Cost is not the reason to limit LLM usage. The reason is to keep identity and ledger behavior
stable, reproducible, and auditable.

The correct PR 5 architecture is hybrid:

### Always deterministic

- root user mapping;
- schema/role contracts;
- Unicode and typed-literal normalization;
- IDs and user ownership;
- exact stable external identifiers when available;
- assertion construction;
- proposition/cluster keys;
- temporal payload preservation;
- belief revision mechanics and support ledger;
- invalidation/rebuild;
- hard safety gates.

### Conditional LLM review

Use an independent reasoning-enabled LLM only when PR 5 is considering reusing an existing
entity for a separate mention and exact deterministic evidence is not sufficient by itself.
Initial reviewed types may include organization, project, and place.

The model receives a bounded proposed-link view:

- proposed existing entity and exact active aliases;
- new mention and bounded evidence;
- neighboring resolved arguments;
- source authority and time;
- explicit identifiers and known incompatibilities;
- no unrelated user history and no raw instructions outside bounded evidence.

The model may only verify the proposed link:

```json
{
  "schema_version": "1",
  "verdict": "supported|contradicted|insufficient|malformed",
  "scope_errors": [],
  "ambiguities": [],
  "missing_context": [],
  "corrected_resolution": null
}
```

It cannot propose a different entity, create a merge, rewrite an alias, rewrite the candidate,
or promote an assertion.

Decision rule:

```text
deterministically eligible proposed link
+ support critic = supported
+ adversarial critic = supported when risk policy requires it
  -> reuse exact entity

anything else
  -> do not merge; create/retain separate provisional entity
```

Model error, timeout, malformed output, disagreement, or insufficient context must fail closed
to separate provisional identity. A model can veto a risky link; it cannot bypass deterministic
ownership/type/identifier constraints.

This LLM layer should be immutable, cached, versioned, traced, and reasoning-enabled (medium by
default). Identical input must not be called repeatedly. A model/profile/prompt change creates a
new resolution input/version, never silently mutates an old decision.

### Why later PRs do not fully compensate

PR 7 handles temporal/correction/conflict reconciliation. PR 11 adds full entity resolution,
reversible merges/splits, cross-language aliases, and cluster critics. They do not justify
allowing weak identity decisions in PR 5: a wrong entity ID already contaminates assertions and
beliefs. PR 5 therefore prevents risky mistakes now while deferring broader merging.

## 4. Hard invariants

1. Only active `ready_for_resolution` candidates are eligible.
2. An active score with route `ready_for_resolution` for the configured PR 4 policy is required.
3. Non-ready, superseded, and invalidated candidates never create active assertions/beliefs.
4. Every lookup/link/write is scoped by `user_id`.
5. Equal person names never cause automatic reuse, even if an LLM suggests it.
6. No cross-user, cross-type, fuzzy, embedding-only, transliteration-only, or name-only merge.
7. Model output can only veto/confirm an already deterministic proposed link.
8. Assertion semantic payloads are immutable.
9. Belief changes create immutable revisions; only the head pointer is mutable.
10. Every belief revision has a complete assertion support ledger.
11. Uncertainty cannot become positive/negative certainty.
12. Truth and utility are separate versioned decisions.
13. No graph write, retrieval, prompt injection, or Telegram behavior change.
14. Scheduling, retry, crash recovery, and rebuild are idempotent.
15. Invalidation removes unsupported eligibility without erasing audit history.

## 5. Included and deferred work

Included:

- deterministic root user;
- exact typed concepts;
- exact stable-ID linking;
- conservative exact aliases for organization/project/place;
- conditional support/adversarial LLM link critics;
- mention-scoped provisional entities;
- immutable assertions and lineage;
- exact-proposition support aggregation;
- minimal active/uncertain/historical/unsupported belief revisions;
- deterministic utility baseline;
- scheduler, backfill, invalidation, rebuild, inspection, offline/live eval.

Deferred:

- automatic person merge;
- general fuzzy/embedding entity retrieval;
- cross-language alias merge;
- model-proposed targets;
- logical merge/split/relink events;
- cluster-wide entity consistency critic;
- temporal progression versus contradiction;
- field-aware correction application;
- model-selected winner between conflicting beliefs;
- wall-clock TTL;
- graph/retrieval/online memory.

## 6. Package layout

```text
memory/resolution/
  __init__.py
  schemas.py
  contracts.py
  normalization.py
  entities.py
  link_view.py
  prompts.py
  parser.py
  critics.py
  assertions.py
  propositions.py
  beliefs.py
  utility.py
  temporal.py
  jobs.py
  pipeline.py
  scheduler.py
  rebuild.py
  store.py
```

Evaluation:

```text
memory/eval/resolution_expectations.py
memory/eval/fixtures/resolution_v1.json
test_memory_resolution.py
test_memory_resolution_eval.py
```

## 7. Versions and configuration

```text
RESOLUTION_STAGE=candidate_resolve
RESOLVER_NAME=minimal_entity_assertion_resolver
RESOLVER_VERSION=1
RESOLUTION_PROMPT_VERSION=entity_link_verification_v1
ASSERTION_SCHEMA_VERSION=1
PROPOSITION_KEY_VERSION=1
RECONCILIATION_POLICY_VERSION=minimal_belief_v1
UTILITY_POLICY_VERSION=minimal_utility_v1
```

Disabled defaults:

```text
MEMORY_RESOLUTION_ENABLED=0
MEMORY_RESOLUTION_SCAN_INTERVAL_SECONDS=30
MEMORY_RESOLUTION_SCAN_BATCH_SIZE=100
MEMORY_RESOLUTION_LINK_SUPPORT_MODEL_PROFILE=extraction
MEMORY_RESOLUTION_LINK_ADVERSARIAL_MODEL_PROFILE=agent
MEMORY_RESOLUTION_MAX_TOKENS=1536
MEMORY_RESOLUTION_CONTEXT_CHARS=240
MEMORY_RESOLUTION_REASONING_EFFORT=medium
MEMORY_REQUIRED_VERIFICATION_POLICY_VERSION=verification_policy_v1
MEMORY_RECONCILIATION_POLICY_VERSION=minimal_belief_v1
MEMORY_UTILITY_POLICY_VERSION=minimal_utility_v1
```

Do not create a new provider endpoint. Reuse structured-output transport/profile handling and
omit temperature for reasoning models as PR 3/PR 4 already do.

## 8. Resolution contracts

`contracts.py` must cover every schema in `SCHEMA_CONTRACTS` and declare:

- candidate kind;
- role order;
- root-subject roles;
- entity/concept/literal roles;
- entity type by role;
- stable identifier fields if any;
- exact alias reuse allowed/forbidden;
- LLM critic risk level (`never`, `support`, `support_and_adversarial`);
- proposition identity fields;
- broad cluster/slot fields;
- cardinality (`single`, `set`, `event`);
- belief eligibility and default utility.

Unknown schema fails non-retryably. A known deliberately deferred schema may create an
assertion with `resolution_deferred`, but never an invented mapping.

## 9. Exact normalization

Identity normalization:

1. valid Unicode;
2. NFKC;
3. trim/collapse whitespace;
4. case-fold for exact lookup only;
5. preserve original display alias;
6. preserve JSON scalar type;
7. no implicit translation/transliteration/synonym expansion;
8. reuse PR 3 canonical literals rather than creating a competing dictionary.

Literal and mention representations of the same contract-declared exact concept resolve to the
same entity while keeping mention lineage.

## 10. Entity policy

### Root user

One deterministic active entity per `user_id`. Only explicit `self` in a contract-declared
subject/person role maps to it. Display-name equality never maps an entity to self.

### Concepts

Deterministic identity from user, concept namespace, schema/role contract, and canonical typed
value. No LLM is needed.

### Stable identifiers

Matching user/type/stable external identifier is deterministic. Explicit identifier conflict is
a hard veto that no model can override.

### Exact aliases for organization/project/place

The resolver retrieves only same-user, same-type active exact aliases. If no existing alias
exists, create a provisional entity. If one candidate exists, apply contract risk policy and
conditional critics. If several candidates exist, do not ask the model to select freely: create
a separate provisional entity or defer to PR 11.

### People other than self

Always mention-scoped provisional in PR 5 unless a contract contains a verified stable external
identifier. Equal names and LLM opinion are insufficient. Graph utility remains deferred.

### Other types/literals

Default to mention-scoped provisional or typed literal unless an explicit contract says
otherwise. Capitalization is not entity evidence.

## 11. Schema migration v6

Add these tables with user/status indexes and foreign keys:

### `memory_entities`

```text
entity_id PK
user_id
entity_type
identity_key
canonical_label
status: active|provisional|invalidated
resolver_version
created_at / updated_at
UNIQUE(user_id, entity_type, identity_key)
```

### `memory_entity_aliases`

```text
alias_id PK
user_id
entity_id FK
source_mention_id FK nullable
alias / normalized_alias / language
evidence_pointer_json nullable
status
created_at
```

### `memory_mention_links`

```text
link_id PK
user_id
mention_id FK
entity_id FK
decision: stable_identifier|exact_alias_verified|exact_concept|provisional_new
resolution_components_json
resolver_version
status
created_at
UNIQUE(mention_id, resolver_version)
```

### `memory_resolution_verdicts`

```text
resolution_verdict_id PK
user_id
mention_id
proposed_entity_id
role: support|adversarial
verdict
scope_errors_json / ambiguities_json / missing_context_json
critic_name/version/prompt_version
model_profile/model_name/reasoning_effort
input_hash/output_json
resolution_run_id
status / created_at
UNIQUE(mention_id, proposed_entity_id, role, critic_name, critic_version,
       prompt_version, input_hash)
```

### `memory_assertions`

```text
assertion_id PK
user_id / candidate_id FK
proposition_key / cluster_key
candidate_kind / schema_name / schema_version
resolved_arguments_json / attributes_json
polarity / epistemic_json / temporal_json
observed_at / recorded_at
assertion_schema_version / resolver_version
status: active|historical|invalidated
UNIQUE(candidate_id, assertion_schema_version, resolver_version)
```

### Belief ledger

```text
memory_beliefs(
  belief_id PK, user_id, proposition_key, cluster_key, schema_name, created_at,
  UNIQUE(user_id, proposition_key)
)

memory_belief_revisions(
  belief_revision_id PK, user_id, belief_id FK, input_set_hash,
  resolved_arguments_json, resolved_value_json, polarity, temporal_json,
  belief_status, utility_class, utility_reason_codes_json,
  confidence_components_json, reconciliation_policy_version,
  utility_policy_version, supersedes_revision_id, created_at,
  UNIQUE(belief_id, input_set_hash, reconciliation_policy_version,
         utility_policy_version)
)

memory_belief_heads(
  belief_id PK, user_id, belief_revision_id FK, updated_at
)

memory_belief_support(
  belief_revision_id FK, assertion_id FK, relation,
  weight_components_json,
  PRIMARY KEY(belief_revision_id, assertion_id, relation)
)
```

Assertions and belief revisions are insert-only semantic records. Status/head projections may
change atomically. Old revisions remain auditable.

## 12. IDs and resolved arguments

Add deterministic prefixes:

```text
ment_ entity
malias_ alias
mlink_ mention link
mrver_ resolution verdict
ma_ assertion
mb_ belief
mbr_ belief revision
```

IDs hash canonical semantic inputs and version constants, never wall time/run/provider/random
metadata.

Resolved arguments use a strict tagged envelope:

```json
{"role":"subject","value_kind":"entity","entity_id":"ment_..."}
```

```json
{"role":"amount","value_kind":"literal","literal":150}
```

No argument may contain both entity and literal values.

## 13. Proposition and cluster keys

Store both:

- `proposition_key`: exact normalized claim identity for support aggregation;
- `cluster_key`: broader contract-defined slot/group hint for PR 7.

Proposition key contains version, kind/schema/version, sorted resolved arguments, relevant
attributes, and contract-defined temporal identity. Polarity is excluded so exact positive and
negative assertions meet and become uncertain instead of producing two confident beliefs.

PR 5 does not choose winners across different proposition keys that merely share a cluster.

## 14. Assertion eligibility and lineage

Before creating an assertion, recheck:

- candidate/job/user ownership;
- exact `ready_for_resolution` status;
- configured acceptance policy;
- active ready score and required active verdicts;
- active sources/versions/segments/mentions;
- schema/role contract;
- temporal structural validity;
- resolution link decisions and verdict input hashes.

Required lineage:

```text
candidate/score/verdict -> assertion
mention -> mention_link -> entity
resolution_verdict -> mention_link
entity -> assertion
assertion -> belief_revision
belief_revision -> newer revision
```

Extend lineage endpoint ownership for every new kind.

## 15. Minimal belief policy

Reconcile only assertions sharing the exact proposition key:

1. certain active assertions with one polarity -> `active`;
2. unknown polarity or uncertain commitment -> `uncertain`;
3. active positive + negative -> `uncertain` with `polarity_conflict`;
4. all remaining support historical -> `historical`;
5. all support invalidated/deleted -> `unsupported`;
6. no recency, authority, or model-selected winner;
7. different values in one broad cluster are stored for PR 7, not overwritten.

Correction candidates create correction assertions and lineage. They may historicalize an old
assertion already marked upstream as superseded, but PR 5 does not synthesize a replacement
domain fact. Full correction/temporal reconciliation remains PR 7.

## 16. Utility policy

Separate classes:

```text
durable|contextual|temporary|deferred|ineligible
```

Deterministic baseline uses schema/kind, certainty, temporal scope, and identity status.
Reason codes include preference, constraint, active goal/task, temporary state, uncertain claim,
provisional identity, correction deferred, and schema ineligible.

An optional LLM utility suggestion may be stored in shadow telemetry later, but it must not
change truth status or graph eligibility in PR 5 without its own reviewed contract/eval. The
first quality-critical LLM use is entity-link veto/confirmation.

## 17. Jobs, cache stability, and scheduler

`candidate_resolve` jobs are candidate-targeted. Input hash includes:

- candidate ID;
- active score ID/verdict-set hash;
- required verification policy;
- resolver/assertion/proposition/reconciliation/utility versions;
- resolution contract hash;
- critic prompt/model profiles/reasoning configuration;
- proposed-link input hashes.

Scheduler selects bounded active ready candidates without current resolution output and also
detects recomputation after candidate/score/verdict invalidation, supersession, policy change,
new support, or stale belief head.

Critic verdicts are immutable and reusable. Operational failure fails closed to provisional
identity; it never promotes a link. The chosen fallback and failure reason are persisted so
replay is stable. A later retry/review requires an explicit new policy/input version rather than
silently changing the old result.

## 18. Atomic commit

1. claim lease;
2. load candidate, score, verdicts, mentions/evidence, exact entity candidates;
3. perform bounded critic calls outside transactions if required;
4. compute deterministic assertion/belief output;
5. open short `BEGIN IMMEDIATE`;
6. recheck lease, ownership, active source/version, ready status, active score, input hash;
7. insert verdicts/entities/aliases/links/assertion/belief revision/support idempotently;
8. compare-and-set belief head;
9. add lineage;
10. complete processor run/job in the same transaction.

No partial entity/assertion/belief commit is allowed. Extend `ProcessorOutput` with frozen typed
PR 5 artifacts or one validated `ResolutionBatch`.

## 19. Invalidation, supersession, and rebuild

Source/candidate invalidation:

- invalidates directly derived links/assertions/verdicts;
- preserves shared entity when other active aliases/support remain;
- never invalidates root user;
- enqueues bounded belief recomputation;
- creates historical/unsupported revision and moves head atomically;
- never deletes old audit rows.

Provide user-scoped dry-run/checkpointed rebuild from active ready PR 4 boundary records.
Incremental and rebuild semantic hashes/heads must match. Downgrade is disable + backup/rebuild,
not destructive reverse migration.

## 20. Evaluation

Default PR 5 eval is offline and deterministic around the PR 4 persisted boundary. A strict
captured input contains real candidate/mention/evidence/verdict/score shapes but no expected PR
5 output.

For critic-required cases, offline fixtures contain reviewed captured structured verdicts.
Separate opt-in live suites evaluate current critic models with reasoning enabled.

Subjects:

1. `PR5ResolutionSubject`: isolated DB, real scheduler/worker/processor/stores, captured PR 4
   boundary, no network.
2. `PR5ResolutionCriticSubject`: same path with live support/adversarial critics, explicit
   `--allow-network`.
3. Optional full ingestion->extraction->verification->resolution cross-stage subject.

Resolution corpus must cover:

- root self;
- literal/mention concept equivalence;
- stable identifier;
- exact org/project/place alias true match;
- same alias but different entity (critic veto);
- critic insufficient/disagreement/malformed/timeout fallback;
- equal person names never merged;
- cross-user identical aliases;
- uncertain and negative propositions;
- positive/negative conflict;
- tool task ownership;
- temporal preservation;
- correction/supersession;
- invalidation with/without remaining support;
- duplicate support;
- provisional identity utility deferral;
- non-ready candidate non-consumption.

Every lifecycle/link expectation requires human review.

## 21. Metrics and hard gates

Metrics:

- eligible candidate -> assertion recall;
- non-ready consumption;
- entity/link precision/recall by type;
- false merge and false split rate;
- root mapping;
- critic support/adversarial agreement, false accept/reject, fallback rate;
- resolved arguments and keys;
- belief head/support accuracy;
- uncertainty/negation preservation;
- utility accuracy;
- invalidation/rebuild/job completion;
- live stability across repeated runs/model versions.

Hard gates:

```text
review/schema validity                         100%
eligible assertion recall                      100%
non-ready consumed                             0
root mapping                                   100%
false person merge                             0
cross-user leakage                             0
critic-caused forbidden merge                  0
active belief without complete support         0
resolved arguments/keys                        100%
uncertainty and negation preservation          100%
pointer ownership/dereference                  100%
job completion/idempotent rebuild              100%
graph writes                                   0
```

Live critic gates must be measured on reviewed hard negatives, not only aggregate accuracy.
Model disagreement must reduce automation, never pick an arbitrary winner.

## 22. Test plan

### Schema/IDs

- fresh v6 and v5->v6 migration;
- exact indexes/FKs/version validation;
- deterministic IDs and typed normalization;
- duplicate/concurrent inserts;
- malformed status/JSON rejection.

### Deterministic resolution

- one root per user;
- exact concept literal/mention equivalence;
- stable identifier/type/ownership constraints;
- person name non-merge;
- cross-user and cross-type isolation;
- provisional fallback.

### Critics

- strict structured parser and repair cascade;
- prompt injection treated as evidence data;
- support/adversarial policy matrix;
- critic cannot propose target/rewrite;
- deterministic veto precedes model;
- timeout/malformed/disagreement fails closed;
- immutable cache/version/reasoning trace;
- no model call for root/concept/stable-ID path.

### Assertions/beliefs

- ready score eligibility;
- strict resolved argument envelope;
- observed versus recorded time;
- immutable assertion content/lineage;
- duplicate support aggregation;
- uncertainty/polarity conflict;
- no different-value winner;
- new input set creates revision/head CAS;
- historical/unsupported audit retention.

### Transactions/jobs/invalidation

- bounded scheduler/backfill/recompute;
- lease loss/retry/restart;
- failure injection at each insertion group;
- all-or-nothing commit;
- source/candidate/score/verdict invalidation;
- shared entity/root survival;
- rebuild equivalence/checkpoint resume.

### Regression

- PR 0–4 tests remain green;
- disabled feature creates no jobs/effect;
- Telegram prompts/answers unchanged;
- no graph/retrieval dependency.

## 23. Implementation order

1. Approve role/entity/cardinality/risk contracts and hybrid critic policy.
2. Add frozen schemas, IDs, normalization, and structured critic verdict contract.
3. Add schema v6 and migration tests.
4. Implement deterministic root/concept/stable-ID/provisional resolution.
5. Implement bounded proposed-link view, prompts, parser, support/adversarial critics.
6. Implement immutable resolution verdict store/cache.
7. Implement assertion/proposition/cluster construction and lineage.
8. Implement belief revisions, support, head CAS, and utility baseline.
9. Extend atomic `ProcessorOutput` commit.
10. Add job hashes, processor, scheduler, backfill/recompute.
11. Add invalidation and rebuild.
12. Add service/status/logging APIs.
13. Add offline captured-boundary eval and reviewed critic fixtures.
14. Pass offline hard gates and PR 0–4 regressions.
15. Run live critic smoke/full stability eval with reasoning.
16. Obtain human sign-off before release qualification.

## 24. Decisions to approve before coding

1. Exact alias-reuse types in v1 (`organization`, `project`, `place`).
2. Per-schema entity/concept/literal roles and cardinality.
3. Critic risk matrix and when adversarial review is mandatory.
4. Conservative fallback semantics and whether it is final for that policy version.
5. Proposition temporal identity and cluster fields.
6. No winner across different values until PR 7.
7. Correction assertion-only behavior until PR 7.
8. Utility allowlist/reason codes.
9. Whether release waits for separate `verification_v2` review.
10. Resolution/critic corpus size and live stability thresholds.

## 25. Completion criteria

PR 5 is complete when:

1. only active ready candidates with active ready PR 4 scores are consumed;
2. deterministic low-risk resolution is user-scoped and reproducible;
3. risky exact alias reuse requires immutable reviewed critic decisions;
4. model failure/disagreement cannot cause a merge;
5. equal person names never merge automatically;
6. literal/mention equivalence preserves lineage;
7. assertions are immutable and fully traceable;
8. proposition/cluster keys are deterministic/versioned;
9. belief changes create immutable revisions with atomic heads;
10. support ledger is complete;
11. uncertainty/negation/conflict are preserved without arbitrary winners;
12. invalidation/rebuild are correct and idempotent;
13. truth and utility are separate;
14. offline and live critic hard gates pass with human-reviewed expectations;
15. PR 0–4 regressions pass;
16. no graph/retrieval/prompt/Telegram effect exists.

## 26. Non-goals

- raw re-extraction or candidate rewriting;
- model-proposed entity targets;
- automatic person merge;
- general fuzzy/cross-language resolution;
- logical merge/split implementation;
- temporal/correction winner selection;
- graph/retrieval/online injection;
- enabling any feature by default.

PR 5 should leave PR 6 a clean input: supported, conservatively resolved, useful belief heads
with complete evidence, verifier, resolver, assertion, and belief lineage.
