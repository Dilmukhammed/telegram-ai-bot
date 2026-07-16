from __future__ import annotations

import json
import sqlite3
from typing import Any

from memory.attachment.schemas import ATTACHMENT_VERSION
from memory.db import MemoryDatabase, utc_now_iso
from memory.graph.store import MemoryGraphStore


class AttachmentMaterializer:
    def __init__(self, db: MemoryDatabase, *, store: MemoryGraphStore | None = None) -> None:
        self._db = db
        self._store = store or MemoryGraphStore(db)

    def materialize_active_events(self, *, user_id: int, limit: int = 50) -> int:
        return self.reconcile_events(user_id=user_id, limit=limit)

    def reconcile_events(self, *, user_id: int, limit: int = 200) -> int:
        """Make attachment graph edges equal the durable event state.

        This is deliberately diff-based: an unchanged rerun performs no writes
        and does not advance the graph revision. Reverted/missing events expire
        only ``attach:*`` edges; the source belief's ordinary graph edge is not
        touched.
        """
        with self._db.transaction(immediate=True) as conn:
            event_rows = conn.execute(
                """
                SELECT event_id, op, source_belief_id, source_entity_id, target_entity_id,
                       utility_class, domain_pack, tier, status
                FROM memory_attachment_events
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            event_by_id = {str(row["event_id"]): row for row in event_rows}
            edge_rows = conn.execute(
                """
                SELECT edge_id, status, payload_hash, properties_json
                FROM graph_edges
                WHERE user_id = ? AND edge_type LIKE 'attach:%'
                """,
                (user_id,),
            ).fetchall()
            edge_by_event: dict[str, Any] = {}
            for edge in edge_rows:
                try:
                    props = json.loads(str(edge["properties_json"] or "{}"))
                except json.JSONDecodeError:
                    props = {}
                event_id = str(props.get("event_id") or edge["payload_hash"] or "")
                if event_id:
                    edge_by_event[event_id] = edge

            to_materialize = []
            to_expire = []
            for event_id, event in event_by_id.items():
                edge = edge_by_event.get(event_id)
                if str(event["status"]) == "active":
                    if edge is None or str(edge["status"]) != "active" or str(edge["payload_hash"]) != event_id:
                        to_materialize.append(event)
                elif edge is not None and str(edge["status"]) == "active":
                    to_expire.append(str(edge["edge_id"]))
            for event_id, edge in edge_by_event.items():
                if event_id not in event_by_id and str(edge["status"]) == "active":
                    to_expire.append(str(edge["edge_id"]))

            if not to_materialize and not to_expire:
                return 0
            revision = self._store.bump_revision_in_txn(conn, user_id=user_id)
            now = utc_now_iso()
            for edge_id in sorted(set(to_expire)):
                conn.execute(
                    """
                    UPDATE graph_edges
                    SET status='expired', valid_to=?, graph_revision=?, updated_at=?
                    WHERE edge_id=? AND user_id=? AND status='active'
                    """,
                    (now, revision, now, edge_id, user_id),
                )
            for row in to_materialize:
                self._materialize_row(conn, user_id=user_id, row=row, revision=revision)
                conn.execute(
                    "UPDATE memory_attachment_events SET graph_revision=? WHERE event_id=?",
                    (revision, str(row["event_id"])),
                )
        return len(to_materialize) + len(set(to_expire))

    def _materialize_row(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        row: Any,
        revision: int,
    ) -> None:
        source_id = str(row["source_entity_id"])
        target_id = str(row["target_entity_id"])
        op = str(row["op"])
        # graph_edges.belief_id FK → memory_beliefs; never use event_id here.
        belief_id = row["source_belief_id"]
        if not belief_id:
            return
        belief_id = str(belief_id)
        from_node = self._ensure_entity_node(
            conn, user_id=user_id, entity_id=source_id, revision=revision
        )
        to_node = self._ensure_entity_node(
            conn, user_id=user_id, entity_id=target_id, revision=revision
        )
        if from_node is None or to_node is None:
            return
        edge_type = f"attach:{op}"
        self._store.upsert_edge_in_txn(
            conn,
            user_id=user_id,
            belief_id=belief_id,
            from_node_id=from_node,
            to_node_id=to_node,
            edge_type=edge_type,
            properties={
                "event_id": row["event_id"],
                "utility_class": row["utility_class"],
                "domain_pack": row["domain_pack"],
                "tier": row["tier"],
                "attachment_version": ATTACHMENT_VERSION,
            },
            payload_hash=str(row["event_id"]),
            graph_revision=revision,
        )

    def _ensure_entity_node(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        entity_id: str,
        revision: int,
    ) -> str | None:
        entity = conn.execute(
            """
            SELECT entity_id, entity_type, identity_key, canonical_label, status
            FROM memory_entities
            WHERE entity_id = ? AND user_id = ?
            """,
            (entity_id, user_id),
        ).fetchone()
        if entity is None:
            community = conn.execute(
                """
                SELECT community_id,community_type,label,status
                FROM graph_communities
                WHERE community_id=? AND user_id=?
                """,
                (entity_id, user_id),
            ).fetchone()
            if community is None:
                return None
            return self._store.upsert_node_in_txn(
                conn,
                user_id=user_id,
                node_type="community",
                source_record_id=str(community["community_id"]),
                label=str(community["label"] or community["community_id"]),
                properties={
                    "community_type": str(community["community_type"]),
                    "community_status": str(community["status"]),
                },
                graph_revision=revision,
            )
        node_type = "concept" if str(entity["entity_type"]) == "concept" else "entity"
        return self._store.upsert_node_in_txn(
            conn,
            user_id=user_id,
            node_type=node_type,
            source_record_id=str(entity["entity_id"]),
            label=str(entity["canonical_label"] or entity["identity_key"]),
            properties={
                "entity_type": str(entity["entity_type"]),
                "identity_key": str(entity["identity_key"]),
                "entity_status": str(entity["status"]),
            },
            graph_revision=revision,
        )
