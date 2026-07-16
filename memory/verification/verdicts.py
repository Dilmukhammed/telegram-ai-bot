from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any, Sequence

from memory.db import MemoryDatabase, dumps_json, loads_json_object, utc_now_iso
from memory.ids import make_score_id, make_verdict_id
from memory.models import LineageInput, LineageRelation
from memory.verification.adversarial import looks_like_correction
from memory.verification.schemas import (
    CandidateScoreInput,
    CandidateStatusUpdate,
    EvidenceDirectness,
    VerificationVerdictInput,
    VerificationVerdict,
    VerifierRole,
)

if TYPE_CHECKING:
    from memory.lineage import MemoryLineageStore


class MemoryVerificationStore:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    def load_candidate(self, candidate_id: str, *, user_id: int) -> dict[str, Any] | None:
        with self._db.connection() as conn:
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
            evidence_rows = conn.execute(
                """
                SELECT e.*, seg.text AS segment_text, seg.status AS segment_status,
                       src.source_type, src.authority_class, src.status AS source_status,
                       ver.status AS source_version_status,
                       ver.occurred_at AS source_occurred_at
                FROM memory_candidate_evidence e
                JOIN memory_segments seg ON seg.segment_id = e.segment_id
                JOIN memory_source_versions ver
                  ON ver.source_version_id = seg.source_version_id
                JOIN memory_sources src ON src.source_id = ver.source_id
                WHERE e.candidate_id = ? AND src.user_id = ?
                ORDER BY e.segment_id, e.pointer_json
                """,
                (candidate_id, user_id),
            ).fetchall()
            arguments = _load_json(candidate["arguments_json"])
            epistemic = loads_json_object(candidate["epistemic_json"])
            mention_ids = {
                str(item["mention_id"])
                for item in arguments
                if isinstance(item, dict) and item.get("mention_id")
            }
            speaker_ref = epistemic.get("speaker_ref")
            if isinstance(speaker_ref, str) and speaker_ref.startswith("mmen_"):
                mention_ids.add(speaker_ref)
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
                mentions = {
                    str(row["mention_id"]): {
                        "mention_id": str(row["mention_id"]),
                        "mention_type": str(row["mention_type"]),
                        "surface_text": str(row["surface_text"]),
                        "normalized_hint": row["normalized_hint"],
                        "pointer": loads_json_object(row["pointer_json"]),
                        "status": str(row["status"]),
                    }
                    for row in rows
                }

        return {
            "candidate_id": str(candidate["candidate_id"]),
            "user_id": int(candidate["user_id"]),
            "candidate_kind": str(candidate["candidate_kind"]),
            "schema_name": str(candidate["schema_name"]),
            "schema_version": str(candidate["schema_version"]),
            "arguments": arguments,
            "attributes": loads_json_object(candidate["attributes_json"]),
            "polarity": str(candidate["polarity"]),
            "epistemic": epistemic,
            "temporal": (
                loads_json_object(candidate["temporal_json"])
                if candidate["temporal_json"]
                else None
            ),
            "canonical_hint": candidate["canonical_hint"],
            "status": str(candidate["status"]),
            "acceptance_policy": candidate["acceptance_policy"],
            "primary_source_version_id": str(candidate["primary_source_version_id"]),
            "mentions": mentions,
            "evidence": [
                {
                    "segment_id": str(row["segment_id"]),
                    "relation": str(row["evidence_relation"]),
                    "pointer": loads_json_object(row["pointer_json"]),
                    "exact_quote": str(row["exact_quote"] or ""),
                    "context_pointer": (
                        loads_json_object(row["context_pointer_json"])
                        if row["context_pointer_json"]
                        else None
                    ),
                    "segment_text": str(row["segment_text"] or ""),
                    "segment_status": str(row["segment_status"]),
                    "source_type": str(row["source_type"]),
                    "authority_class": str(row["authority_class"]),
                    "source_status": str(row["source_status"]),
                    "source_version_status": str(row["source_version_status"]),
                    "source_occurred_at": row["source_occurred_at"],
                }
                for row in evidence_rows
            ],
        }

    def list_schedulable(
        self,
        *,
        policy_version: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.candidate_id, c.user_id,
                       extraction_job.source_version_id
                FROM memory_claim_candidates c
                JOIN memory_processor_runs extraction_run
                  ON extraction_run.run_id = c.extraction_run_id
                JOIN memory_jobs extraction_job
                  ON extraction_job.job_id = extraction_run.job_id
                JOIN memory_source_versions ver
                  ON ver.source_version_id = extraction_job.source_version_id
                JOIN memory_sources src ON src.source_id = ver.source_id
                WHERE c.status NOT IN ('superseded', 'invalidated')
                  AND src.status = 'active' AND ver.status = 'active'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM memory_candidate_scores score
                      WHERE score.candidate_id = c.candidate_id
                        AND score.policy_version = ?
                        AND score.status = 'active'
                  )
                ORDER BY c.created_at, c.candidate_id
                LIMIT ?
                """,
                (policy_version, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_verdict_inputs(
        self,
        *,
        candidate_id: str,
        user_id: int,
        verifier_version: str,
        prompt_version: str,
        input_hash: str,
    ) -> tuple[VerificationVerdictInput, ...]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_candidate_verdicts
                WHERE candidate_id = ? AND user_id = ?
                  AND verifier_version = ? AND prompt_version = ?
                  AND input_hash = ? AND status = 'active'
                ORDER BY role, verdict_id
                """,
                (
                    candidate_id,
                    user_id,
                    verifier_version,
                    prompt_version,
                    input_hash,
                ),
            ).fetchall()
        return tuple(
            VerificationVerdictInput(
                candidate_id=str(row["candidate_id"]),
                role=VerifierRole(str(row["role"])),
                verdict=VerificationVerdict(str(row["verdict"])),
                evidence_directness=(
                    EvidenceDirectness(str(row["evidence_directness"]))
                    if row["evidence_directness"]
                    else None
                ),
                scope_errors=tuple(_load_json(row["scope_errors_json"])),
                ambiguities=tuple(_load_json(row["ambiguities_json"])),
                missing_context=tuple(_load_json(row["missing_context_json"])),
                verifier_name=str(row["verifier_name"]),
                verifier_version=str(row["verifier_version"]),
                prompt_version=str(row["prompt_version"]),
                model_profile=row["model_profile"],
                model_name=row["model_name"],
                input_hash=str(row["input_hash"]),
                raw_output=loads_json_object(row["output_json"]),
            )
            for row in rows
        )

    def insert_outputs_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        verification_run_id: str,
        target_candidate_id: str,
        verdicts: Sequence[VerificationVerdictInput],
        scores: Sequence[CandidateScoreInput],
        updates: Sequence[CandidateStatusUpdate],
        lineage_store: "MemoryLineageStore",
    ) -> None:
        now = utc_now_iso()
        owner = conn.execute(
            "SELECT user_id FROM memory_claim_candidates WHERE candidate_id = ?",
            (target_candidate_id,),
        ).fetchone()
        if owner is None:
            raise ValueError(f"unknown verification target: {target_candidate_id}")
        if int(owner["user_id"]) != user_id:
            raise PermissionError("verification target belongs to another user")

        links: list[LineageInput] = []
        for item in verdicts:
            if item.candidate_id != target_candidate_id:
                raise ValueError("verdict candidate does not match verification job target")
            verdict_id = make_verdict_id(
                candidate_id=item.candidate_id,
                role=item.role.value,
                verifier_name=item.verifier_name,
                verifier_version=item.verifier_version,
                prompt_version=item.prompt_version,
                input_hash=item.input_hash,
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_candidate_verdicts(
                    verdict_id, user_id, candidate_id, role, verdict,
                    evidence_directness, scope_errors_json, ambiguities_json,
                    missing_context_json, corrected_candidate_json,
                    verifier_name, verifier_version, prompt_version,
                    model_profile, model_name, input_hash, output_json,
                    verification_run_id, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    verdict_id,
                    user_id,
                    item.candidate_id,
                    item.role.value,
                    item.verdict.value,
                    item.evidence_directness.value if item.evidence_directness else None,
                    dumps_json(list(item.scope_errors)),
                    dumps_json(list(item.ambiguities)),
                    dumps_json(list(item.missing_context)),
                    item.verifier_name,
                    item.verifier_version,
                    item.prompt_version,
                    item.model_profile,
                    item.model_name,
                    item.input_hash,
                    dumps_json(dict(item.raw_output)),
                    verification_run_id,
                    now,
                ),
            )
            links.append(
                LineageInput(
                    parent_kind="candidate",
                    parent_id=item.candidate_id,
                    child_kind="candidate_verdict",
                    child_id=verdict_id,
                    relation=LineageRelation.DERIVED_FROM,
                )
            )

        for item in scores:
            if item.candidate_id != target_candidate_id:
                raise ValueError("score candidate does not match verification job target")
            score_id = make_score_id(
                candidate_id=item.candidate_id,
                policy_version=item.policy_version,
                verdict_set_hash=item.verdict_set_hash,
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_candidate_scores(
                    score_id, user_id, candidate_id, policy_version,
                    verdict_set_hash, components_json, route_status,
                    verification_run_id, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    score_id,
                    user_id,
                    item.candidate_id,
                    item.policy_version,
                    item.verdict_set_hash,
                    dumps_json(dict(item.components)),
                    item.route_status,
                    verification_run_id,
                    now,
                ),
            )
            links.append(
                LineageInput(
                    parent_kind="candidate",
                    parent_id=item.candidate_id,
                    child_kind="candidate_score",
                    child_id=score_id,
                    relation=LineageRelation.DERIVED_FROM,
                )
            )

        for item in updates:
            if item.candidate_id != target_candidate_id:
                raise ValueError("candidate update does not match verification job target")
            placeholders = ",".join("?" for _ in item.from_statuses)
            updated = conn.execute(
                f"""
                UPDATE memory_claim_candidates
                SET status = ?, acceptance_policy = ?, updated_at = ?
                WHERE candidate_id = ? AND user_id = ?
                  AND status IN ({placeholders})
                """,
                (
                    item.to_status,
                    item.acceptance_policy,
                    now,
                    item.candidate_id,
                    user_id,
                    *item.from_statuses,
                ),
            )
            if updated.rowcount != 1:
                raise ValueError("candidate status changed before verification commit")

        for item in updates:
            if item.to_status in {"ready_for_resolution", "needs_confirmation"}:
                _supersede_priors_after_correction(
                    conn,
                    user_id=user_id,
                    correction_candidate_id=item.candidate_id,
                    now=now,
                )

        if links:
            lineage_store.add_links(conn, user_id=user_id, links=links)

    def list_verdicts(self, *, user_id: int, candidate_id: str) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_candidate_verdicts
                WHERE user_id = ? AND candidate_id = ?
                ORDER BY created_at, verdict_id
                """,
                (user_id, candidate_id),
            ).fetchall()
        return [dict(row) for row in rows]


def _load_json(value: str) -> Any:
    parsed = json.loads(value)
    return parsed


def _supersede_priors_after_correction(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    correction_candidate_id: str,
    now: str,
) -> None:
    """After a correction verifies, supersede prior candidates on supported prior segments."""
    row = conn.execute(
        """
        SELECT candidate_kind, arguments_json
        FROM memory_claim_candidates
        WHERE candidate_id = ? AND user_id = ?
        """,
        (correction_candidate_id, user_id),
    ).fetchone()
    if row is None:
        return
    evidence_rows = conn.execute(
        """
        SELECT segment_id, evidence_relation AS relation
        FROM memory_candidate_evidence
        WHERE candidate_id = ?
        """,
        (correction_candidate_id,),
    ).fetchall()
    arguments = _load_json(str(row["arguments_json"]))
    if not isinstance(arguments, list):
        arguments = []
    payload = {
        "candidate_kind": str(row["candidate_kind"] or ""),
        "arguments": arguments,
        "evidence": [
            {"relation": str(item["relation"] or "")} for item in evidence_rows
        ],
    }
    if not looks_like_correction(payload):
        return

    corrects_segments = {
        str(item["segment_id"])
        for item in evidence_rows
        if str(item["relation"] or "") == "corrects"
    }
    # Prior facts live on supports segments that are not the correction utterance.
    prior_segment_ids = {
        str(item["segment_id"])
        for item in evidence_rows
        if str(item["relation"] or "") == "supports"
        and str(item["segment_id"]) not in corrects_segments
    }
    if not prior_segment_ids:
        segment_ids = [str(item["segment_id"]) for item in evidence_rows]
        unique = list(dict.fromkeys(segment_ids))
        if len(unique) > 1:
            prior_segment_ids = set(unique[:-1])
    if not prior_segment_ids:
        return

    placeholders = ",".join("?" for _ in prior_segment_ids)
    candidates = conn.execute(
        f"""
        SELECT c.candidate_id, c.candidate_kind, c.arguments_json
        FROM memory_claim_candidates AS c
        WHERE c.user_id = ?
          AND c.candidate_id != ?
          AND c.status IN (
              'proposed', 'needs_confirmation', 'ready_for_resolution',
              'insufficient', 'contradicted'
          )
          AND c.candidate_id IN (
            SELECT DISTINCT candidate_id
            FROM memory_candidate_evidence
            WHERE segment_id IN ({placeholders})
          )
        """,
        (user_id, correction_candidate_id, *sorted(prior_segment_ids)),
    ).fetchall()
    to_supersede: list[str] = []
    for item in candidates:
        evidence_relations = [
            str(rel["relation"] or "")
            for rel in conn.execute(
                """
                SELECT evidence_relation AS relation
                FROM memory_candidate_evidence
                WHERE candidate_id = ?
                """,
                (item["candidate_id"],),
            ).fetchall()
        ]
        args = _load_json(str(item["arguments_json"]))
        if not isinstance(args, list):
            args = []
        if looks_like_correction(
            {
                "candidate_kind": str(item["candidate_kind"] or ""),
                "arguments": args,
                "evidence": [{"relation": rel} for rel in evidence_relations],
            }
        ):
            continue
        to_supersede.append(str(item["candidate_id"]))
    if not to_supersede:
        return
    id_placeholders = ",".join("?" for _ in to_supersede)
    conn.execute(
        f"""
        UPDATE memory_claim_candidates
        SET status = 'superseded', updated_at = ?
        WHERE candidate_id IN ({id_placeholders})
        """,
        (now, *to_supersede),
    )
