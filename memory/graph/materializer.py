from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from memory.db import MemoryDatabase
from memory.graph.outbox import MemoryGraphOutbox
from memory.graph.schemas import (
    OUTBOX_EXPIRE,
    OUTBOX_REMOVE,
    OUTBOX_REBUILD_USER,
    OUTBOX_UPSERT,
    SUBJECT_ROLES,
    edge_type_for,
    is_materializable,
)
from memory.graph.store import MemoryGraphStore
from memory.ids import canonical_json


@dataclass(frozen=True, slots=True)
class MaterializeResult:
    belief_id: str
    operation: str
    edge_id: str | None
    node_ids: tuple[str, ...]
    skipped: bool
    reason: str | None = None


class GraphMaterializer:
    def __init__(
        self,
        db: MemoryDatabase,
        *,
        store: MemoryGraphStore | None = None,
        outbox: MemoryGraphOutbox | None = None,
        summary_invalidator: object | None = None,
        attachment_invalidator: object | None = None,
    ) -> None:
        self._db = db
        self._store = store or MemoryGraphStore(db)
        self._outbox = outbox or MemoryGraphOutbox(db)
        self._summary_invalidator = summary_invalidator
        self._attachment_invalidator = attachment_invalidator

    def process_event(
        self,
        *,
        user_id: int,
        belief_id: str,
        operation: str,
    ) -> MaterializeResult:
        if operation == OUTBOX_REBUILD_USER:
            from memory.graph.rebuild import rebuild_user_graph

            rebuild_user_graph(self._db, user_id=user_id, store=self._store)
            return MaterializeResult(
                belief_id=belief_id,
                operation=operation,
                edge_id=None,
                node_ids=(),
                skipped=False,
            )
        if operation in {OUTBOX_REMOVE, OUTBOX_EXPIRE}:
            return self._expire_belief(user_id=user_id, belief_id=belief_id)
        if operation == OUTBOX_UPSERT:
            return self._upsert_belief(user_id=user_id, belief_id=belief_id)
        raise ValueError(f"unknown graph outbox operation: {operation!r}")

    def drain_once(self, *, limit: int = 50) -> list[MaterializeResult]:
        events = self._outbox.claim(limit=limit)
        results: list[MaterializeResult] = []
        for event in events:
            try:
                result = self.process_event(
                    user_id=event.user_id,
                    belief_id=event.belief_id,
                    operation=event.operation,
                )
                self._outbox.mark_done(event.event_id)
                results.append(result)
            except Exception as exc:  # noqa: BLE001 - quarantine bad events
                self._outbox.mark_failed(event.event_id, error=str(exc))
                results.append(
                    MaterializeResult(
                        belief_id=event.belief_id,
                        operation=event.operation,
                        edge_id=None,
                        node_ids=(),
                        skipped=True,
                        reason=str(exc),
                    )
                )
        return results

    def materialize_belief(
        self,
        *,
        user_id: int,
        belief_id: str,
    ) -> MaterializeResult:
        head = self._load_head(user_id=user_id, belief_id=belief_id)
        if head is None:
            return self._expire_belief(user_id=user_id, belief_id=belief_id)
        if not is_materializable(
            belief_status=str(head["belief_status"]),
            utility_class=str(head["utility_class"]),
        ):
            return self._expire_belief(user_id=user_id, belief_id=belief_id)
        return self._upsert_belief(user_id=user_id, belief_id=belief_id)

    def _expire_belief(self, *, user_id: int, belief_id: str) -> MaterializeResult:
        with self._db.transaction(immediate=True) as conn:
            revision = self._store.bump_revision_in_txn(conn, user_id=user_id)
            count = self._store.expire_edges_for_belief_in_txn(
                conn,
                user_id=user_id,
                belief_id=belief_id,
                graph_revision=revision,
            )
            self._mark_summary_dirty_in_txn(conn, user_id=user_id, belief_id=belief_id)
        return MaterializeResult(
            belief_id=belief_id,
            operation=OUTBOX_REMOVE,
            edge_id=None,
            node_ids=(),
            skipped=count == 0,
            reason="expired" if count else "nothing_to_expire",
        )

    def _upsert_belief(self, *, user_id: int, belief_id: str) -> MaterializeResult:
        head = self._load_head(user_id=user_id, belief_id=belief_id)
        if head is None:
            return MaterializeResult(
                belief_id=belief_id,
                operation=OUTBOX_UPSERT,
                edge_id=None,
                node_ids=(),
                skipped=True,
                reason="missing_head",
            )
        if not is_materializable(
            belief_status=str(head["belief_status"]),
            utility_class=str(head["utility_class"]),
        ):
            return self._expire_belief(user_id=user_id, belief_id=belief_id)

        args = _load_args(head.get("resolved_arguments_json"))
        schema_name = str(head.get("schema_name") or "unknown")
        kind = str(head.get("assertion_kind") or "")
        # Prefer assertion metadata only when it matches the belief schema (winner
        # revisions may also support-link a correction assertion for lineage).
        if (
            head.get("assertion_schema")
            and str(head["assertion_schema"]) == schema_name
            and head.get("assertion_kind")
        ):
            kind = str(head["assertion_kind"])
            schema_name = str(head["assertion_schema"])
        if not kind:
            kind = _infer_kind(schema_name)

        endpoints = _pick_endpoints(args)
        if endpoints is None:
            return MaterializeResult(
                belief_id=belief_id,
                operation=OUTBOX_UPSERT,
                edge_id=None,
                node_ids=(),
                skipped=True,
                reason="insufficient_endpoints",
            )
        from_arg, to_arg, extras = endpoints
        edge_type = edge_type_for(kind=kind, schema_name=schema_name)
        payload = {
            "belief_id": belief_id,
            "belief_revision_id": head["belief_revision_id"],
            "edge_type": edge_type,
            "from": from_arg,
            "to": to_arg,
            "extras": extras,
            "polarity": head.get("polarity"),
        }
        payload_hash = canonical_json(payload)

        with self._db.transaction(immediate=True) as conn:
            revision = self._store.bump_revision_in_txn(conn, user_id=user_id)
            from_node = self._ensure_arg_node(
                conn,
                user_id=user_id,
                arg=from_arg,
                graph_revision=revision,
            )
            to_node = self._ensure_arg_node(
                conn,
                user_id=user_id,
                arg=to_arg,
                graph_revision=revision,
            )
            if from_node is None or to_node is None:
                raise RuntimeError("unresolved_endpoint")
            # Expire other active edges for this belief (shape may have changed).
            self._store.expire_edges_for_belief_in_txn(
                conn,
                user_id=user_id,
                belief_id=belief_id,
                graph_revision=revision,
            )
            edge_id = self._store.upsert_edge_in_txn(
                conn,
                user_id=user_id,
                belief_id=belief_id,
                from_node_id=from_node,
                to_node_id=to_node,
                edge_type=edge_type,
                properties={
                    "polarity": head.get("polarity"),
                    "kind": kind,
                    "schema_name": schema_name,
                    "extras": extras,
                    "belief_revision_id": head["belief_revision_id"],
                },
                payload_hash=payload_hash,
                graph_revision=revision,
            )
            self._mark_summary_dirty_in_txn(conn, user_id=user_id, belief_id=belief_id)
        return MaterializeResult(
            belief_id=belief_id,
            operation=OUTBOX_UPSERT,
            edge_id=edge_id,
            node_ids=(from_node, to_node),
            skipped=False,
        )

    def _ensure_arg_node(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        arg: Mapping[str, Any],
        graph_revision: int,
    ) -> str | None:
        entity_id = arg.get("entity_id")
        if entity_id:
            entity = conn.execute(
                """
                SELECT entity_id, entity_type, identity_key, canonical_label, status
                FROM memory_entities
                WHERE entity_id = ? AND user_id = ?
                """,
                (str(entity_id), user_id),
            ).fetchone()
            if entity is None:
                return None
            entity_type = str(entity["entity_type"])
            node_type = "concept" if entity_type == "concept" else "entity"
            return self._store.upsert_node_in_txn(
                conn,
                user_id=user_id,
                node_type=node_type,
                source_record_id=str(entity["entity_id"]),
                label=str(entity["canonical_label"] or entity["identity_key"]),
                properties={
                    "entity_type": entity_type,
                    "identity_key": str(entity["identity_key"]),
                    "entity_status": str(entity["status"]),
                },
                graph_revision=graph_revision,
            )
        literal = arg.get("literal")
        if literal is None:
            return None
        source_record_id = f"literal:{canonical_json({'literal': literal})}"
        return self._store.upsert_node_in_txn(
            conn,
            user_id=user_id,
            node_type="concept",
            source_record_id=source_record_id,
            label=str(literal),
            properties={"literal": literal},
            graph_revision=graph_revision,
        )

    def _load_head(self, *, user_id: int, belief_id: str) -> dict[str, Any] | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT b.belief_id, b.user_id, b.schema_name, b.proposition_key,
                       r.belief_revision_id, r.belief_status, r.utility_class,
                       r.polarity, r.resolved_arguments_json,
                       (
                           SELECT a.candidate_kind
                           FROM memory_belief_support s
                           JOIN memory_assertions a ON a.assertion_id = s.assertion_id
                           WHERE s.belief_revision_id = r.belief_revision_id
                             AND s.relation = 'supports'
                           ORDER BY a.created_at DESC, a.assertion_id DESC
                           LIMIT 1
                       ) AS assertion_kind,
                       (
                           SELECT a.schema_name
                           FROM memory_belief_support s
                           JOIN memory_assertions a ON a.assertion_id = s.assertion_id
                           WHERE s.belief_revision_id = r.belief_revision_id
                             AND s.relation = 'supports'
                           ORDER BY a.created_at DESC, a.assertion_id DESC
                           LIMIT 1
                       ) AS assertion_schema
                FROM memory_belief_heads h
                JOIN memory_beliefs b ON b.belief_id = h.belief_id
                JOIN memory_belief_revisions r
                  ON r.belief_revision_id = h.belief_revision_id
                WHERE h.belief_id = ? AND h.user_id = ?
                """,
                (belief_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def _mark_summary_dirty_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        belief_id: str,
    ) -> None:
        invalidator = self._summary_invalidator
        if invalidator is None:
            return
        mark = getattr(invalidator, "mark_from_belief_change_in_txn", None)
        if callable(mark):
            mark(conn, user_id=user_id, belief_id=belief_id)
        attach = getattr(self._attachment_invalidator, "mark_from_belief_change_in_txn", None)
        if callable(attach):
            attach(conn, user_id=user_id, belief_id=belief_id)


def _load_args(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def _infer_kind(schema_name: str) -> str:
    name = schema_name.casefold()
    if name.startswith("corrects") or name == "correction":
        return "correction"
    if name.startswith("prefer") or name.startswith("likes"):
        return "preference"
    if name.startswith("has_") or "attribute" in name or "quality" in name:
        return "entity_attribute"
    if "playing" in name or name.startswith("studies") or name.startswith("currently"):
        return "state"
    if name.startswith("had_") or name.startswith("completed") or name.startswith("buys"):
        return "event"
    return "claim"


def _pick_endpoints(
    args: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]] | None:
    usable = [
        dict(item)
        for item in args
        if item.get("entity_id") or item.get("literal") is not None
    ]
    if len(usable) < 2:
        return None
    subject_idx = 0
    for index, item in enumerate(usable):
        role = str(item.get("role") or "").lower()
        if role in SUBJECT_ROLES:
            subject_idx = index
            break
    from_arg = usable[subject_idx]
    to_idx = None
    for index, item in enumerate(usable):
        if index == subject_idx:
            continue
        to_idx = index
        break
    if to_idx is None:
        return None
    to_arg = usable[to_idx]
    extras = [
        item
        for index, item in enumerate(usable)
        if index not in {subject_idx, to_idx}
    ]
    return from_arg, to_arg, extras
