from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from memory.db import MemoryDatabase, dumps_json, utc_now_iso
from memory.models import LineageInput, LineageRelation
from memory.resolution.schemas import (
    ASSERTION_SCHEMA_VERSION,
    RECONCILIATION_POLICY_VERSION,
    RESOLVER_VERSION,
    UTILITY_POLICY_VERSION,
    AssertionRecord,
    BeliefRevisionRecord,
    ResolutionBatch,
    ResolvedArgument,
)
from memory.resolution.events_store import insert_events_in_txn

if TYPE_CHECKING:
    from memory.lineage import MemoryLineageStore


class MemoryResolutionStore:
    def __init__(
        self,
        db: MemoryDatabase,
        *,
        summary_invalidator: object | None = None,
        attachment_invalidator: object | None = None,
    ) -> None:
        self._db = db
        self._summary_invalidator = summary_invalidator
        self._attachment_invalidator = attachment_invalidator

    def list_schedulable(
        self,
        *,
        required_verification_policy: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.candidate_id, c.user_id,
                       extraction_job.source_version_id,
                       score.score_id, score.verdict_set_hash
                FROM memory_claim_candidates c
                JOIN memory_processor_runs extraction_run
                  ON extraction_run.run_id = c.extraction_run_id
                JOIN memory_jobs extraction_job
                  ON extraction_job.job_id = extraction_run.job_id
                JOIN memory_source_versions ver
                  ON ver.source_version_id = extraction_job.source_version_id
                JOIN memory_sources src ON src.source_id = ver.source_id
                JOIN memory_candidate_scores score
                  ON score.candidate_id = c.candidate_id
                 AND score.policy_version = ?
                 AND score.route_status = 'ready_for_resolution'
                 AND score.status = 'active'
                WHERE c.status = 'ready_for_resolution'
                  AND src.status = 'active' AND ver.status = 'active'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM memory_assertions a
                      WHERE a.candidate_id = c.candidate_id
                        AND a.assertion_schema_version = ?
                        AND a.resolver_version = ?
                        AND a.status IN ('active', 'historical')
                  )
                ORDER BY c.created_at, c.candidate_id
                LIMIT ?
                """,
                (
                    required_verification_policy,
                    ASSERTION_SCHEMA_VERSION,
                    RESOLVER_VERSION,
                    limit,
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_ready_candidate(
        self,
        candidate_id: str,
        *,
        user_id: int,
        required_verification_policy: str,
    ) -> dict[str, Any] | None:
        with self._db.connection() as conn:
            return self.load_ready_candidate_in_txn(
                conn,
                candidate_id,
                user_id=user_id,
                required_verification_policy=required_verification_policy,
            )

    def load_ready_candidate_in_txn(
        self,
        conn: sqlite3.Connection,
        candidate_id: str,
        *,
        user_id: int,
        required_verification_policy: str,
    ) -> dict[str, Any] | None:
        candidate = conn.execute(
            """
            SELECT c.*, extraction_job.source_version_id AS primary_source_version_id
            FROM memory_claim_candidates c
            JOIN memory_processor_runs extraction_run
              ON extraction_run.run_id = c.extraction_run_id
            JOIN memory_jobs extraction_job
              ON extraction_job.job_id = extraction_run.job_id
            WHERE c.candidate_id = ? AND c.user_id = ?
            """,
            (candidate_id, user_id),
        ).fetchone()
        if candidate is None:
            return None
        score = conn.execute(
            """
            SELECT *
            FROM memory_candidate_scores
            WHERE candidate_id = ? AND user_id = ?
              AND policy_version = ? AND status = 'active'
            ORDER BY created_at DESC, score_id DESC
            LIMIT 1
            """,
            (candidate_id, user_id, required_verification_policy),
        ).fetchone()
        arguments = _load_json(candidate["arguments_json"])
        if not isinstance(arguments, list):
            arguments = []
        epistemic = _load_object(candidate["epistemic_json"])
        mention_ids = {
            str(item["mention_id"])
            for item in arguments
            if isinstance(item, dict) and item.get("mention_id")
        }
        mentions: dict[str, dict[str, Any]] = {}
        if mention_ids:
            placeholders = ",".join("?" for _ in mention_ids)
            rows = conn.execute(
                f"""
                SELECT mention_id, mention_type, surface_text, normalized_hint,
                       pointer_json, status
                FROM memory_mentions
                WHERE user_id = ? AND mention_id IN ({placeholders})
                """,
                (user_id, *sorted(mention_ids)),
            ).fetchall()
            mentions = {str(row["mention_id"]): dict(row) for row in rows}
        evidence_rows = conn.execute(
            """
            SELECT evidence_relation AS relation, segment_id
            FROM memory_candidate_evidence
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        ).fetchall()
        return {
            "candidate_id": str(candidate["candidate_id"]),
            "user_id": int(candidate["user_id"]),
            "candidate_kind": str(candidate["candidate_kind"]),
            "kind": str(candidate["candidate_kind"]),
            "schema_name": str(candidate["schema_name"]),
            "schema_version": str(candidate["schema_version"]),
            "arguments": arguments,
            "attributes": _load_object(candidate["attributes_json"]),
            "polarity": str(candidate["polarity"]),
            "epistemic": epistemic,
            "temporal": (
                _load_object(candidate["temporal_json"])
                if candidate["temporal_json"]
                else None
            ),
            "status": str(candidate["status"]),
            "primary_source_version_id": str(candidate["primary_source_version_id"]),
            "mentions": mentions,
            "evidence": [
                {
                    "relation": str(row["relation"]),
                    "segment_id": str(row["segment_id"]),
                }
                for row in evidence_rows
            ],
            "score": dict(score) if score is not None else None,
        }

    def list_assertions_for_proposition(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        proposition_key: str,
    ) -> list[AssertionRecord]:
        rows = conn.execute(
            """
            SELECT *
            FROM memory_assertions
            WHERE user_id = ? AND proposition_key = ?
              AND status IN ('active', 'historical', 'invalidated')
            ORDER BY created_at, assertion_id
            """,
            (user_id, proposition_key),
        ).fetchall()
        return [_row_to_assertion(row) for row in rows]

    def get_belief_head(
        self,
        conn: sqlite3.Connection,
        *,
        belief_id: str,
        user_id: int,
    ) -> str | None:
        row = conn.execute(
            """
            SELECT belief_revision_id
            FROM memory_belief_heads
            WHERE belief_id = ? AND user_id = ?
            """,
            (belief_id, user_id),
        ).fetchone()
        return str(row["belief_revision_id"]) if row is not None else None

    def insert_outputs_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        resolution_run_id: str,
        batch: ResolutionBatch,
        lineage_store: "MemoryLineageStore",
    ) -> None:
        now = utc_now_iso()
        links: list[LineageInput] = []

        for entity in batch.entities:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_entities(
                    entity_id, user_id, entity_type, identity_key, canonical_label,
                    status, resolver_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity.entity_id,
                    user_id,
                    entity.entity_type,
                    entity.identity_key,
                    entity.canonical_label,
                    entity.status,
                    RESOLVER_VERSION,
                    now,
                    now,
                ),
            )

        if batch.merge_events:
            insert_events_in_txn(
                conn,
                user_id,
                batch.merge_events,
                resolution_run_id=resolution_run_id,
                now=now,
            )
            invalidator = self._summary_invalidator
            if invalidator is not None:
                mark_merge = getattr(invalidator, "mark_entity_merge_in_txn", None)
                if callable(mark_merge):
                    for event in batch.merge_events:
                        if event.op == "merge":
                            mark_merge(
                                conn,
                                user_id=user_id,
                                winner_entity_id=event.winner_entity_id,
                                loser_entity_id=event.loser_entity_id,
                            )
            for event in batch.merge_events:
                if event.op == "split" and event.supersedes_event_id:
                    conn.execute(
                        """
                        UPDATE memory_entity_resolution_events
                        SET status = 'reverted'
                        WHERE event_id = ? AND user_id = ?
                        """,
                        (event.supersedes_event_id, user_id),
                    )

        for alias in batch.aliases:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_entity_aliases(
                    alias_id, user_id, entity_id, source_mention_id, alias,
                    normalized_alias, language, evidence_pointer_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    alias.alias_id,
                    user_id,
                    alias.entity_id,
                    alias.source_mention_id,
                    alias.alias,
                    alias.normalized_alias,
                    alias.language,
                    alias.evidence_pointer_json,
                    now,
                ),
            )
            if alias.source_mention_id:
                links.append(
                    LineageInput(
                        parent_kind="mention",
                        parent_id=alias.source_mention_id,
                        child_kind="entity_alias",
                        child_id=alias.alias_id,
                        relation=LineageRelation.DERIVED_FROM,
                    )
                )

        for link in batch.mention_links:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_mention_links(
                    link_id, user_id, mention_id, entity_id, decision,
                    resolution_components_json, resolver_version, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    link.link_id,
                    user_id,
                    link.mention_id,
                    link.entity_id,
                    link.decision,
                    dumps_json(dict(link.resolution_components)),
                    RESOLVER_VERSION,
                    now,
                ),
            )
            links.extend(
                (
                    LineageInput(
                        parent_kind="mention",
                        parent_id=link.mention_id,
                        child_kind="mention_link",
                        child_id=link.link_id,
                        relation=LineageRelation.DERIVED_FROM,
                    ),
                    LineageInput(
                        parent_kind="mention_link",
                        parent_id=link.link_id,
                        child_kind="entity",
                        child_id=link.entity_id,
                        relation=LineageRelation.DERIVED_FROM,
                    ),
                )
            )

        for verdict in batch.resolution_verdicts:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_resolution_verdicts(
                    resolution_verdict_id, user_id, mention_id, proposed_entity_id,
                    role, verdict, scope_errors_json, ambiguities_json,
                    missing_context_json, critic_name, critic_version, prompt_version,
                    model_profile, model_name, reasoning_effort, input_hash, output_json,
                    resolution_run_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    verdict.resolution_verdict_id,
                    user_id,
                    verdict.mention_id,
                    verdict.proposed_entity_id,
                    verdict.role,
                    verdict.verdict,
                    dumps_json(list(verdict.scope_errors)),
                    dumps_json(list(verdict.ambiguities)),
                    dumps_json(list(verdict.missing_context)),
                    verdict.critic_name,
                    verdict.critic_version,
                    verdict.prompt_version,
                    verdict.model_profile,
                    verdict.model_name,
                    verdict.reasoning_effort,
                    verdict.input_hash,
                    dumps_json(dict(verdict.output_json)),
                    resolution_run_id,
                    now,
                ),
            )
            link_id = next(
                (
                    item.link_id
                    for item in batch.mention_links
                    if item.mention_id == verdict.mention_id
                ),
                None,
            )
            if link_id:
                links.append(
                    LineageInput(
                        parent_kind="resolution_verdict",
                        parent_id=verdict.resolution_verdict_id,
                        child_kind="mention_link",
                        child_id=link_id,
                        relation=LineageRelation.DERIVED_FROM,
                    )
                )

        assertion = batch.assertion
        assertions_to_insert: list[AssertionRecord] = []
        if assertion is not None:
            assertions_to_insert.append(assertion)
        assertions_to_insert.extend(batch.additional_assertions)

        if batch.historicalize_assertion_ids:
            placeholders = ",".join("?" for _ in batch.historicalize_assertion_ids)
            conn.execute(
                f"""
                UPDATE memory_assertions
                SET status = 'historical'
                WHERE user_id = ?
                  AND assertion_id IN ({placeholders})
                  AND status = 'active'
                """,
                (user_id, *batch.historicalize_assertion_ids),
            )

        # Winner assertions use synthetic candidate_ids (`{corr}:winner`) to satisfy
        # UNIQUE(candidate_id, assertion_schema_version, resolver_version).
        for assertion in assertions_to_insert:
            _ensure_assertion_candidate_row(
                conn,
                user_id=user_id,
                assertion=assertion,
                now=now,
            )

        for assertion in assertions_to_insert:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_assertions(
                    assertion_id, user_id, candidate_id, proposition_key, cluster_key,
                    candidate_kind, schema_name, schema_version,
                    resolved_arguments_json, attributes_json, polarity, epistemic_json,
                    temporal_json, observed_at, recorded_at, assertion_schema_version,
                    resolver_version, status, resolution_run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assertion.assertion_id,
                    user_id,
                    assertion.candidate_id,
                    assertion.proposition_key,
                    assertion.cluster_key,
                    assertion.candidate_kind,
                    assertion.schema_name,
                    assertion.schema_version,
                    dumps_json([item.to_mapping() for item in assertion.resolved_arguments]),
                    dumps_json(dict(assertion.attributes)),
                    assertion.polarity,
                    dumps_json(dict(assertion.epistemic)),
                    dumps_json(dict(assertion.temporal)) if assertion.temporal else None,
                    assertion.observed_at,
                    now,
                    ASSERTION_SCHEMA_VERSION,
                    RESOLVER_VERSION,
                    assertion.status,
                    resolution_run_id,
                    now,
                ),
            )
            links.append(
                LineageInput(
                    parent_kind="candidate",
                    parent_id=assertion.candidate_id,
                    child_kind="assertion",
                    child_id=assertion.assertion_id,
                    relation=LineageRelation.DERIVED_FROM,
                )
            )
            for arg in assertion.resolved_arguments:
                if arg.value_kind == "entity" and arg.entity_id:
                    links.append(
                        LineageInput(
                            parent_kind="entity",
                            parent_id=arg.entity_id,
                            child_kind="assertion",
                            child_id=assertion.assertion_id,
                            relation=LineageRelation.DERIVED_FROM,
                        )
                    )

        # Additional revisions first (e.g. historicalize losers). Primary revision last
        # so same-proposition cessation/correction heads are not overwritten.
        revisions: list[BeliefRevisionRecord] = []
        revisions.extend(batch.additional_belief_revisions)
        if batch.belief_revision is not None:
            revisions.append(batch.belief_revision)

        for revision in revisions:
            _insert_belief_revision_in_txn(
                conn,
                user_id=user_id,
                revision=revision,
                set_belief_head=batch.set_belief_head,
                now=now,
                links=links,
                attachment_invalidator=self._attachment_invalidator,
            )

        if links:
            lineage_store.add_links(conn, user_id=user_id, links=links)


