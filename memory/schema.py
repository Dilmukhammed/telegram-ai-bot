from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 13

_MIGRATION_1_DDL = """
CREATE TABLE IF NOT EXISTS memory_schema_migrations (
    version              INTEGER PRIMARY KEY,
    applied_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_sources (
    source_id           TEXT PRIMARY KEY,
    user_id             INTEGER NOT NULL,
    session_id          TEXT,
    source_type         TEXT NOT NULL,
    source_ref          TEXT NOT NULL,
    ingested_at         TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',
    authority_class     TEXT NOT NULL,
    metadata_json       TEXT,
    UNIQUE(user_id, source_type, source_ref)
);

CREATE TABLE IF NOT EXISTS memory_source_versions (
    source_version_id   TEXT PRIMARY KEY,
    source_id           TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    mime_type           TEXT,
    occurred_at         TEXT,
    ingested_at         TEXT NOT NULL,
    pointer_json        TEXT NOT NULL,
    metadata_json       TEXT,
    status              TEXT NOT NULL DEFAULT 'active',
    supersedes_version_id TEXT,
    FOREIGN KEY(source_id) REFERENCES memory_sources(source_id),
    UNIQUE(source_id, content_hash)
);

CREATE TABLE IF NOT EXISTS memory_segments (
    segment_id           TEXT PRIMARY KEY,
    source_version_id    TEXT NOT NULL,
    parent_segment_id    TEXT,
    segment_type         TEXT NOT NULL,
    ordinal              INTEGER NOT NULL,
    text                 TEXT,
    pointer_json         TEXT NOT NULL,
    embedding_json       TEXT,
    normalizer_name      TEXT NOT NULL,
    normalizer_version   TEXT NOT NULL,
    input_hash           TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY(source_version_id) REFERENCES memory_source_versions(source_version_id)
);

CREATE TABLE IF NOT EXISTS memory_jobs (
    job_id               TEXT PRIMARY KEY,
    user_id              INTEGER NOT NULL,
    source_version_id    TEXT NOT NULL,
    stage                TEXT NOT NULL,
    status               TEXT NOT NULL,
    priority             INTEGER NOT NULL DEFAULT 0,
    attempts             INTEGER NOT NULL DEFAULT 0,
    max_attempts         INTEGER NOT NULL,
    model_profile        TEXT,
    input_hash           TEXT NOT NULL,
    processor_name       TEXT NOT NULL,
    processor_version    TEXT NOT NULL,
    prompt_version       TEXT,
    output_json          TEXT,
    not_before           TEXT,
    lease_owner          TEXT,
    lease_until          TEXT,
    last_error           TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    FOREIGN KEY(source_version_id) REFERENCES memory_source_versions(source_version_id)
);

CREATE TABLE IF NOT EXISTS memory_lineage (
    lineage_id           TEXT PRIMARY KEY,
    user_id              INTEGER NOT NULL,
    parent_kind          TEXT NOT NULL,
    parent_id            TEXT NOT NULL,
    child_kind           TEXT NOT NULL,
    child_id             TEXT NOT NULL,
    relation             TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    UNIQUE(user_id, parent_kind, parent_id, child_kind, child_id, relation)
);

CREATE TABLE IF NOT EXISTS memory_processor_runs (
    run_id               TEXT PRIMARY KEY,
    job_id               TEXT NOT NULL,
    user_id              INTEGER NOT NULL,
    processor_name       TEXT NOT NULL,
    processor_version    TEXT NOT NULL,
    prompt_version       TEXT,
    model_profile        TEXT,
    started_at           TEXT NOT NULL,
    completed_at         TEXT,
    outcome              TEXT,
    input_hash           TEXT NOT NULL,
    output_hash          TEXT,
    usage_json           TEXT,
    error_class          TEXT,
    error_message        TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_sources_user_type
    ON memory_sources(user_id, source_type, status);

CREATE INDEX IF NOT EXISTS idx_memory_source_versions_source
    ON memory_source_versions(source_id, ingested_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_jobs_claim
    ON memory_jobs(status, not_before, priority DESC, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_jobs_lease
    ON memory_jobs(status, lease_until);

CREATE INDEX IF NOT EXISTS idx_memory_jobs_user
    ON memory_jobs(user_id, status);

CREATE INDEX IF NOT EXISTS idx_memory_lineage_parent
    ON memory_lineage(user_id, parent_kind, parent_id);

CREATE INDEX IF NOT EXISTS idx_memory_lineage_child
    ON memory_lineage(user_id, child_kind, child_id);
"""


_MIGRATION_3_DDL = """
CREATE TABLE IF NOT EXISTS memory_ingestion_cursors (
    stream_name            TEXT PRIMARY KEY,
    cursor_json            TEXT NOT NULL,
    initialized_at         TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    last_scan_started_at   TEXT,
    last_scan_completed_at TEXT,
    last_error             TEXT,
    records_seen           INTEGER NOT NULL DEFAULT 0,
    registered_count       INTEGER NOT NULL DEFAULT 0,
    duplicate_count        INTEGER NOT NULL DEFAULT 0,
    failed_count           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS memory_ingestion_failures (
    stream_name      TEXT NOT NULL,
    item_key         TEXT NOT NULL,
    user_id          INTEGER,
    cursor_json      TEXT NOT NULL,
    status           TEXT NOT NULL,
    attempts         INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL,
    not_before       TEXT,
    error_class      TEXT,
    error_message    TEXT,
    first_failed_at  TEXT NOT NULL,
    last_failed_at   TEXT NOT NULL,
    resolved_at      TEXT,
    PRIMARY KEY(stream_name, item_key)
);

CREATE INDEX IF NOT EXISTS idx_memory_ingestion_failures_due
    ON memory_ingestion_failures(status, not_before, last_failed_at);

CREATE INDEX IF NOT EXISTS idx_memory_sources_type_ref_status
    ON memory_sources(source_type, source_ref, status)
"""

