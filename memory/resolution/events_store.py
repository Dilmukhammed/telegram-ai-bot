from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Mapping, Sequence

from memory.db import dumps_json
from memory.ids import canonical_json, make_resolution_event_id
from memory.resolution.er_types import AliasEquivalenceRecord, MergeEventRecord
from memory.resolution.schemas import RESOLVER_VERSION


def evidence_hash(evidence: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(evidence)).encode("utf-8")).hexdigest()


def build_merge_event(
    *,
    user_id: int,
    winner_entity_id: str,
    loser_entity_id: str,
    cluster_key: str | None,
    tier: str,
    evidence: Mapping[str, Any],
    reason: str,
    decided_by: str,
    resolver_version: str = RESOLVER_VERSION,
    resolution_run_id: str | None = None,
    supersedes_event_id: str | None = None,
) -> MergeEventRecord:
    payload = dict(evidence)
    if resolution_run_id:
        payload["resolution_run_id"] = resolution_run_id
    digest = evidence_hash(payload)
    return MergeEventRecord(
        event_id=make_resolution_event_id(
            user_id=user_id,
            op="merge",
            winner_entity_id=winner_entity_id,
            loser_entity_id=loser_entity_id,
            evidence_hash=digest,
            resolver_version=resolver_version,
        ),
        op="merge",
        winner_entity_id=winner_entity_id,
        loser_entity_id=loser_entity_id,
        cluster_key=cluster_key,
        tier=tier,
        evidence_json=payload,
        evidence_hash=digest,
        reason=reason,
        decided_by=decided_by,
        supersedes_event_id=supersedes_event_id,
        status="active",
    )


def build_split_event(
    *,
    user_id: int,
    winner_entity_id: str,
    loser_entity_id: str,
    cluster_key: str | None,
    tier: str,
    evidence: Mapping[str, Any],
    reason: str,
    decided_by: str,
    merge_event_id: str,
    resolver_version: str = RESOLVER_VERSION,
    resolution_run_id: str | None = None,
) -> MergeEventRecord:
    payload = dict(evidence)
    payload["reverted_merge_event_id"] = merge_event_id
    if resolution_run_id:
        payload["resolution_run_id"] = resolution_run_id
    digest = evidence_hash(payload)
    return MergeEventRecord(
        event_id=make_resolution_event_id(
            user_id=user_id,
            op="split",
            winner_entity_id=winner_entity_id,
            loser_entity_id=loser_entity_id,
            evidence_hash=digest,
            resolver_version=resolver_version,
        ),
        op="split",
        winner_entity_id=winner_entity_id,
        loser_entity_id=loser_entity_id,
        cluster_key=cluster_key,
        tier=tier,
        evidence_json=payload,
        evidence_hash=digest,
        reason=reason,
        decided_by=decided_by,
        supersedes_event_id=merge_event_id,
        status="active",
    )


def insert_events_in_txn(
    conn: sqlite3.Connection,
    user_id: int,
    events: Sequence[MergeEventRecord],
    *,
    resolution_run_id: str | None,
    now: str,
    resolver_version: str = RESOLVER_VERSION,
) -> None:
    for event in events:
        payload = dict(event.evidence_json)
        if resolution_run_id and "resolution_run_id" not in payload:
            payload["resolution_run_id"] = resolution_run_id
        conn.execute(
            """
            INSERT OR IGNORE INTO memory_entity_resolution_events(
                event_id, user_id, op, winner_entity_id, loser_entity_id,
                cluster_key, tier, evidence_json, evidence_hash, reason, decided_by,
                supersedes_event_id, resolver_version, resolution_run_id,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                user_id,
                event.op,
                event.winner_entity_id,
                event.loser_entity_id,
                event.cluster_key,
                event.tier,
                dumps_json(payload),
                event.evidence_hash,
                event.reason,
                event.decided_by,
                event.supersedes_event_id,
                resolver_version,
                resolution_run_id,
                event.status,
                now,
            ),
        )


def list_active_merges_for_loser(
    conn: sqlite3.Connection,
    user_id: int,
    entity_id: str,
) -> list[sqlite3.Row]:
    try:
        return list(
            conn.execute(
                """
                SELECT *
                FROM memory_entity_resolution_events
                WHERE user_id = ?
                  AND status = 'active'
                  AND op = 'merge'
                  AND loser_entity_id = ?
                ORDER BY created_at, event_id
                """,
                (user_id, entity_id),
            ).fetchall()
        )
    except sqlite3.OperationalError:
        return []


def find_merges_touching_evidence(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    alias_ids: Sequence[str] = (),
    verdict_ids: Sequence[str] = (),
    mention_ids: Sequence[str] = (),
) -> list[dict[str, Any]]:
    needles = {
        *alias_ids,
        *verdict_ids,
        *mention_ids,
    }
    if not needles:
        return []
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM memory_entity_resolution_events
            WHERE user_id = ?
              AND status = 'active'
              AND op = 'merge'
            ORDER BY created_at, event_id
            """,
            (user_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    touched: list[dict[str, Any]] = []
    for row in rows:
        evidence = _load_evidence(row["evidence_json"])
        if _evidence_intersects(evidence, needles):
            touched.append(dict(row))
    return touched


def insert_equivalence_in_txn(
    conn: sqlite3.Connection,
    user_id: int,
    record: AliasEquivalenceRecord,
    *,
    now: str,
    status: str = "active",
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO memory_entity_alias_equivalences(
            equivalence_id, user_id,
            normalized_alias_a, language_a,
            normalized_alias_b, language_b,
            entity_type, source, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.equivalence_id,
            user_id,
            record.normalized_alias_a,
            record.language_a,
            record.normalized_alias_b,
            record.language_b,
            record.entity_type,
            record.source,
            status,
            now,
        ),
    )


def lookup_equivalences(
    conn: sqlite3.Connection,
    user_id: int,
    entity_type: str,
    normalized_alias: str,
) -> list[AliasEquivalenceRecord]:
    try:
        rows = conn.execute(
            """
            SELECT equivalence_id, normalized_alias_a, language_a,
                   normalized_alias_b, language_b, entity_type, source
            FROM memory_entity_alias_equivalences
            WHERE user_id = ?
              AND entity_type = ?
              AND status = 'active'
              AND (normalized_alias_a = ? OR normalized_alias_b = ?)
            ORDER BY created_at, equivalence_id
            """,
            (user_id, entity_type, normalized_alias, normalized_alias),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        AliasEquivalenceRecord(
            equivalence_id=str(row["equivalence_id"]),
            normalized_alias_a=str(row["normalized_alias_a"]),
            language_a=row["language_a"],
            normalized_alias_b=str(row["normalized_alias_b"]),
            language_b=row["language_b"],
            entity_type=str(row["entity_type"]),
            source=str(row["source"]),
        )
        for row in rows
    ]


def _load_evidence(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _evidence_intersects(evidence: Mapping[str, Any], needles: set[str]) -> bool:
    for value in _walk_values(evidence):
        if isinstance(value, str) and value in needles:
            return True
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                if isinstance(item, str) and item in needles:
                    return True
    return False


def _walk_values(value: Any) -> Any:
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _walk_values(item)
        return
    if isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
        return
    yield value
