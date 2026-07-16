from __future__ import annotations

import sqlite3

from memory.attachment.dirty import AttachmentDirtyStore
from memory.attachment.schemas import AttachmentConfig


class AttachmentInvalidator:
    def __init__(self, *, dirty: AttachmentDirtyStore, config: AttachmentConfig) -> None:
        self._dirty = dirty
        self._config = config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def mark_from_belief_change_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        belief_id: str,
    ) -> None:
        if not self.enabled:
            return
        # Attachments are derived state. Any revision/status change of their
        # source belief invalidates the old derivation immediately; the dirty
        # job may later produce a new event from the new head. This closes the
        # append-only hole where an inferred edge survived its evidence.
        conn.execute(
            """
            UPDATE memory_attachment_events
            SET status = 'reverted'
            WHERE user_id = ? AND source_belief_id = ?
              AND status IN ('active', 'possible')
            """,
            (user_id, belief_id),
        )
        # Also invalidate events that were inferred through graph edges backed
        # by this belief. This covers multi-hop attachments whose source belief
        # is different but whose provenance path has become stale.
        conn.execute(
            """
            UPDATE memory_attachment_events
            SET status='reverted'
            WHERE user_id=? AND status IN ('active','possible')
              AND event_id IN (
                SELECT d.event_id
                FROM memory_attachment_dependencies d
                WHERE d.user_id=? AND d.status='active'
                  AND (
                    (d.dependency_type='belief' AND d.dependency_id=?)
                    OR (
                      d.dependency_type='graph_edge'
                      AND d.dependency_id IN (
                        SELECT edge_id FROM graph_edges
                        WHERE user_id=? AND belief_id=?
                      )
                    )
                  )
              )
            """,
            (user_id, user_id, belief_id, user_id, belief_id),
        )
        conn.execute(
            """
            UPDATE memory_attachment_dependencies
            SET status='invalidated'
            WHERE user_id=? AND status='active'
              AND (
                (dependency_type='belief' AND dependency_id=?)
                OR (
                  dependency_type='graph_edge'
                  AND dependency_id IN (
                    SELECT edge_id FROM graph_edges
                    WHERE user_id=? AND belief_id=?
                  )
                )
              )
            """,
            (user_id, belief_id, user_id, belief_id),
        )
        self._dirty.mark_in_txn(
            conn,
            user_id=user_id,
            belief_id=belief_id,
            debounce_seconds=self._config.debounce_seconds,
            reason=f"belief:{belief_id}",
        )
