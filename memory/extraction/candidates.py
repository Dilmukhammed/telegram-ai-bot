from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from memory.db import MemoryDatabase, dumps_json, loads_json_object, utc_now_iso
from memory.extraction.schemas import (
    CandidateArgument,
    Epistemic,
    JsonValue,
    Temporal,
    thaw_json,
)
from memory.ids import make_candidate_id
from memory.extraction.mentions import assert_exact_segment_span
from memory.models import LineageInput, LineageRelation
from memory.pointers import EvidencePointer, pointer_to_mapping

if TYPE_CHECKING:
    from memory.lineage import MemoryLineageStore


@dataclass(frozen=True, slots=True)
class CandidateEvidenceInput:
    segment_id: str
    relation: str
    pointer: EvidencePointer
    exact_quote: str
    context_pointer: EvidencePointer | None = None


@dataclass(frozen=True, slots=True)
class CandidateInput:
    local_ref: str
    segment_id: str
    kind: str
    schema_name: str
    schema_version: str
    arguments: tuple[CandidateArgument, ...]
    attributes: Mapping[str, JsonValue]
    polarity: str
    epistemic: Epistemic
    temporal: Temporal | None
    status: str
    evidence: tuple[CandidateEvidenceInput, ...]
    canonical_hint: str | None
    extractor_name: str
    extractor_version: str
    prompt_version: str
    cross_segment_mention_ids: Mapping[tuple[str, str], str] = field(default_factory=dict)


