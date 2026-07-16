from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from memory.db import MemoryDatabase, dumps_json, utc_now_iso
from memory.ids import make_community_id, make_summary_id
from memory.summaries.schemas import (
    DETECTOR_VERSION,
    STATUS_ACTIVE,
    STATUS_REJECTED,
    STATUS_SUPERSEDED,
    SUMMARY_PROMPT_VERSION,
    SummaryDraft,
)


@dataclass(frozen=True, slots=True)
class SummaryRecord:
    summary_id: str
    user_id: int
    summary_type: str
    target_id: str
    content: str
    sentences: tuple[str, ...]
    belief_ids: tuple[str, ...]
    sentence_support: Mapping[str, tuple[str, ...]]
    status: str
    graph_revision: int


class SummaryStore:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    def get_active(
        self,
        *,
        user_id: int,
        summary_type: str,
        target_id: str,
    ) -> SummaryRecord | None:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM graph_summaries
                WHERE user_id = ? AND summary_type = ? AND target_id = ?
                  AND status = ?
                ORDER BY updated_at DESC, summary_id DESC
                LIMIT 1
                """,
                (user_id, summary_type, target_id, STATUS_ACTIVE),
            ).fetchone()
        return _row_to_record(row) if row else None

    def insert_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        summary_type: str,
        target_id: str,
        draft: SummaryDraft,
        input_hash: str,
        status: str,
        graph_revision: int,
        model_profile: str | None,
        prompt_version: str = SUMMARY_PROMPT_VERSION,
    ) -> str:
        summary_id = make_summary_id(
            user_id=user_id,
            summary_type=summary_type,
            target_id=target_id,
            input_hash=input_hash,
            prompt_version=prompt_version,
        )
        now = utc_now_iso()
        conn.execute(
            """
            INSERT OR IGNORE INTO graph_summaries(
                summary_id, user_id, summary_type, target_id, content,
                sentences_json, belief_ids_json, sentence_support_json,
                input_hash, model_profile, prompt_version, status,
                graph_revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary_id,
                user_id,
                summary_type,
                target_id,
                draft.content,
                dumps_json([s.text for s in draft.sentences]),
                dumps_json(list(draft.belief_ids)),
                dumps_json(
                    {str(k): list(v) for k, v in draft.sentence_support.items()}
                ),
                input_hash,
                model_profile,
                prompt_version,
                status,
                graph_revision,
                now,
                now,
            ),
        )
        return summary_id

    def supersede_active_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        summary_type: str,
        target_id: str,
    ) -> int:
        now = utc_now_iso()
        updated = conn.execute(
            """
            UPDATE graph_summaries
            SET status = ?, updated_at = ?
            WHERE user_id = ? AND summary_type = ? AND target_id = ?
              AND status = ?
            """,
            (
                STATUS_SUPERSEDED,
                now,
                user_id,
                summary_type,
                target_id,
                STATUS_ACTIVE,
            ),
        )
        return int(updated.rowcount)

    def count_by_status(self, *, user_id: int | None = None) -> dict[str, int]:
        with self._db.connection() as conn:
            if user_id is None:
                rows = conn.execute(
                    """
                    SELECT status, COUNT(*) AS c
                    FROM graph_summaries
                    GROUP BY status
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT status, COUNT(*) AS c
                    FROM graph_summaries
                    WHERE user_id = ?
                    GROUP BY status
                    """,
                    (user_id,),
                ).fetchall()
        return {str(row["status"]): int(row["c"]) for row in rows}

    def list_active_for_user(
        self,
        *,
        user_id: int,
        summary_types: tuple[str, ...] | None = None,
        limit: int = 100,
    ) -> list[SummaryRecord]:
        with self._db.connection() as conn:
            if summary_types:
                placeholders = ",".join("?" for _ in summary_types)
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM graph_summaries
                    WHERE user_id = ? AND status = ?
                      AND summary_type IN ({placeholders})
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (user_id, STATUS_ACTIVE, *summary_types, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM graph_summaries
                    WHERE user_id = ? AND status = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (user_id, STATUS_ACTIVE, limit),
                ).fetchall()
        return [_row_to_record(row) for row in rows if row]


