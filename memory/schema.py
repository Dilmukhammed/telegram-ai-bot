from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 5

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