_MIGRATION_4_DDL = """
CREATE TABLE IF NOT EXISTS memory_mentions (
    mention_id           TEXT PRIMARY KEY,
    user_id              INTEGER NOT NULL,
    segment_id           TEXT NOT NULL,
    mention_type         TEXT NOT NULL,
    surface_text         TEXT NOT NULL,
    normalized_hint      TEXT,
    pointer_json         TEXT NOT NULL,
    extractor_name       TEXT NOT NULL,
    extractor_version    TEXT NOT NULL,
    prompt_version       TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY(segment_id) REFERENCES memory_segments(segment_id)
);

CREATE TABLE IF NOT EXISTS memory_claim_candidates (
    candidate_id          TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    candidate_kind        TEXT NOT NULL,
    schema_name           TEXT NOT NULL,
    schema_version        TEXT NOT NULL,
    arguments_json        TEXT NOT NULL,
    attributes_json       TEXT NOT NULL,
    polarity              TEXT NOT NULL,
    epistemic_json        TEXT NOT NULL,
    temporal_json         TEXT,
    canonical_hint        TEXT,
    status                TEXT NOT NULL,
    extraction_run_id     TEXT NOT NULL,
    acceptance_policy     TEXT,
    extractor_name        TEXT NOT NULL,
    extractor_version     TEXT NOT NULL,
    prompt_version        TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    FOREIGN KEY(extraction_run_id) REFERENCES memory_processor_runs(run_id)
);

CREATE TABLE IF NOT EXISTS memory_candidate_evidence (
    candidate_id          TEXT NOT NULL,
    segment_id            TEXT NOT NULL,
    evidence_relation     TEXT NOT NULL,
    pointer_json          TEXT NOT NULL,
    exact_quote           TEXT,
    context_pointer_json  TEXT,
    PRIMARY KEY(candidate_id, segment_id, pointer_json),
    FOREIGN KEY(candidate_id) REFERENCES memory_claim_candidates(candidate_id),
    FOREIGN KEY(segment_id) REFERENCES memory_segments(segment_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_mentions_user_status
    ON memory_mentions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_mentions_segment
    ON memory_mentions(segment_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_candidates_user_status
    ON memory_claim_candidates(user_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_candidate_evidence_segment
    ON memory_candidate_evidence(segment_id, candidate_id);
"""

_MIGRATION_5_DDL = """
ALTER TABLE memory_jobs ADD COLUMN target_kind TEXT;
ALTER TABLE memory_jobs ADD COLUMN target_id TEXT;

CREATE TABLE IF NOT EXISTS memory_candidate_verdicts (
    verdict_id            TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    candidate_id          TEXT NOT NULL,
    role                  TEXT NOT NULL,
    verdict               TEXT NOT NULL,
    evidence_directness   TEXT,
    scope_errors_json     TEXT NOT NULL,
    ambiguities_json      TEXT NOT NULL,
    missing_context_json  TEXT NOT NULL,
    corrected_candidate_json TEXT,
    verifier_name         TEXT NOT NULL,
    verifier_version      TEXT NOT NULL,
    prompt_version        TEXT NOT NULL,
    model_profile         TEXT,
    model_name            TEXT,
    input_hash            TEXT NOT NULL,
    output_json           TEXT NOT NULL,
    verification_run_id   TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY(candidate_id) REFERENCES memory_claim_candidates(candidate_id),
    FOREIGN KEY(verification_run_id) REFERENCES memory_processor_runs(run_id),
    UNIQUE(
        candidate_id, role, verifier_name, verifier_version,
        prompt_version, input_hash
    )
);

CREATE TABLE IF NOT EXISTS memory_candidate_scores (
    score_id              TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    candidate_id          TEXT NOT NULL,
    policy_version        TEXT NOT NULL,
    verdict_set_hash      TEXT NOT NULL,
    components_json       TEXT NOT NULL,
    route_status          TEXT NOT NULL,
    verification_run_id   TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY(candidate_id) REFERENCES memory_claim_candidates(candidate_id),
    FOREIGN KEY(verification_run_id) REFERENCES memory_processor_runs(run_id),
    UNIQUE(candidate_id, policy_version, verdict_set_hash)
);

CREATE INDEX IF NOT EXISTS idx_memory_jobs_target
    ON memory_jobs(target_kind, target_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_candidate_verdicts_candidate
    ON memory_candidate_verdicts(candidate_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_candidate_scores_candidate
    ON memory_candidate_scores(candidate_id, status, created_at);
"""

