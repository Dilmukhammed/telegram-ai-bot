from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from memory.attachment.taxonomy import normalize_label


@dataclass(frozen=True, slots=True)
class AttachmentContextPack:
    belief_id: str
    schema_name: str
    polarity: str | None
    epistemic: Mapping[str, Any]
    statement: str
    source_entity_id: str | None
    source_label: str
    source_entity_type: str | None
    attach_domains: tuple[str, ...]
    neighbor_entities: tuple[dict[str, Any], ...]
    existing_attachments: tuple[dict[str, Any], ...]
    domain_preferences: tuple[dict[str, Any], ...]
    recent_corrections: tuple[str, ...]


def load_context_pack(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    belief_id: str,
    attach_domains: tuple[str, ...],
    source_entity_id: str | None,
    source_label: str,
    source_entity_type: str | None,
) -> AttachmentContextPack | None:
    row = conn.execute(
        """
        SELECT b.belief_id, b.schema_name, b.proposition_key,
               r.polarity, r.belief_status, r.utility_class,
               r.resolved_arguments_json
        FROM memory_belief_heads h
        JOIN memory_beliefs b ON b.belief_id = h.belief_id
        JOIN memory_belief_revisions r ON r.belief_revision_id = h.belief_revision_id
        WHERE h.belief_id = ? AND h.user_id = ?
        """,
        (belief_id, user_id),
    ).fetchone()
    if row is None:
        return None

    args = _load_args(row["resolved_arguments_json"])
    statement = source_label or str(row["proposition_key"] or belief_id)
    neighbors = _load_neighbors(conn, user_id=user_id, entity_id=source_entity_id)
    existing = _load_existing_attachments(
        conn, user_id=user_id, source_entity_id=source_entity_id
    )
    prefs = _load_domain_preferences(conn, user_id=user_id, domains=attach_domains)
    corrections = _load_recent_corrections(conn, user_id=user_id, belief_id=belief_id)
    return AttachmentContextPack(
        belief_id=belief_id,
        schema_name=str(row["schema_name"]),
        polarity=str(row["polarity"]) if row["polarity"] else None,
        epistemic={},
        statement=statement,
        source_entity_id=source_entity_id,
        source_label=source_label,
        source_entity_type=source_entity_type,
        attach_domains=attach_domains,
        neighbor_entities=neighbors,
        existing_attachments=existing,
        domain_preferences=prefs,
        recent_corrections=corrections,
    )


def _load_args(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [a for a in parsed if isinstance(a, dict)] if isinstance(parsed, list) else []
    if isinstance(raw, list):
        return [a for a in raw if isinstance(a, dict)]
    return []


def _load_neighbors(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    entity_id: str | None,
    limit: int = 12,
) -> tuple[dict[str, Any], ...]:
    if not entity_id:
        return ()
    rows = conn.execute(
        """
        SELECT e.edge_type, e.from_node_id, e.to_node_id, e.properties_json,
               n.label, n.source_record_id
        FROM graph_edges e
        JOIN graph_nodes n ON n.node_id IN (e.from_node_id, e.to_node_id)
        WHERE e.user_id = ? AND e.status = 'active'
          AND (e.from_node_id IN (
                SELECT node_id FROM graph_nodes
                WHERE user_id = ? AND source_record_id = ?
              )
               OR e.to_node_id IN (
                SELECT node_id FROM graph_nodes
                WHERE user_id = ? AND source_record_id = ?
              ))
        LIMIT ?
        """,
        (user_id, user_id, entity_id, user_id, entity_id, limit),
    ).fetchall()
    return tuple(dict(row) for row in rows)


def _load_existing_attachments(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    source_entity_id: str | None,
) -> tuple[dict[str, Any], ...]:
    if not source_entity_id:
        return ()
    rows = conn.execute(
        """
        SELECT op, target_entity_id, utility_class, status, tier
        FROM memory_attachment_events
        WHERE user_id = ? AND source_entity_id = ? AND status = 'active'
        """,
        (user_id, source_entity_id),
    ).fetchall()
    return tuple(dict(row) for row in rows)


def _load_domain_preferences(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    domains: tuple[str, ...],
    limit: int = 8,
) -> tuple[dict[str, Any], ...]:
    if not domains:
        return ()
    rows = conn.execute(
        """
        SELECT b.belief_id, b.schema_name, b.proposition_key, r.utility_class
        FROM memory_belief_heads h
        JOIN memory_beliefs b ON b.belief_id = h.belief_id
        JOIN memory_belief_revisions r ON r.belief_revision_id = h.belief_revision_id
        WHERE h.user_id = ? AND r.belief_status = 'active'
        ORDER BY r.created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return tuple(dict(row) for row in rows)


def _load_recent_corrections(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    belief_id: str,
    limit: int = 5,
) -> tuple[str, ...]:
    rows = conn.execute(
        """
        SELECT cluster_key FROM memory_beliefs WHERE belief_id = ? AND user_id = ?
        """,
        (belief_id, user_id),
    ).fetchone()
    if rows is None:
        return ()
    cluster_key = str(rows["cluster_key"])
    corr = conn.execute(
        """
        SELECT belief_id FROM memory_beliefs
        WHERE user_id = ? AND cluster_key = ? AND belief_id != ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, cluster_key, belief_id, limit),
    ).fetchall()
    return tuple(str(r["belief_id"]) for r in corr)


def lexical_overlap(a: str, b: str) -> float:
    ta = set(normalize_label(a).split())
    tb = set(normalize_label(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