def _ensure_assertion_candidate_row(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    assertion: AssertionRecord,
    now: str,
) -> None:
    existing = conn.execute(
        "SELECT candidate_id FROM memory_claim_candidates WHERE candidate_id = ?",
        (assertion.candidate_id,),
    ).fetchone()
    if existing is not None:
        return
    # Prefer cloning extraction_run_id from a real sibling assertion candidate.
    sibling = None
    if assertion.candidate_id.endswith(":winner"):
        base_id = assertion.candidate_id[: -len(":winner")]
        sibling = conn.execute(
            "SELECT * FROM memory_claim_candidates WHERE candidate_id = ?",
            (base_id,),
        ).fetchone()
    if sibling is None:
        raise ValueError(
            f"cannot insert assertion for unknown candidate {assertion.candidate_id!r}"
        )
    conn.execute(
        """
        INSERT OR IGNORE INTO memory_claim_candidates(
            candidate_id, user_id, candidate_kind, schema_name, schema_version,
            arguments_json, attributes_json, polarity, epistemic_json, temporal_json,
            canonical_hint, status, extraction_run_id, acceptance_policy,
            extractor_name, extractor_version, prompt_version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'ready_for_resolution', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            assertion.candidate_id,
            user_id,
            assertion.candidate_kind,
            assertion.schema_name,
            assertion.schema_version,
            dumps_json([item.to_mapping() for item in assertion.resolved_arguments]),
            dumps_json(dict(assertion.attributes)),
            assertion.polarity,
            dumps_json(dict(assertion.epistemic)),
            dumps_json(dict(assertion.temporal)) if assertion.temporal else None,
            sibling["extraction_run_id"],
            sibling["acceptance_policy"],
            str(sibling["extractor_name"]),
            str(sibling["extractor_version"]),
            str(sibling["prompt_version"]),
            now,
            now,
        ),
    )


def _insert_belief_revision_in_txn(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    revision: BeliefRevisionRecord,
    set_belief_head: bool,
    now: str,
    links: list[LineageInput],
    attachment_invalidator: object | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO memory_beliefs(
            belief_id, user_id, proposition_key, cluster_key, schema_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            revision.belief_id,
            user_id,
            revision.proposition_key,
            revision.cluster_key,
            revision.schema_name,
            now,
        ),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO memory_belief_revisions(
            belief_revision_id, user_id, belief_id, input_set_hash,
            resolved_arguments_json, resolved_value_json, polarity, temporal_json,
            belief_status, utility_class, utility_reason_codes_json,
            confidence_components_json, reconciliation_policy_version,
            utility_policy_version, supersedes_revision_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision.belief_revision_id,
            user_id,
            revision.belief_id,
            revision.input_set_hash,
            dumps_json([item.to_mapping() for item in revision.resolved_arguments]),
            dumps_json(dict(revision.resolved_value)) if revision.resolved_value else None,
            revision.polarity,
            dumps_json(dict(revision.temporal)) if revision.temporal else None,
            revision.belief_status,
            revision.utility_class,
            dumps_json(list(revision.utility_reason_codes)),
            dumps_json(dict(revision.confidence_components)),
            RECONCILIATION_POLICY_VERSION,
            UTILITY_POLICY_VERSION,
            revision.supersedes_revision_id,
            now,
        ),
    )
    # Refresh support when the revision row already existed (INSERT OR IGNORE).
    conn.execute(
        "DELETE FROM memory_belief_support WHERE belief_revision_id = ?",
        (revision.belief_revision_id,),
    )
    for support in revision.support:
        conn.execute(
            """
            INSERT OR IGNORE INTO memory_belief_support(
                belief_revision_id, assertion_id, relation, weight_components_json
            ) VALUES (?, ?, ?, ?)
            """,
            (
                revision.belief_revision_id,
                support.assertion_id,
                support.relation,
                dumps_json(dict(support.weight_components)),
            ),
        )
        links.append(
            LineageInput(
                parent_kind="assertion",
                parent_id=support.assertion_id,
                child_kind="belief_revision",
                child_id=revision.belief_revision_id,
                relation=LineageRelation.DERIVED_FROM,
            )
        )
    if set_belief_head:
        existing = conn.execute(
            """
            SELECT belief_revision_id FROM memory_belief_heads
            WHERE belief_id = ? AND user_id = ?
            """,
            (revision.belief_id, user_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO memory_belief_heads(
                    belief_id, user_id, belief_revision_id, updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (revision.belief_id, user_id, revision.belief_revision_id, now),
            )
        else:
            conn.execute(
                """
                UPDATE memory_belief_heads
                SET belief_revision_id = ?, updated_at = ?
                WHERE belief_id = ? AND user_id = ?
                """,
                (revision.belief_revision_id, now, revision.belief_id, user_id),
            )
        if revision.supersedes_revision_id:
            links.append(
                LineageInput(
                    parent_kind="belief_revision",
                    parent_id=revision.supersedes_revision_id,
                    child_kind="belief_revision",
                    child_id=revision.belief_revision_id,
                    relation=LineageRelation.SUPERSEDES,
                )
            )
        from memory.graph.outbox import enqueue_belief_head_change

        enqueue_belief_head_change(
            conn,
            user_id=user_id,
            belief_id=revision.belief_id,
            belief_status=revision.belief_status,
            utility_class=revision.utility_class,
            revision_id=revision.belief_revision_id,
        )
        _mark_attachment_dirty_in_txn(
            conn,
            invalidator=attachment_invalidator,
            user_id=user_id,
            belief_id=revision.belief_id,
        )


def _mark_attachment_dirty_in_txn(
    conn: sqlite3.Connection,
    *,
    invalidator: object | None,
    user_id: int,
    belief_id: str,
) -> None:
    if invalidator is None:
        return
    mark = getattr(invalidator, "mark_from_belief_change_in_txn", None)
    if callable(mark):
        mark(conn, user_id=user_id, belief_id=belief_id)


def _load_json(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def _load_object(value: str | None) -> dict[str, Any]:
    parsed = _load_json(value)
    return dict(parsed) if isinstance(parsed, dict) else {}


def _row_to_assertion(row: sqlite3.Row) -> AssertionRecord:
    args_raw = _load_json(row["resolved_arguments_json"])
    resolved: list[ResolvedArgument] = []
    if isinstance(args_raw, list):
        for item in args_raw:
            if not isinstance(item, dict):
                continue
            resolved.append(
                ResolvedArgument(
                    role=str(item.get("role") or ""),
                    value_kind=str(item.get("value_kind") or "literal"),
                    entity_id=(
                        str(item["entity_id"]) if item.get("entity_id") else None
                    ),
                    literal=item.get("literal"),
                )
            )
    return AssertionRecord(
        assertion_id=str(row["assertion_id"]),
        candidate_id=str(row["candidate_id"]),
        proposition_key=str(row["proposition_key"]),
        cluster_key=str(row["cluster_key"]),
        candidate_kind=str(row["candidate_kind"]),
        schema_name=str(row["schema_name"]),
        schema_version=str(row["schema_version"]),
        resolved_arguments=tuple(resolved),
        attributes=_load_object(row["attributes_json"]),
        polarity=str(row["polarity"]),
        epistemic=_load_object(row["epistemic_json"]),
        temporal=_load_object(row["temporal_json"]) if row["temporal_json"] else None,
        observed_at=str(row["observed_at"]) if row["observed_at"] else None,
        status=str(row["status"]),
    )