# PR5 MVP A1: entities/assertions/beliefs. Resolution verdicts (LLM critics) deferred.
_MIGRATION_6_DDL = """
CREATE TABLE IF NOT EXISTS memory_entities (
    entity_id             TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    entity_type           TEXT NOT NULL,
    identity_key          TEXT NOT NULL,
    canonical_label       TEXT NOT NULL,
    status                TEXT NOT NULL,
    resolver_version      TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE(user_id, entity_type, identity_key)
);

CREATE TABLE IF NOT EXISTS memory_entity_aliases (
    alias_id              TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    entity_id             TEXT NOT NULL,
    source_mention_id     TEXT,
    alias                 TEXT NOT NULL,
    normalized_alias      TEXT NOT NULL,
    language              TEXT,
    evidence_pointer_json TEXT,
    status                TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    FOREIGN KEY(entity_id) REFERENCES memory_entities(entity_id),
    FOREIGN KEY(source_mention_id) REFERENCES memory_mentions(mention_id)
);

CREATE TABLE IF NOT EXISTS memory_mention_links (
    link_id               TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    mention_id            TEXT NOT NULL,
    entity_id             TEXT NOT NULL,
    decision              TEXT NOT NULL,
    resolution_components_json TEXT NOT NULL,
    resolver_version      TEXT NOT NULL,
    status                TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    FOREIGN KEY(mention_id) REFERENCES memory_mentions(mention_id),
    FOREIGN KEY(entity_id) REFERENCES memory_entities(entity_id),
    UNIQUE(mention_id, resolver_version)
);

CREATE TABLE IF NOT EXISTS memory_assertions (
    assertion_id          TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    candidate_id          TEXT NOT NULL,
    proposition_key       TEXT NOT NULL,
    cluster_key           TEXT NOT NULL,
    candidate_kind        TEXT NOT NULL,
    schema_name           TEXT NOT NULL,
    schema_version        TEXT NOT NULL,
    resolved_arguments_json TEXT NOT NULL,
    attributes_json       TEXT NOT NULL,
    polarity              TEXT NOT NULL,
    epistemic_json        TEXT NOT NULL,
    temporal_json         TEXT,
    observed_at           TEXT,
    recorded_at           TEXT NOT NULL,
    assertion_schema_version TEXT NOT NULL,
    resolver_version      TEXT NOT NULL,
    status                TEXT NOT NULL,
    resolution_run_id     TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    FOREIGN KEY(candidate_id) REFERENCES memory_claim_candidates(candidate_id),
    FOREIGN KEY(resolution_run_id) REFERENCES memory_processor_runs(run_id),
    UNIQUE(candidate_id, assertion_schema_version, resolver_version)
);

CREATE TABLE IF NOT EXISTS memory_beliefs (
    belief_id             TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    proposition_key       TEXT NOT NULL,
    cluster_key           TEXT NOT NULL,
    schema_name           TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    UNIQUE(user_id, proposition_key)
);

CREATE TABLE IF NOT EXISTS memory_belief_revisions (
    belief_revision_id    TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    belief_id             TEXT NOT NULL,
    input_set_hash        TEXT NOT NULL,
    resolved_arguments_json TEXT NOT NULL,
    resolved_value_json   TEXT,
    polarity              TEXT NOT NULL,
    temporal_json         TEXT,
    belief_status         TEXT NOT NULL,
    utility_class         TEXT NOT NULL,
    utility_reason_codes_json TEXT NOT NULL,
    confidence_components_json TEXT NOT NULL,
    reconciliation_policy_version TEXT NOT NULL,
    utility_policy_version TEXT NOT NULL,
    supersedes_revision_id TEXT,
    created_at            TEXT NOT NULL,
    FOREIGN KEY(belief_id) REFERENCES memory_beliefs(belief_id),
    UNIQUE(
        belief_id, input_set_hash, reconciliation_policy_version,
        utility_policy_version
    )
);

CREATE TABLE IF NOT EXISTS memory_belief_heads (
    belief_id             TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    belief_revision_id    TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    FOREIGN KEY(belief_id) REFERENCES memory_beliefs(belief_id),
    FOREIGN KEY(belief_revision_id) REFERENCES memory_belief_revisions(belief_revision_id)
);

CREATE TABLE IF NOT EXISTS memory_belief_support (
    belief_revision_id    TEXT NOT NULL,
    assertion_id          TEXT NOT NULL,
    relation              TEXT NOT NULL,
    weight_components_json TEXT NOT NULL,
    PRIMARY KEY(belief_revision_id, assertion_id, relation),
    FOREIGN KEY(belief_revision_id) REFERENCES memory_belief_revisions(belief_revision_id),
    FOREIGN KEY(assertion_id) REFERENCES memory_assertions(assertion_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_entities_user_status
    ON memory_entities(user_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_entity_aliases_lookup
    ON memory_entity_aliases(user_id, normalized_alias, status);
CREATE INDEX IF NOT EXISTS idx_memory_mention_links_mention
    ON memory_mention_links(mention_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_assertions_user_prop
    ON memory_assertions(user_id, proposition_key, status);
CREATE INDEX IF NOT EXISTS idx_memory_assertions_candidate
    ON memory_assertions(candidate_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_beliefs_user
    ON memory_beliefs(user_id, schema_name);
CREATE INDEX IF NOT EXISTS idx_memory_belief_revisions_belief
    ON memory_belief_revisions(belief_id, created_at);
"""

_MIGRATION_7_DDL = """
CREATE TABLE IF NOT EXISTS memory_resolution_verdicts (
    resolution_verdict_id TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    mention_id            TEXT NOT NULL,
    proposed_entity_id    TEXT NOT NULL,
    role                  TEXT NOT NULL,
    verdict               TEXT NOT NULL,
    scope_errors_json     TEXT NOT NULL,
    ambiguities_json      TEXT NOT NULL,
    missing_context_json  TEXT NOT NULL,
    critic_name           TEXT NOT NULL,
    critic_version        TEXT NOT NULL,
    prompt_version        TEXT NOT NULL,
    model_profile         TEXT,
    model_name            TEXT,
    reasoning_effort      TEXT,
    input_hash            TEXT NOT NULL,
    output_json           TEXT NOT NULL,
    resolution_run_id     TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'active',
    created_at            TEXT NOT NULL,
    FOREIGN KEY(mention_id) REFERENCES memory_mentions(mention_id),
    FOREIGN KEY(proposed_entity_id) REFERENCES memory_entities(entity_id),
    FOREIGN KEY(resolution_run_id) REFERENCES memory_processor_runs(run_id),
    UNIQUE(
        mention_id, proposed_entity_id, role, critic_name, critic_version,
        prompt_version, input_hash
    )
);

CREATE INDEX IF NOT EXISTS idx_memory_resolution_verdicts_mention
    ON memory_resolution_verdicts(mention_id, status, created_at);
"""

