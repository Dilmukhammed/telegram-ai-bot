from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING
from memory.db import MemoryDatabase
from memory.summaries.communities.detector import detect_communities
from memory.summaries.dirty import SummaryDirtyStore
from memory.summaries.invalidator import SummaryInvalidator
from memory.summaries.loaders import load_graph_snapshot
from memory.summaries.schemas import SUMMARY_TYPE_COMMUNITY, SummaryConfig
from memory.summaries.store import CommunityStore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def redetect_communities_in_txn(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    communities: CommunityStore,
) -> list[str]:
    nodes, edges, revision = load_graph_snapshot(conn, user_id=user_id)
    detected = detect_communities(nodes=nodes, edges=edges)
    ids: list[str] = []
    for item in detected:
        community_id = communities.upsert_in_txn(
            conn,
            user_id=user_id,
            community_type=item.community_type,
            seed_node_id=item.seed_node_id,
            member_node_ids=item.member_node_ids,
            member_belief_ids=item.member_belief_ids,
            input_hash=item.input_hash,
            graph_revision=revision,
        )
        ids.append(community_id)
    return ids


def redetect_communities(
    db: MemoryDatabase,
    *,
    user_id: int,
    communities: CommunityStore,
    config: SummaryConfig,
) -> list[str]:
    if not config.communities_enabled:
        return []
    with db.transaction(immediate=True) as conn:
        return redetect_communities_in_txn(
            conn, user_id=user_id, communities=communities
        )


def mark_user_full_rebuild(
    db: MemoryDatabase,
    *,
    user_id: int,
    invalidator: SummaryInvalidator,
    communities: CommunityStore,
    config: SummaryConfig,
) -> None:
    with db.transaction(immediate=True) as conn:
        if config.communities_enabled:
            redetect_communities_in_txn(
                conn, user_id=user_id, communities=communities
            )
        invalidator.mark_user_full_in_txn(conn, user_id=user_id, reason="graph_rebuild")


def mark_community_summaries_dirty(
    db: MemoryDatabase,
    *,
    user_id: int,
    community_ids: list[str],
    dirty: SummaryDirtyStore,
    debounce_seconds: float,
) -> None:
    with db.transaction() as conn:
        for community_id in community_ids:
            dirty.mark_in_txn(
                conn,
                user_id=user_id,
                summary_type=SUMMARY_TYPE_COMMUNITY,
                target_id=community_id,
                debounce_seconds=debounce_seconds,
                reason="community_redetect",
            )