class CommunityStore:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    def upsert_in_txn(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        community_type: str,
        seed_node_id: str,
        member_node_ids: tuple[str, ...],
        member_belief_ids: tuple[str, ...],
        input_hash: str,
        graph_revision: int,
        label: str | None = None,
        detector_version: str = DETECTOR_VERSION,
    ) -> str:
        community_id = make_community_id(
            user_id=user_id,
            community_type=community_type,
            seed_node_id=seed_node_id,
            detector_version=detector_version,
            input_hash=input_hash,
        )
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO graph_communities(
                community_id, user_id, community_type, label,
                member_node_ids_json, member_belief_ids_json, seed_node_id,
                input_hash, detector_version, graph_revision, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(user_id, community_type, seed_node_id, detector_version)
            DO UPDATE SET
                label = excluded.label,
                member_node_ids_json = excluded.member_node_ids_json,
                member_belief_ids_json = excluded.member_belief_ids_json,
                input_hash = excluded.input_hash,
                graph_revision = excluded.graph_revision,
                status = 'active',
                updated_at = excluded.updated_at
            """,
            (
                community_id,
                user_id,
                community_type,
                label,
                dumps_json(list(member_node_ids)),
                dumps_json(list(member_belief_ids)),
                seed_node_id,
                input_hash,
                detector_version,
                graph_revision,
                now,
                now,
            ),
        )
        row = conn.execute(
            """
            SELECT community_id
            FROM graph_communities
            WHERE user_id = ? AND community_type = ? AND seed_node_id = ?
              AND detector_version = ?
            """,
            (user_id, community_type, seed_node_id, detector_version),
        ).fetchone()
        return str(row["community_id"]) if row is not None else community_id

    def list_active(
        self,
        *,
        user_id: int,
    ) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT community_id, community_type, label, member_node_ids_json,
                       member_belief_ids_json, seed_node_id, graph_revision
                FROM graph_communities
                WHERE user_id = ? AND status = 'active'
                ORDER BY community_type, community_id
                """,
                (user_id,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "community_id": str(row["community_id"]),
                    "community_type": str(row["community_type"]),
                    "label": row["label"],
                    "member_node_ids": json.loads(row["member_node_ids_json"] or "[]"),
                    "member_belief_ids": json.loads(
                        row["member_belief_ids_json"] or "[]"
                    ),
                    "seed_node_id": str(row["seed_node_id"]),
                    "graph_revision": int(row["graph_revision"]),
                }
            )
        return out

    def count_active(self, *, user_id: int | None = None) -> int:
        with self._db.connection() as conn:
            if user_id is None:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM graph_communities WHERE status = 'active'"
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM graph_communities
                    WHERE user_id = ? AND status = 'active'
                    """,
                    (user_id,),
                ).fetchone()
        return int(row["c"])


def _row_to_record(row: sqlite3.Row) -> SummaryRecord:
    support_raw = json.loads(row["sentence_support_json"] or "{}")
    support = {
        str(k): tuple(str(x) for x in v)
        for k, v in support_raw.items()
        if isinstance(v, list)
    }
    sentences = tuple(str(s) for s in json.loads(row["sentences_json"] or "[]"))
    belief_ids = tuple(str(b) for b in json.loads(row["belief_ids_json"] or "[]"))
    return SummaryRecord(
        summary_id=str(row["summary_id"]),
        user_id=int(row["user_id"]),
        summary_type=str(row["summary_type"]),
        target_id=str(row["target_id"]),
        content=str(row["content"]),
        sentences=sentences,
        belief_ids=belief_ids,
        sentence_support=support,
        status=str(row["status"]),
        graph_revision=int(row["graph_revision"]),
    )