_MIGRATION_8_DDL = """
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id              TEXT PRIMARY KEY,
    user_id              INTEGER NOT NULL,
    node_type            TEXT NOT NULL,
    source_record_id     TEXT NOT NULL,
    label                TEXT,
    properties_json      TEXT,
    embedding_json       TEXT,
    status               TEXT NOT NULL,
    graph_revision       INTEGER NOT NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    UNIQUE(user_id, node_type, source_record_id)
);

CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id              TEXT PRIMARY KEY,
    user_id              INTEGER NOT NULL,
    from_node_id         TEXT NOT NULL,
    to_node_id           TEXT NOT NULL,
    edge_type            TEXT NOT NULL,
    belief_id            TEXT NOT NULL,
    properties_json      TEXT,
    valid_from           TEXT,
    valid_to             TEXT,
    status               TEXT NOT NULL,
    graph_revision       INTEGER NOT NULL,
    payload_hash         TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    FOREIGN KEY(from_node_id) REFERENCES graph_nodes(node_id),
    FOREIGN KEY(to_node_id) REFERENCES graph_nodes(node_id),
    FOREIGN KEY(belief_id) REFERENCES memory_beliefs(belief_id),
    UNIQUE(user_id, belief_id, from_node_id, to_node_id, edge_type)
);

CREATE TABLE IF NOT EXISTS graph_outbox (
    event_id              TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    belief_id             TEXT NOT NULL,
    operation             TEXT NOT NULL,
    payload_hash          TEXT NOT NULL,
    status                TEXT NOT NULL,
    attempts              INTEGER NOT NULL DEFAULT 0,
    lease_until           TEXT,
    last_error            TEXT,
    created_at            TEXT NOT NULL,
    processed_at          TEXT
);

CREATE TABLE IF NOT EXISTS graph_revisions (
    user_id                 INTEGER PRIMARY KEY,
    current_revision        INTEGER NOT NULL,
    last_materialized_at    TEXT,
    materializer_version    TEXT NOT NULL,
    graph_schema_version    TEXT NOT NULL,
    belief_policy_version   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_user_status
    ON graph_nodes(user_id, status, node_type);
CREATE INDEX IF NOT EXISTS idx_graph_edges_user_status
    ON graph_edges(user_id, status, edge_type);
CREATE INDEX IF NOT EXISTS idx_graph_edges_belief
    ON graph_edges(belief_id, status);
CREATE INDEX IF NOT EXISTS idx_graph_edges_from
    ON graph_edges(from_node_id, status);
CREATE INDEX IF NOT EXISTS idx_graph_edges_to
    ON graph_edges(to_node_id, status);
CREATE INDEX IF NOT EXISTS idx_graph_outbox_claim
    ON graph_outbox(status, lease_until, created_at);
CREATE INDEX IF NOT EXISTS idx_graph_outbox_user
    ON graph_outbox(user_id, status);
"""

_MIGRATION_9_DDL = """
CREATE TABLE IF NOT EXISTS memory_shadow_retrieval_runs (
    run_id                TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    query_hash            TEXT NOT NULL,
    query_time            TEXT NOT NULL,
    graph_revision        INTEGER NOT NULL,
    memory_needed         INTEGER NOT NULL,
    plan_json             TEXT NOT NULL,
    channels_json         TEXT NOT NULL,
    pack_json             TEXT NOT NULL,
    latency_ms_json       TEXT NOT NULL,
    pack_token_estimate   INTEGER NOT NULL,
    belief_ids_json       TEXT NOT NULL,
    error                 TEXT,
    created_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_shadow_runs_user
    ON memory_shadow_retrieval_runs(user_id, created_at);
"""

_MIGRATION_10_DDL = """
CREATE TABLE IF NOT EXISTS memory_entity_resolution_events (
    event_id             TEXT PRIMARY KEY,
    user_id              INTEGER NOT NULL,
    op                   TEXT NOT NULL,
    winner_entity_id     TEXT NOT NULL,
    loser_entity_id      TEXT NOT NULL,
    cluster_key          TEXT,
    tier                 TEXT NOT NULL,
    evidence_json        TEXT NOT NULL,
    evidence_hash        TEXT NOT NULL,
    reason               TEXT NOT NULL,
    decided_by           TEXT NOT NULL,
    supersedes_event_id  TEXT,
    resolver_version     TEXT NOT NULL,
    resolution_run_id    TEXT,
    status               TEXT NOT NULL DEFAULT 'active',
    created_at           TEXT NOT NULL,
    FOREIGN KEY(winner_entity_id) REFERENCES memory_entities(entity_id),
    FOREIGN KEY(loser_entity_id) REFERENCES memory_entities(entity_id),
    UNIQUE(user_id, op, winner_entity_id, loser_entity_id, evidence_hash, resolver_version)
);
CREATE INDEX IF NOT EXISTS idx_memory_res_events_user_status
    ON memory_entity_resolution_events(user_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_res_events_loser
    ON memory_entity_resolution_events(loser_entity_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_res_events_winner
    ON memory_entity_resolution_events(winner_entity_id, status);

CREATE TABLE IF NOT EXISTS memory_entity_alias_equivalences (
    equivalence_id       TEXT PRIMARY KEY,
    user_id              INTEGER NOT NULL,
    normalized_alias_a   TEXT NOT NULL,
    language_a           TEXT,
    normalized_alias_b   TEXT NOT NULL,
    language_b           TEXT,
    entity_type          TEXT NOT NULL,
    source               TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'active',
    created_at           TEXT NOT NULL,
    UNIQUE(user_id, entity_type, normalized_alias_a, normalized_alias_b, source)
);
CREATE INDEX IF NOT EXISTS idx_memory_alias_equiv_lookup
    ON memory_entity_alias_equivalences(user_id, entity_type, normalized_alias_a, status);
"""