class MemoryCandidateStore:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    def insert_in_txn(
        self,
        conn: sqlite3.Connection,
        candidates: Sequence[CandidateInput],
        *,
        user_id: int,
        extraction_run_id: str,
        mention_ids: Mapping[tuple[str, str], str],
        lineage_store: "MemoryLineageStore",
    ) -> dict[tuple[str, str], str]:
        resolved: dict[tuple[str, str], str] = {}
        now = utc_now_iso()
        for candidate in candidates:
            merged_mention_ids = dict(mention_ids)
            merged_mention_ids.update(candidate.cross_segment_mention_ids)
            resolved_arguments, argument_mentions = _resolve_arguments(
                candidate,
                merged_mention_ids,
            )
            evidence_payload = []
            for evidence in candidate.evidence:
                _assert_evidence_owner(
                    conn,
                    segment_id=evidence.segment_id,
                    user_id=user_id,
                    source_version_id=evidence.pointer.source_version_id,
                )
                assert_exact_segment_span(
                    conn,
                    segment_id=evidence.segment_id,
                    user_id=user_id,
                    pointer=evidence.pointer,
                    expected_text=evidence.exact_quote,
                )
                evidence_payload.append(
                    {
                        "segment_id": evidence.segment_id,
                        "relation": evidence.relation,
                        "pointer": pointer_to_mapping(evidence.pointer),
                        "exact_quote": evidence.exact_quote,
                    }
                )
            if not evidence_payload:
                raise ValueError("candidate requires at least one evidence pointer")
            attributes = {str(k): thaw_json(v) for k, v in candidate.attributes.items()}
            epistemic = _epistemic_payload(candidate.epistemic)
            speaker_ref = candidate.epistemic.speaker_ref
            if speaker_ref not in (None, "self"):
                speaker_key = (candidate.segment_id, speaker_ref)
                speaker_id = mention_ids.get(speaker_key)
                if speaker_id is None:
                    raise ValueError(
                        f"candidate epistemic speaker references unknown mention: {speaker_key!r}"
                    )
                epistemic["speaker_ref"] = speaker_id
                argument_mentions = tuple(
                    dict.fromkeys((*argument_mentions, speaker_id))
                )
            temporal = _temporal_payload(candidate.temporal)
            semantic_payload = {
                "kind": candidate.kind,
                "schema_name": candidate.schema_name,
                "schema_version": candidate.schema_version,
                "arguments": resolved_arguments,
                "attributes": attributes,
                "polarity": candidate.polarity,
                "epistemic": epistemic,
                "temporal": temporal,
                "status": candidate.status,
                "evidence": evidence_payload,
            }
            candidate_id = make_candidate_id(
                user_id=user_id,
                semantic_payload=semantic_payload,
                extractor_name=candidate.extractor_name,
                extractor_version=candidate.extractor_version,
                prompt_version=candidate.prompt_version,
            )
            key = (candidate.segment_id, candidate.local_ref)
            previous = resolved.get(key)
            if previous is not None and previous != candidate_id:
                raise ValueError(f"duplicate local candidate reference: {key!r}")
            resolved[key] = candidate_id
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO memory_claim_candidates(
                    candidate_id, user_id, candidate_kind, schema_name, schema_version,
                    arguments_json, attributes_json, polarity, epistemic_json,
                    temporal_json, canonical_hint, status, extraction_run_id,
                    acceptance_policy, extractor_name, extractor_version,
                    prompt_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    user_id,
                    candidate.kind,
                    candidate.schema_name,
                    candidate.schema_version,
                    dumps_json(resolved_arguments),
                    dumps_json(attributes),
                    candidate.polarity,
                    dumps_json(epistemic),
                    dumps_json(temporal) if temporal is not None else None,
                    candidate.canonical_hint,
                    candidate.status,
                    extraction_run_id,
                    candidate.extractor_name,
                    candidate.extractor_version,
                    candidate.prompt_version,
                    now,
                    now,
                ),
            )
            for evidence in candidate.evidence:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO memory_candidate_evidence(
                        candidate_id, segment_id, evidence_relation, pointer_json,
                        exact_quote, context_pointer_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        evidence.segment_id,
                        evidence.relation,
                        dumps_json(pointer_to_mapping(evidence.pointer)),
                        evidence.exact_quote,
                        (
                            dumps_json(pointer_to_mapping(evidence.context_pointer))
                            if evidence.context_pointer is not None
                            else None
                        ),
                    ),
                )
            if cursor.rowcount:
                links = [
                    LineageInput(
                        parent_kind="segment",
                        parent_id=evidence.segment_id,
                        child_kind="candidate",
                        child_id=candidate_id,
                        relation=LineageRelation.DERIVED_FROM,
                    )
                    for evidence in candidate.evidence
                ]
                links.extend(
                    LineageInput(
                        parent_kind="mention",
                        parent_id=mention_id,
                        child_kind="candidate",
                        child_id=candidate_id,
                        relation=LineageRelation.DERIVED_FROM,
                    )
                    for mention_id in argument_mentions
                )
                lineage_store.add_links(conn, user_id=user_id, links=links)
        support_segment_ids = {
            evidence.segment_id
            for candidate in candidates
            if candidate.kind == "correction"
            for evidence in candidate.evidence
            if evidence.relation == "supports" and evidence.segment_id != candidate.segment_id
        }
        if support_segment_ids:
            placeholders = ",".join("?" for _ in support_segment_ids)
            conn.execute(
                f"""
                UPDATE memory_claim_candidates
                SET status = 'superseded', updated_at = ?
                WHERE user_id = ?
                  AND candidate_kind != 'correction'
                  AND status IN (
                      'proposed', 'needs_confirmation', 'ready_for_resolution',
                      'insufficient', 'contradicted'
                  )
                  AND candidate_id IN (
                    SELECT DISTINCT candidate_id
                    FROM memory_candidate_evidence
                    WHERE segment_id IN ({placeholders})
                  )
                """,
                (now, user_id, *sorted(support_segment_ids)),
            )
        return resolved

    def list_for_user(
        self,
        *,
        user_id: int,
        statuses: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [user_id]
        status_sql = ""
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            status_sql = f" AND status IN ({placeholders})"
            params.extend(statuses)
        with self._db.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_claim_candidates
                WHERE user_id = ? {status_sql}
                ORDER BY created_at, candidate_id
                """,
                tuple(params),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for field in ("arguments_json", "attributes_json", "epistemic_json"):
                item[field[:-5]] = loads_json_object(item[field]) if field != "arguments_json" else _loads_array(item[field])
            item["temporal"] = loads_json_object(item["temporal_json"]) if item["temporal_json"] else None
            result.append(item)
        return result


def _resolve_arguments(
    candidate: CandidateInput,
    mention_ids: Mapping[tuple[str, str], str],
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    resolved: list[dict[str, Any]] = []
    referenced: list[str] = []
    for argument in candidate.arguments:
        if argument.mention_ref is not None:
            key = (candidate.segment_id, argument.mention_ref)
            mention_id = mention_ids.get(key)
            if mention_id is None:
                raise ValueError(f"candidate references unknown mention: {key!r}")
            resolved.append({"role": argument.role, "mention_id": mention_id})
            referenced.append(mention_id)
        elif argument.has_literal:
            resolved.append({"role": argument.role, "literal": thaw_json(argument.literal)})
        else:
            raise ValueError("candidate argument has neither mention nor literal")
    return resolved, tuple(dict.fromkeys(referenced))


def _epistemic_payload(value: Epistemic) -> dict[str, Any]:
    return {
        "mode": value.mode.value,
        "speaker_commitment": value.speaker_commitment.value,
        "scope": value.scope.value,
        "alternatives": [thaw_json(item) for item in value.alternatives],
        "needs_confirmation": value.needs_confirmation,
        "speaker_ref": value.speaker_ref,
    }


def _temporal_payload(value: Temporal | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "original_text": value.original_text,
        "valid_from": value.valid_from,
        "valid_to": value.valid_to,
        "event_time": value.event_time,
        "precision": value.precision,
        "timezone": value.timezone,
    }


def _assert_evidence_owner(
    conn: sqlite3.Connection,
    *,
    segment_id: str,
    user_id: int,
    source_version_id: str,
) -> None:
    row = conn.execute(
        """
        SELECT seg.source_version_id, seg.status, s.user_id
        FROM memory_segments seg
        JOIN memory_source_versions v ON v.source_version_id = seg.source_version_id
        JOIN memory_sources s ON s.source_id = v.source_id
        WHERE seg.segment_id = ?
        """,
        (segment_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown evidence segment: {segment_id}")
    if int(row["user_id"]) != user_id:
        raise PermissionError("evidence segment belongs to another user")
    if row["source_version_id"] != source_version_id:
        raise ValueError("evidence pointer source version mismatch")
    if row["status"] != "active":
        raise RuntimeError("candidate cannot use inactive evidence")


def _loads_array(raw: str) -> list[Any]:
    import json

    value = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError("stored arguments_json is not an array")
    return value
