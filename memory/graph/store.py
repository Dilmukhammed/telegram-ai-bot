from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from memory.db import MemoryDatabase, dumps_json, utc_now_iso
from memory.graph.schemas import (
    BELIEF_POLICY_VERSION,
    EDGE_STATUS_ACTIVE,
    EDGE_STATUS_EXPIRED,
    GRAPH_SCHEMA_VERSION,
    MATERIALIZER_VERSION,
    NODE_STATUS_ACTIVE,
)
from memory.ids import make_graph_edge_id, make_graph_node_id


class MemoryGraphStore:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    def ensure_revision_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
    ) -> int:
        row = conn.execute(
            "SELECT current_revision FROM graph_revisions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is not None:
            return int(row["current_revision"])
        conn.execute(
            """
            INSERT INTO graph_revisions(
                user_id, current_revision, last_materialized_at,
                materializer_version, graph_schema_version, belief_policy_version
            ) VALUES (?, 0, NULL, ?, ?, ?)
            """,
            (
                user_id,
                MATERIALIZER_VERSION,
                GRAPH_SCHEMA_VERSION,
                BELIEF_POLICY_VERSION,
            ),
        )
        return 0

    def bump_revision_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
    ) -> int:
        now = utc_now_iso()
        self.ensure_revision_in_txn(conn, user_id=user_id)
        conn.execute(
            """
            UPDATE graph_revisions
            SET current_revision = current_revision + 1,
                last_materialized_at = ?,
                materializer_version = ?,
                graph_schema_version = ?,
                belief_policy_version = ?
            WHERE user_id = ?
            """,
            (
                now,
                MATERIALIZER_VERSION,
                GRAPH_SCHEMA_VERSION,
                BELIEF_POLICY_VERSION,
                user_id,
            ),
        )
        row = conn.execute(
            "SELECT current_revision FROM graph_revisions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row["current_revision"])

    def current_revision(self, user_id: int) -> int:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT current_revision FROM graph_revisions WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row["current_revision"]) if row else 0

    def upsert_node_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        node_type: str,
        source_record_id: str,
        label: str | None,
        properties: Mapping[str, Any] | None,
        graph_revision: int,
    ) -> str:
        node_id = make_graph_node_id(
            user_id=user_id,
            node_type=node_type,
            source_record_id=source_record_id,
        )
        now = utc_now_iso()
        props = dumps_json(dict(properties or {}))
        existing = conn.execute(
            "SELECT node_id FROM graph_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO graph_nodes(
                    node_id, user_id, node_type, source_record_id, label,
                    properties_json, embedding_json, status, graph_revision,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    node_id,
                    user_id,
                    node_type,
                    source_record_id,
                    label,
                    props,
                    NODE_STATUS_ACTIVE,
                    graph_revision,
                    now,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE graph_nodes
                SET label = ?, properties_json = ?, status = ?,
                    graph_revision = ?, updated_at = ?
                WHERE node_id = ? AND user_id = ?
                """,
                (
                    label,
                    props,
                    NODE_STATUS_ACTIVE,
                    graph_revision,
                    now,
                    node_id,
                    user_id,
                ),
            )
        return node_id

    def upsert_edge_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        belief_id: str,
        from_node_id: str,
        to_node_id: str,
        edge_type: str,
        properties: Mapping[str, Any] | None,
        payload_hash: str,
        graph_revision: int,
    ) -> str:
        edge_id = make_graph_edge_id(
            user_id=user_id,
            belief_id=belief_id,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            edge_type=edge_type,
        )
        now = utc_now_iso()
        props = dumps_json(dict(properties or {}))
        existing = conn.execute(
            "SELECT edge_id, payload_hash, status FROM graph_edges WHERE edge_id = ?",
            (edge_id,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO graph_edges(
                    edge_id, user_id, from_node_id, to_node_id, edge_type,
                    belief_id, properties_json, valid_from, valid_to, status,
                    graph_revision, payload_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    edge_id,
                    user_id,
                    from_node_id,
                    to_node_id,
                    edge_type,
                    belief_id,
                    props,
                    EDGE_STATUS_ACTIVE,
                    graph_revision,
                    payload_hash,
                    now,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE graph_edges
                SET properties_json = ?, status = ?, graph_revision = ?,
                    payload_hash = ?, updated_at = ?, valid_to = NULL
                WHERE edge_id = ? AND user_id = ?
                """,
                (
                    props,
                    EDGE_STATUS_ACTIVE,
                    graph_revision,
                    payload_hash,
                    now,
                    edge_id,
                    user_id,
                ),
            )
        return edge_id

    def expire_edges_for_belief_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        belief_id: str,
        graph_revision: int,
    ) -> int:
        now = utc_now_iso()
        updated = conn.execute(
            """
            UPDATE graph_edges
            SET status = ?, valid_to = ?, graph_revision = ?, updated_at = ?
            WHERE user_id = ? AND belief_id = ? AND status = ?
            """,
            (
                EDGE_STATUS_EXPIRED,
                now,
                graph_revision,
                now,
                user_id,
                belief_id,
                EDGE_STATUS_ACTIVE,
            ),
        )
        return int(updated.rowcount)

    def list_active_edges(self, *, user_id: int) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM graph_edges
                WHERE user_id = ? AND status = ?
                ORDER BY edge_type, edge_id
                """,
                (user_id, EDGE_STATUS_ACTIVE),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_active_nodes(self, *, user_id: int) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM graph_nodes
                WHERE user_id = ? AND status = ?
                ORDER BY node_type, source_record_id
                """,
                (user_id, NODE_STATUS_ACTIVE),
            ).fetchall()
        return [dict(row) for row in rows]

    def wipe_user_projection_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
    ) -> None:
        conn.execute("DELETE FROM graph_edges WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM graph_nodes WHERE user_id = ?", (user_id,))
        conn.execute(
            """
            UPDATE graph_revisions
            SET current_revision = 0, last_materialized_at = NULL
            WHERE user_id = ?
            """,
            (user_id,),
        )
        self.ensure_revision_in_txn(conn, user_id=user_id)