_MIGRATION_11_DDL = """
CREATE TABLE IF NOT EXISTS graph_summaries (
    summary_id             TEXT PRIMARY KEY,
    user_id                INTEGER NOT NULL,
    summary_type           TEXT NOT NULL,
    target_id              TEXT NOT NULL,
    content                TEXT NOT NULL,
    sentences_json         TEXT NOT NULL,
    belief_ids_json        TEXT NOT NULL,
    sentence_support_json  TEXT NOT NULL,
    input_hash             TEXT NOT NULL,
    model_profile          TEXT,
    prompt_version         TEXT NOT NULL,
    status                 TEXT NOT NULL,
    graph_revision         INTEGER NOT NULL,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_communities (
    community_id           TEXT PRIMARY KEY,
    user_id                INTEGER NOT NULL,
    community_type         TEXT NOT NULL,
    label                  TEXT,
    member_node_ids_json   TEXT NOT NULL,
    member_belief_ids_json TEXT NOT NULL,
    seed_node_id           TEXT NOT NULL,
    input_hash             TEXT NOT NULL,
    detector_version       TEXT NOT NULL,
    graph_revision         INTEGER NOT NULL,
    status                 TEXT NOT NULL,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    UNIQUE(user_id, community_type, seed_node_id, detector_version)
);

CREATE TABLE IF NOT EXISTS graph_summary_dirty (
    dirty_id               TEXT PRIMARY KEY,
    user_id                INTEGER NOT NULL,
    summary_type           TEXT NOT NULL,
    target_id              TEXT NOT NULL,
    not_before             TEXT NOT NULL,
    lease_until            TEXT,
    reason                 TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    UNIQUE(user_id, summary_type, target_id)
);

CREATE TABLE IF NOT EXISTS graph_summary_user_state (
    user_id                      INTEGER PRIMARY KEY,
    incremental_ops_since_full   INTEGER NOT NULL DEFAULT 0,
    last_full_rebuild_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_graph_summaries_user_type_target
    ON graph_summaries(user_id, summary_type, target_id, status);
CREATE INDEX IF NOT EXISTS idx_graph_summaries_user_status
    ON graph_summaries(user_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_graph_communities_user_type
    ON graph_communities(user_id, community_type, status);
CREATE INDEX IF NOT EXISTS idx_graph_summary_dirty_claim
    ON graph_summary_dirty(not_before, lease_until, updated_at);
"""

_MIGRATION_12_DDL = """
CREATE TABLE IF NOT EXISTS memory_attachment_events (
    event_id              TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    op                    TEXT NOT NULL,
    source_belief_id      TEXT,
    source_entity_id      TEXT NOT NULL,
    target_entity_id      TEXT NOT NULL,
    domain_pack           TEXT NOT NULL,
    tier                  TEXT NOT NULL,
    status                TEXT NOT NULL,
    utility_class         TEXT NOT NULL,
    evidence_json         TEXT NOT NULL,
    evidence_hash         TEXT NOT NULL,
    critic_report_json    TEXT,
    layer_trace_json      TEXT NOT NULL,
    input_hash            TEXT NOT NULL,
    resolver_version      TEXT NOT NULL,
    attachment_version    TEXT NOT NULL,
    supersedes_event_id   TEXT,
    graph_revision        INTEGER,
    created_at            TEXT NOT NULL,
    UNIQUE(user_id, op, source_entity_id, target_entity_id, evidence_hash, attachment_version)
);

CREATE TABLE IF NOT EXISTS memory_attachment_negatives (
    negative_id           TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    source_entity_id      TEXT NOT NULL,
    op                    TEXT NOT NULL,
    target_entity_id      TEXT NOT NULL,
    reason                TEXT NOT NULL,
    layer                 TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'active',
    expires_at            TEXT,
    created_at            TEXT NOT NULL,
    UNIQUE(user_id, source_entity_id, op, target_entity_id)
);

CREATE TABLE IF NOT EXISTS memory_attachment_dirty (
    dirty_id              TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    belief_id             TEXT NOT NULL,
    not_before            TEXT NOT NULL,
    lease_until           TEXT,
    reason                TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE(user_id, belief_id)
);

CREATE TABLE IF NOT EXISTS memory_attachment_embeddings (
    embed_id              TEXT PRIMARY KEY,
    user_id               INTEGER NOT NULL,
    object_kind           TEXT NOT NULL,
    object_id             TEXT NOT NULL,
    model_name            TEXT NOT NULL,
    embedding_json        TEXT NOT NULL,
    content_hash          TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE(user_id, object_kind, object_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_memory_attach_user_status
    ON memory_attachment_events(user_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_attach_source
    ON memory_attachment_events(source_entity_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_attach_target
    ON memory_attachment_events(target_entity_id, status);
"""

_MIGRATION_13_DDL = """
CREATE TABLE IF NOT EXISTS memory_attachment_dependencies (
    event_id             TEXT NOT NULL,
    user_id              INTEGER NOT NULL,
    dependency_type      TEXT NOT NULL,
    dependency_id        TEXT NOT NULL,
    path_json            TEXT,
    status               TEXT NOT NULL DEFAULT 'active',
    created_at           TEXT NOT NULL,
    PRIMARY KEY(event_id, dependency_type, dependency_id),
    FOREIGN KEY(event_id) REFERENCES memory_attachment_events(event_id)
);

CREATE TABLE IF NOT EXISTS memory_attachment_constraints (
    constraint_id        TEXT PRIMARY KEY,
    user_id              INTEGER NOT NULL,
    constraint_type      TEXT NOT NULL,
    subject_entity_id    TEXT,
    target_entity_id     TEXT NOT NULL,
    scope                TEXT NOT NULL,
    source_belief_id     TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'active',
    reason_json          TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    UNIQUE(user_id, constraint_type, subject_entity_id, target_entity_id, source_belief_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_attach_dependency
    ON memory_attachment_dependencies(user_id, dependency_type, dependency_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_attach_constraint_target
    ON memory_attachment_constraints(user_id, target_entity_id, status);
"""


