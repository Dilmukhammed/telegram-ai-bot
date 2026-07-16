from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from memory.db import MemoryDatabase
from memory.graph.materializer import GraphMaterializer
from memory.graph.outbox import enqueue_outbox_in_txn
from memory.graph.schemas import OUTBOX_UPSERT, is_materializable
from memory.graph.store import MemoryGraphStore

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True)
class GraphRebuildResult:
    user_id: int
    beliefs_seen: int
    edges_active: int
    revision: int


def list_eligible_belief_ids(
    db: MemoryDatabase,
    *,
    user_id: int,
) -> list[str]:
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT h.belief_id, r.belief_status, r.utility_class
            FROM memory_belief_heads h
            JOIN memory_belief_revisions r
              ON r.belief_revision_id = h.belief_revision_id
            WHERE h.user_id = ?
            ORDER BY h.belief_id
            """,
            (user_id,),
        ).fetchall()
    return [
        str(row["belief_id"])
        for row in rows
        if is_materializable(
            belief_status=str(row["belief_status"]),
            utility_class=str(row["utility_class"]),
        )
    ]


def rebuild_user_graph(
    db: MemoryDatabase,
    *,
    user_id: int,
    store: MemoryGraphStore | None = None,
    summary_invalidator: object | None = None,
) -> GraphRebuildResult:
    graph_store = store or MemoryGraphStore(db)
    materializer = GraphMaterializer(
        db,
        store=graph_store,
        summary_invalidator=summary_invalidator,
    )
    with db.transaction(immediate=True) as conn:
        graph_store.wipe_user_projection_in_txn(conn, user_id=user_id)
    belief_ids = list_eligible_belief_ids(db, user_id=user_id)
    for belief_id in belief_ids:
        materializer.materialize_belief(user_id=user_id, belief_id=belief_id)
    if summary_invalidator is not None:
        mark = getattr(summary_invalidator, "mark_user_full_in_txn", None)
        if callable(mark):
            with db.transaction(immediate=True) as conn:
                mark(conn, user_id=user_id, reason="graph_rebuild")
    edges = graph_store.list_active_edges(user_id=user_id)
    return GraphRebuildResult(
        user_id=user_id,
        beliefs_seen=len(belief_ids),
        edges_active=len(edges),
        revision=graph_store.current_revision(user_id),
    )


def enqueue_belief_recompute_outbox_in_txn(
    conn,
    *,
    user_id: int,
    belief_id: str,
    belief_status: str,
    utility_class: str,
    revision_id: str,
) -> str:
    operation = (
        OUTBOX_UPSERT
        if is_materializable(
            belief_status=belief_status, utility_class=utility_class
        )
        else "remove"
    )
    return enqueue_outbox_in_txn(
        conn,
        user_id=user_id,
        belief_id=belief_id,
        operation=operation,
        payload_hash=revision_id,
    )
