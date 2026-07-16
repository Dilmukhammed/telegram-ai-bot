from __future__ import annotations

import sqlite3
from typing import Any

from memory.summaries.dirty import SummaryDirtyStore
from memory.summaries.eligibility import default_targets_for_user
from memory.summaries.loaders import load_belief_snapshots
from memory.summaries.schemas import (
    SUMMARY_TYPE_COMMUNITY,
    SUMMARY_TYPE_CORE_PROFILE,
    SUMMARY_TYPE_ENTITY,
    SUMMARY_TYPE_TIMELINE_ENTITY,
    SUMMARY_TYPE_TIMELINE_USER,
    SUMMARY_TYPE_ACTIVE_STATE,
    SummaryConfig,
    user_target_id,
)
from memory.summaries.store import CommunityStore


class SummaryInvalidator:
    def __init__(
        self,
        *,
        dirty: SummaryDirtyStore,
        communities: CommunityStore,
        config: SummaryConfig,
    ) -> None:
        self._dirty = dirty
        self._communities = communities
        self._config = config

    @property
    def enabled(self) -> bool:
        return self._config.summaries_enabled

    def mark_from_belief_change_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        belief_id: str,
    ) -> None:
        if not self.enabled:
            return
        snapshots = load_belief_snapshots(conn, user_id=user_id)
        belief = next((b for b in snapshots if b.belief_id == belief_id), None)
        debounce = self._config.debounce_seconds
        uid = user_target_id(user_id)
        self._dirty.mark_in_txn(
            conn,
            user_id=user_id,
            summary_type=SUMMARY_TYPE_CORE_PROFILE,
            target_id=uid,
            debounce_seconds=debounce,
            reason=f"belief:{belief_id}",
        )
        self._dirty.mark_in_txn(
            conn,
            user_id=user_id,
            summary_type=SUMMARY_TYPE_ACTIVE_STATE,
            target_id=uid,
            debounce_seconds=debounce,
            reason=f"belief:{belief_id}",
        )
        self._dirty.mark_in_txn(
            conn,
            user_id=user_id,
            summary_type=SUMMARY_TYPE_TIMELINE_USER,
            target_id=uid,
            debounce_seconds=debounce,
            reason=f"belief:{belief_id}",
        )
        if belief is not None:
            for entity_id in belief.entity_ids:
                self._dirty.mark_in_txn(
                    conn,
                    user_id=user_id,
                    summary_type=SUMMARY_TYPE_ENTITY,
                    target_id=entity_id,
                    debounce_seconds=debounce,
                    reason=f"belief:{belief_id}",
                )
                self._dirty.mark_in_txn(
                    conn,
                    user_id=user_id,
                    summary_type=SUMMARY_TYPE_TIMELINE_ENTITY,
                    target_id=entity_id,
                    debounce_seconds=debounce,
                    reason=f"belief:{belief_id}",
                )
        for community in self._communities.list_active(user_id=user_id):
            members = frozenset(str(b) for b in community["member_belief_ids"])
            if belief_id in members:
                self._dirty.mark_in_txn(
                    conn,
                    user_id=user_id,
                    summary_type=SUMMARY_TYPE_COMMUNITY,
                    target_id=str(community["community_id"]),
                    debounce_seconds=debounce,
                    reason=f"belief:{belief_id}",
                )
        self._bump_ops_in_txn(conn, user_id=user_id)

    def mark_entity_merge_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        winner_entity_id: str,
        loser_entity_id: str,
    ) -> None:
        if not self.enabled:
            return
        debounce = self._config.debounce_seconds
        for entity_id in (winner_entity_id, loser_entity_id):
            self._dirty.mark_in_txn(
                conn,
                user_id=user_id,
                summary_type=SUMMARY_TYPE_ENTITY,
                target_id=entity_id,
                debounce_seconds=debounce,
                reason="entity_merge",
            )
            self._dirty.mark_in_txn(
                conn,
                user_id=user_id,
                summary_type=SUMMARY_TYPE_TIMELINE_ENTITY,
                target_id=entity_id,
                debounce_seconds=debounce,
                reason="entity_merge",
            )
        self._bump_ops_in_txn(conn, user_id=user_id)

    def mark_user_full_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        reason: str = "full_rebuild",
    ) -> None:
        if not self.enabled:
            return
        communities = self._communities.list_active(user_id=user_id)
        entity_ids: set[str] = set()
        snapshots = load_belief_snapshots(conn, user_id=user_id)
        for snap in snapshots:
            entity_ids.update(snap.entity_ids)
        community_ids = tuple(str(c["community_id"]) for c in communities)
        debounce = 0.0
        for summary_type, target_id in default_targets_for_user(
            user_id=user_id,
            entity_ids=tuple(sorted(entity_ids)),
            community_ids=community_ids,
        ):
            self._dirty.mark_in_txn(
                conn,
                user_id=user_id,
                summary_type=summary_type,
                target_id=target_id,
                debounce_seconds=debounce,
                reason=reason,
            )
        conn.execute(
            """
            INSERT INTO graph_summary_user_state(
                user_id, incremental_ops_since_full, last_full_rebuild_at
            ) VALUES (?, 0, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                incremental_ops_since_full = 0,
                last_full_rebuild_at = datetime('now')
            """,
            (user_id,),
        )

    def _bump_ops_in_txn(self, conn: sqlite3.Connection, *, user_id: int) -> None:
        conn.execute(
            """
            INSERT INTO graph_summary_user_state(user_id, incremental_ops_since_full)
            VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                incremental_ops_since_full = incremental_ops_since_full + 1
            """,
            (user_id,),
        )
        row = conn.execute(
            """
            SELECT incremental_ops_since_full
            FROM graph_summary_user_state
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            return
        ops = int(row["incremental_ops_since_full"])
        if ops >= self._config.full_rebuild_every_n:
            self.mark_user_full_in_txn(conn, user_id=user_id, reason="ops_threshold")