class MemorySchemaError(RuntimeError):
    pass


def ensure_schema(conn: sqlite3.Connection) -> None:
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        _ensure_schema_in_txn(conn)
    except BaseException:
        if owns_transaction:
            conn.rollback()
        raise
    else:
        if owns_transaction:
            conn.commit()


def _ensure_schema_in_txn(conn: sqlite3.Connection) -> None:
    table_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'memory_schema_migrations'"
    ).fetchone()
    applied: set[int] = set()
    if table_exists is not None:
        applied = {
            int(row["version"] if isinstance(row, sqlite3.Row) else row[0])
            for row in conn.execute("SELECT version FROM memory_schema_migrations").fetchall()
        }
    if applied and max(applied) > SCHEMA_VERSION:
        raise MemorySchemaError(
            f"memory database schema version {max(applied)} is newer than supported {SCHEMA_VERSION}"
        )
    if applied:
        expected = set(range(1, max(applied) + 1))
        if applied != expected:
            raise MemorySchemaError(
                f"memory database has non-contiguous migrations: {sorted(applied)}"
            )

    from memory.db import utc_now_iso

    if 1 not in applied:
        for statement in _MIGRATION_1_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "INSERT OR IGNORE INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (1, utc_now_iso()),
        )
        applied.add(1)

    if 2 not in applied:
        _require_table(conn, "memory_jobs")
        columns = _column_names(conn, "memory_jobs")
        if "lease_token" not in columns:
            conn.execute("ALTER TABLE memory_jobs ADD COLUMN lease_token TEXT")
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (2, utc_now_iso()),
        )
        applied.add(2)

    if 3 not in applied:
        for statement in _MIGRATION_3_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (3, utc_now_iso()),
        )
        applied.add(3)

    if 4 not in applied:
        for statement in _MIGRATION_4_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (4, utc_now_iso()),
        )
        applied.add(4)

    if 5 not in applied:
        for statement in _MIGRATION_5_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (5, utc_now_iso()),
        )
        applied.add(5)

    if 6 not in applied:
        for statement in _MIGRATION_6_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (6, utc_now_iso()),
        )
        applied.add(6)

    if 7 not in applied:
        for statement in _MIGRATION_7_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (7, utc_now_iso()),
        )
        applied.add(7)

    if 8 not in applied:
        for statement in _MIGRATION_8_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (8, utc_now_iso()),
        )
        applied.add(8)

    if 9 not in applied:
        for statement in _MIGRATION_9_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (9, utc_now_iso()),
        )
        applied.add(9)

    if 10 not in applied:
        for statement in _MIGRATION_10_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (10, utc_now_iso()),
        )
        applied.add(10)

    if 11 not in applied:
        for statement in _MIGRATION_11_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        shadow_cols = _column_names(conn, "memory_shadow_retrieval_runs")
        if "summary_pack_json" not in shadow_cols:
            conn.execute(
                "ALTER TABLE memory_shadow_retrieval_runs "
                "ADD COLUMN summary_pack_json TEXT"
            )
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (11, utc_now_iso()),
        )
        applied.add(11)

    if 12 not in applied:
        for statement in _MIGRATION_12_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (12, utc_now_iso()),
        )
        applied.add(12)

    if 13 not in applied:
        for statement in _MIGRATION_13_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (13, utc_now_iso()),
        )
        applied.add(13)

    _validate_schema(conn)


