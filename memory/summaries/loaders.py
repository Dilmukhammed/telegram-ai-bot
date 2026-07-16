from __future__ import annotations

import json
import sqlite3
from typing import Any

from memory.retrieval.corpus import load_belief_heads
from memory.summaries.schemas import BeliefSnapshot


def load_belief_snapshots(
    conn: sqlite3.Connection,
    *,
    user_id: int,
) -> tuple[BeliefSnapshot, ...]:
    docs = load_belief_heads(conn, user_id=user_id)
    return tuple(_doc_to_snapshot(doc) for doc in docs)


def load_belief_snapshot_by_id(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    belief_id: str,
) -> BeliefSnapshot | None:
    for item in load_belief_snapshots(conn, user_id=user_id):
        if item.belief_id == belief_id:
            return item
    return None


def _doc_to_snapshot(doc: Any) -> BeliefSnapshot:
    temporal = dict(doc.temporal) if doc.temporal else None
    return BeliefSnapshot(
        belief_id=str(doc.belief_id),
        schema_name=str(doc.schema_name),
        statement=str(doc.statement),
        belief_status=str(doc.belief_status),
        utility_class=str(doc.utility_class),
        polarity=str(doc.polarity),
        entity_ids=tuple(str(e) for e in doc.entity_ids),
        temporal=temporal,
    )


def load_graph_snapshot(
    conn: sqlite3.Connection,
    *,
    user_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    revision_row = conn.execute(
        "SELECT current_revision FROM graph_revisions WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    revision = int(revision_row["current_revision"]) if revision_row else 0
    nodes = [
        dict(row)
        for row in conn.execute(
            """
            SELECT node_id, node_type, source_record_id, label, properties_json, status
            FROM graph_nodes
            WHERE user_id = ? AND status = 'active'
            """,
            (user_id,),
        ).fetchall()
    ]
    edges = [
        dict(row)
        for row in conn.execute(
            """
            SELECT edge_id, from_node_id, to_node_id, edge_type, belief_id, status
            FROM graph_edges
            WHERE user_id = ? AND status = 'active'
            """,
            (user_id,),
        ).fetchall()
    ]
    for node in nodes:
        node["properties"] = _loads_obj(node.pop("properties_json", None))
    return nodes, edges, revision


def _loads_obj(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    parsed = json.loads(raw)
    return dict(parsed) if isinstance(parsed, dict) else {}
