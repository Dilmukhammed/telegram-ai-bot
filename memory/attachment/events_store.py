from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from memory.db import MemoryDatabase, dumps_json, utc_now_iso
from memory.ids import make_attachment_event_id
from memory.attachment.schemas import ATTACHMENT_VERSION


@dataclass(frozen=True, slots=True)
class AttachmentEventRecord:
    event_id: str
    user_id: int
    op: str
    source_belief_id: str | None
    source_entity_id: str
    target_entity_id: str
    domain_pack: str
    tier: str
    status: str
    utility_class: str
    evidence_hash: str
    layer_trace_json: str
    created_at: str


class AttachmentEventsStore:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    def insert_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        op: str,
        source_belief_id: str | None,
        source_entity_id: str,
        target_entity_id: str,
        domain_pack: str,
        tier: str,
        status: str,
        utility_class: str,
        evidence: Mapping[str, Any],
        evidence_hash: str,
        critic_report: Mapping[str, Any] | None,
        layer_trace: Mapping[str, Any],
        input_hash: str,
        resolver_version: str,
        graph_revision: int | None = None,
        supersedes_event_id: str | None = None,
    ) -> str:
        event_id = make_attachment_event_id(
            user_id=user_id,
            op=op,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            evidence_hash=evidence_hash,
            attachment_version=ATTACHMENT_VERSION,
        )
        now = utc_now_iso()
        prior = conn.execute(
            """
            SELECT event_id FROM memory_attachment_events
            WHERE user_id=? AND op=? AND source_entity_id=? AND target_entity_id=?
              AND attachment_version=? AND status='active'
            ORDER BY created_at DESC,event_id DESC LIMIT 1
            """,
            (
                user_id,
                op,
                source_entity_id,
                target_entity_id,
                ATTACHMENT_VERSION,
            ),
        ).fetchone()
        prior_event_id = str(prior["event_id"]) if prior is not None else None
        if prior_event_id and prior_event_id != event_id and status == "active":
            conn.execute(
                """
                UPDATE memory_attachment_events SET status='reverted'
                WHERE user_id=? AND op=? AND source_entity_id=? AND target_entity_id=?
                  AND attachment_version=? AND status='active'
                """,
                (
                    user_id,
                    op,
                    source_entity_id,
                    target_entity_id,
                    ATTACHMENT_VERSION,
                ),
            )
        effective_supersedes = supersedes_event_id or (
            prior_event_id if prior_event_id != event_id else None
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO memory_attachment_events(
                event_id, user_id, op, source_belief_id, source_entity_id,
                target_entity_id, domain_pack, tier, status, utility_class,
                evidence_json, evidence_hash, critic_report_json, layer_trace_json,
                input_hash, resolver_version, attachment_version,
                supersedes_event_id, graph_revision, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                user_id,
                op,
                source_belief_id,
                source_entity_id,
                target_entity_id,
                domain_pack,
                tier,
                status,
                utility_class,
                dumps_json(dict(evidence)),
                evidence_hash,
                dumps_json(dict(critic_report)) if critic_report else None,
                dumps_json(dict(layer_trace)),
                input_hash,
                resolver_version,
                ATTACHMENT_VERSION,
                effective_supersedes,
                graph_revision,
                now,
            ),
        )
        return event_id

    def list_for_user(
        self,
        *,
        user_id: int,
        limit: int = 50,
        status: str | None = None,
    ) -> list[AttachmentEventRecord]:
        with self._db.connection() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM memory_attachment_events
                    WHERE user_id = ? AND status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM memory_attachment_events
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
        return [_row_to_record(row) for row in rows]

    def count_active(self, *, user_id: int) -> int:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM memory_attachment_events
                WHERE user_id = ? AND status = 'active'
                """,
                (user_id,),
            ).fetchone()
        return int(row["c"]) if row else 0

    def revert_for_belief_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        belief_id: str,
        reason: str,
    ) -> int:
        """Revert every derived event whose source belief changed.

        The reason is part of the caller's reconciliation trace.  Event rows
        remain immutable apart from lifecycle status so their original critic
        evidence is preserved for audit and possible re-analysis.
        """
        del reason
        changed = conn.execute(
            """
            UPDATE memory_attachment_events
            SET status = 'reverted'
            WHERE user_id = ? AND source_belief_id = ?
              AND status IN ('active', 'possible')
            """,
            (user_id, belief_id),
        )
        return int(changed.rowcount)

    def insert_dependencies_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        user_id: int,
        dependencies: list[Mapping[str, Any]],
    ) -> int:
        now = utc_now_iso()
        inserted = 0
        for dependency in dependencies:
            dependency_type = str(dependency.get("dependency_type") or "")
            dependency_id = str(dependency.get("dependency_id") or "")
            if not dependency_type or not dependency_id:
                continue
            result = conn.execute(
                """
                INSERT OR IGNORE INTO memory_attachment_dependencies(
                    event_id,user_id,dependency_type,dependency_id,path_json,status,created_at
                ) VALUES (?,?,?,?,?,'active',?)
                """,
                (
                    event_id,
                    user_id,
                    dependency_type,
                    dependency_id,
                    dumps_json(dependency.get("path")) if dependency.get("path") else None,
                    now,
                ),
            )
            inserted += int(result.rowcount)
        return inserted


def _row_to_record(row: Any) -> AttachmentEventRecord:
    return AttachmentEventRecord(
        event_id=str(row["event_id"]),
        user_id=int(row["user_id"]),
        op=str(row["op"]),
        source_belief_id=row["source_belief_id"],
        source_entity_id=str(row["source_entity_id"]),
        target_entity_id=str(row["target_entity_id"]),
        domain_pack=str(row["domain_pack"]),
        tier=str(row["tier"]),
        status=str(row["status"]),
        utility_class=str(row["utility_class"]),
        evidence_hash=str(row["evidence_hash"]),
        layer_trace_json=str(row["layer_trace_json"]),
        created_at=str(row["created_at"]),
    )