_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "memory_schema_migrations": frozenset({"version", "applied_at"}),
    "memory_sources": frozenset(
        {
            "source_id",
            "user_id",
            "source_type",
            "source_ref",
            "status",
            "authority_class",
        }
    ),
    "memory_source_versions": frozenset(
        {
            "source_version_id",
            "source_id",
            "content_hash",
            "pointer_json",
            "status",
        }
    ),
    "memory_segments": frozenset(
        {"segment_id", "source_version_id", "pointer_json", "status"}
    ),
    "memory_jobs": frozenset(
        {
            "job_id",
            "user_id",
            "source_version_id",
            "status",
            "attempts",
            "max_attempts",
            "lease_owner",
            "lease_token",
            "lease_until",
            "input_hash",
            "target_kind",
            "target_id",
        }
    ),
    "memory_lineage": frozenset(
        {"lineage_id", "user_id", "parent_kind", "parent_id", "child_kind", "child_id"}
    ),
    "memory_processor_runs": frozenset(
        {"run_id", "job_id", "user_id", "input_hash", "outcome"}
    ),
    "memory_ingestion_cursors": frozenset(
        {
            "stream_name",
            "cursor_json",
            "initialized_at",
            "updated_at",
            "records_seen",
            "registered_count",
            "duplicate_count",
            "failed_count",
        }
    ),
    "memory_ingestion_failures": frozenset(
        {
            "stream_name",
            "item_key",
            "cursor_json",
            "status",
            "attempts",
            "max_attempts",
            "first_failed_at",
            "last_failed_at",
        }
    ),
    "memory_mentions": frozenset(
        {
            "mention_id",
            "user_id",
            "segment_id",
            "pointer_json",
            "extractor_name",
            "extractor_version",
            "prompt_version",
            "status",
        }
    ),
    "memory_claim_candidates": frozenset(
        {
            "candidate_id",
            "user_id",
            "candidate_kind",
            "schema_name",
            "arguments_json",
            "epistemic_json",
            "status",
            "extraction_run_id",
        }
    ),
    "memory_candidate_evidence": frozenset(
        {"candidate_id", "segment_id", "pointer_json", "evidence_relation"}
    ),
    "memory_candidate_verdicts": frozenset(
        {
            "verdict_id",
            "user_id",
            "candidate_id",
            "role",
            "verdict",
            "verifier_name",
            "verifier_version",
            "prompt_version",
            "input_hash",
            "output_json",
            "verification_run_id",
            "status",
        }
    ),
    "memory_candidate_scores": frozenset(
        {
            "score_id",
            "user_id",
            "candidate_id",
            "policy_version",
            "verdict_set_hash",
            "components_json",
            "route_status",
            "verification_run_id",
            "status",
        }
    ),
    "memory_entities": frozenset(
        {
            "entity_id",
            "user_id",
            "entity_type",
            "identity_key",
            "canonical_label",
            "status",
            "resolver_version",
        }
    ),
    "memory_entity_aliases": frozenset(
        {
            "alias_id",
            "user_id",
            "entity_id",
            "alias",
            "normalized_alias",
            "status",
        }
    ),
    "memory_mention_links": frozenset(
        {
            "link_id",
            "user_id",
            "mention_id",
            "entity_id",
            "decision",
            "resolver_version",
            "status",
        }
    ),
    "memory_assertions": frozenset(
        {
            "assertion_id",
            "user_id",
            "candidate_id",
            "proposition_key",
            "cluster_key",
            "resolved_arguments_json",
            "polarity",
            "assertion_schema_version",
            "resolver_version",
            "status",
            "resolution_run_id",
        }
    ),
    "memory_beliefs": frozenset(
        {"belief_id", "user_id", "proposition_key", "cluster_key", "schema_name"}
    ),
    "memory_belief_revisions": frozenset(
        {
            "belief_revision_id",
            "user_id",
            "belief_id",
            "input_set_hash",
            "belief_status",
            "utility_class",
            "reconciliation_policy_version",
            "utility_policy_version",
        }
    ),
    "memory_belief_heads": frozenset(
        {"belief_id", "user_id", "belief_revision_id", "updated_at"}
    ),
    "memory_belief_support": frozenset(
        {"belief_revision_id", "assertion_id", "relation", "weight_components_json"}
    ),
    "memory_resolution_verdicts": frozenset(
        {
            "resolution_verdict_id",
            "user_id",
            "mention_id",
            "proposed_entity_id",
            "role",
            "verdict",
            "critic_name",
            "critic_version",
            "prompt_version",
            "input_hash",
            "output_json",
            "resolution_run_id",
            "status",
        }
    ),
    "memory_entity_resolution_events": frozenset(
        {
            "event_id",
            "user_id",
            "op",
            "winner_entity_id",
            "loser_entity_id",
            "tier",
            "evidence_json",
            "evidence_hash",
            "reason",
            "decided_by",
            "resolver_version",
            "status",
            "created_at",
        }
    ),
    "memory_entity_alias_equivalences": frozenset(
        {
            "equivalence_id",
            "user_id",
            "normalized_alias_a",
            "normalized_alias_b",
            "entity_type",
            "source",
            "status",
            "created_at",
        }
    ),
    "graph_nodes": frozenset(
        {
            "node_id",
            "user_id",
            "node_type",
            "source_record_id",
            "status",
            "graph_revision",
            "created_at",
            "updated_at",
        }
    ),
    "graph_edges": frozenset(
        {
            "edge_id",
            "user_id",
            "from_node_id",
            "to_node_id",
            "edge_type",
            "belief_id",
            "status",
            "graph_revision",
            "payload_hash",
            "created_at",
            "updated_at",
        }
    ),
    "graph_outbox": frozenset(
        {
            "event_id",
            "user_id",
            "belief_id",
            "operation",
            "payload_hash",
            "status",
            "attempts",
            "created_at",
        }
    ),
    "graph_revisions": frozenset(
        {
            "user_id",
            "current_revision",
            "materializer_version",
            "graph_schema_version",
            "belief_policy_version",
        }
    ),
    "memory_shadow_retrieval_runs": frozenset(
        {
            "run_id",
            "user_id",
            "query_hash",
            "query_time",
            "graph_revision",
            "memory_needed",
            "plan_json",
            "channels_json",
            "pack_json",
            "latency_ms_json",
            "pack_token_estimate",
            "belief_ids_json",
            "summary_pack_json",
            "created_at",
        }
    ),
    "graph_summaries": frozenset(
        {
            "summary_id",
            "user_id",
            "summary_type",
            "target_id",
            "content",
            "sentences_json",
            "belief_ids_json",
            "sentence_support_json",
            "input_hash",
            "prompt_version",
            "status",
            "graph_revision",
            "created_at",
            "updated_at",
        }
    ),
    "graph_communities": frozenset(
        {
            "community_id",
            "user_id",
            "community_type",
            "member_node_ids_json",
            "member_belief_ids_json",
            "seed_node_id",
            "input_hash",
            "detector_version",
            "graph_revision",
            "status",
            "created_at",
            "updated_at",
        }
    ),
    "graph_summary_dirty": frozenset(
        {
            "dirty_id",
            "user_id",
            "summary_type",
            "target_id",
            "not_before",
            "created_at",
            "updated_at",
        }
    ),
    "graph_summary_user_state": frozenset(
        {
            "user_id",
            "incremental_ops_since_full",
        }
    ),
    "memory_attachment_events": frozenset(
        {
            "event_id",
            "user_id",
            "op",
            "source_entity_id",
            "target_entity_id",
            "domain_pack",
            "tier",
            "status",
            "utility_class",
            "evidence_hash",
            "layer_trace_json",
            "input_hash",
            "resolver_version",
            "attachment_version",
            "created_at",
        }
    ),
    "memory_attachment_negatives": frozenset(
        {
            "negative_id",
            "user_id",
            "source_entity_id",
            "op",
            "target_entity_id",
            "reason",
            "layer",
            "status",
            "created_at",
        }
    ),
    "memory_attachment_dirty": frozenset(
        {
            "dirty_id",
            "user_id",
            "belief_id",
            "not_before",
            "created_at",
            "updated_at",
        }
    ),
    "memory_attachment_embeddings": frozenset(
        {
            "embed_id",
            "user_id",
            "object_kind",
            "object_id",
            "model_name",
            "content_hash",
            "updated_at",
        }
    ),
    "memory_attachment_dependencies": frozenset(
        {
            "event_id",
            "user_id",
            "dependency_type",
            "dependency_id",
            "status",
            "created_at",
        }
    ),
    "memory_attachment_constraints": frozenset(
        {
            "constraint_id",
            "user_id",
            "constraint_type",
            "target_entity_id",
            "scope",
            "source_belief_id",
            "status",
            "reason_json",
            "created_at",
            "updated_at",
        }
    ),
}

_REQUIRED_INDEXES: dict[str, tuple[str, ...]] = {
    "idx_memory_sources_user_type": ("user_id", "source_type", "status"),
    "idx_memory_source_versions_source": ("source_id", "ingested_at"),
    "idx_memory_jobs_claim": ("status", "not_before", "priority", "created_at"),
    "idx_memory_jobs_lease": ("status", "lease_until"),
    "idx_memory_jobs_user": ("user_id", "status"),
    "idx_memory_lineage_parent": ("user_id", "parent_kind", "parent_id"),
    "idx_memory_lineage_child": ("user_id", "child_kind", "child_id"),
    "idx_memory_ingestion_failures_due": ("status", "not_before", "last_failed_at"),
    "idx_memory_sources_type_ref_status": ("source_type", "source_ref", "status"),
    "idx_memory_mentions_user_status": ("user_id", "status"),
    "idx_memory_mentions_segment": ("segment_id", "status"),
    "idx_memory_candidates_user_status": ("user_id", "status"),
    "idx_memory_candidate_evidence_segment": ("segment_id", "candidate_id"),
    "idx_memory_jobs_target": ("target_kind", "target_id", "status"),
    "idx_memory_candidate_verdicts_candidate": ("candidate_id", "status", "created_at"),
    "idx_memory_candidate_scores_candidate": ("candidate_id", "status", "created_at"),
    "idx_memory_entities_user_status": ("user_id", "status"),
    "idx_memory_entity_aliases_lookup": ("user_id", "normalized_alias", "status"),
    "idx_memory_mention_links_mention": ("mention_id", "status"),
    "idx_memory_assertions_user_prop": ("user_id", "proposition_key", "status"),
    "idx_memory_assertions_candidate": ("candidate_id", "status"),
    "idx_memory_beliefs_user": ("user_id", "schema_name"),
    "idx_memory_belief_revisions_belief": ("belief_id", "created_at"),
    "idx_memory_resolution_verdicts_mention": ("mention_id", "status", "created_at"),
    "idx_graph_nodes_user_status": ("user_id", "status", "node_type"),
    "idx_graph_edges_user_status": ("user_id", "status", "edge_type"),
    "idx_graph_edges_belief": ("belief_id", "status"),
    "idx_graph_edges_from": ("from_node_id", "status"),
    "idx_graph_edges_to": ("to_node_id", "status"),
    "idx_graph_outbox_claim": ("status", "lease_until", "created_at"),
    "idx_graph_outbox_user": ("user_id", "status"),
    "idx_memory_shadow_runs_user": ("user_id", "created_at"),
    "idx_memory_res_events_user_status": ("user_id", "status", "created_at"),
    "idx_memory_res_events_loser": ("loser_entity_id", "status"),
    "idx_memory_res_events_winner": ("winner_entity_id", "status"),
    "idx_memory_alias_equiv_lookup": ("user_id", "entity_type", "normalized_alias_a", "status"),
    "idx_graph_summaries_user_type_target": (
        "user_id",
        "summary_type",
        "target_id",
        "status",
    ),
    "idx_graph_summaries_user_status": ("user_id", "status", "updated_at"),
    "idx_graph_communities_user_type": ("user_id", "community_type", "status"),
    "idx_graph_summary_dirty_claim": ("not_before", "lease_until", "updated_at"),
    "idx_memory_attach_user_status": ("user_id", "status", "created_at"),
    "idx_memory_attach_source": ("source_entity_id", "status"),
    "idx_memory_attach_target": ("target_entity_id", "status"),
}


def _require_table(conn: sqlite3.Connection, table: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if row is None:
        raise MemorySchemaError(f"memory database is missing required table {table!r}")


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"] if isinstance(row, sqlite3.Row) else row[1])
        for row in conn.execute(f"PRAGMA table_info({table})")
    }


def _validate_schema(conn: sqlite3.Connection) -> None:
    for table, required in _REQUIRED_COLUMNS.items():
        _require_table(conn, table)
        missing = required - _column_names(conn, table)
        if missing:
            raise MemorySchemaError(
                f"memory database table {table!r} is missing columns: {sorted(missing)}"
            )

    indexes = {
        str(row["name"] if isinstance(row, sqlite3.Row) else row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    missing_indexes = set(_REQUIRED_INDEXES) - indexes
    if missing_indexes:
        raise MemorySchemaError(
            f"memory database is missing indexes: {sorted(missing_indexes)}"
        )
    for index_name, expected_columns in _REQUIRED_INDEXES.items():
        actual_columns = tuple(
            str(row["name"] if isinstance(row, sqlite3.Row) else row[2])
            for row in conn.execute(f"PRAGMA index_info({index_name})").fetchall()
        )
        if actual_columns != expected_columns:
            raise MemorySchemaError(
                f"memory database index {index_name!r} has columns "
                f"{actual_columns!r}, expected {expected_columns!r}"
            )

    applied = {
        int(row["version"] if isinstance(row, sqlite3.Row) else row[0])
        for row in conn.execute(
            "SELECT version FROM memory_schema_migrations ORDER BY version"
        ).fetchall()
    }
    if applied != set(range(1, SCHEMA_VERSION + 1)):
        raise MemorySchemaError(
            f"memory database migrations are incomplete: {sorted(applied)}"
        )
