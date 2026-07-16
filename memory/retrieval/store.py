from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping, Sequence

from memory.db import MemoryDatabase, dumps_json, utc_now_iso
from memory.ids import content_hash_from_text
from memory.retrieval.schemas import (
    ChannelResult,
    MemoryContextPack,
    QueryPlan,
    ShadowRetrievalResult,
)


def make_shadow_run_id(*, user_id: int, query: str, query_time: str) -> str:
    digest = content_hash_from_text(f"{user_id}|{query_time}|{query}")[:24]
    return f"shadow_{digest}"


def persist_shadow_run(
    db: MemoryDatabase,
    *,
    result: ShadowRetrievalResult,
    query: str,
    error: str | None = None,
    summary_pack_json: Mapping[str, Any] | None = None,
) -> None:
    query_hash = content_hash_from_text(query)
    now = utc_now_iso()
    channels_payload = [
        {
            "channel": item.channel,
            "latency_ms": item.latency_ms,
            "hit_count": len(item.hits),
            "skipped": item.skipped,
            "skip_reason": item.skip_reason,
            "error": item.error,
            "hit_ids": [hit.item_id for hit in item.hits[:30]],
        }
        for item in result.channels
    ]
    belief_ids = [
        str(item.get("belief_id"))
        for item in result.pack.beliefs
        if item.get("belief_id")
    ]
    with db.transaction(immediate=True) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_shadow_retrieval_runs(
                run_id, user_id, query_hash, query_time, graph_revision,
                memory_needed, plan_json, channels_json, pack_json,
                latency_ms_json, pack_token_estimate, belief_ids_json,
                summary_pack_json, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.run_id,
                result.user_id,
                query_hash,
                result.pack.query_time,
                result.pack.graph_revision,
                1 if result.plan.memory_needed else 0,
                dumps_json(result.plan.to_mapping()),
                dumps_json(channels_payload),
                dumps_json(result.pack.to_mapping()),
                dumps_json(dict(result.latency_ms)),
                int(result.pack.token_estimate),
                dumps_json(belief_ids),
                dumps_json(dict(summary_pack_json)) if summary_pack_json else None,
                error,
                now,
            ),
        )


def load_recent_shadow_runs(
    db: MemoryDatabase,
    *,
    user_id: int,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT run_id, query_hash, query_time, graph_revision, memory_needed,
                   pack_token_estimate, belief_ids_json, error, created_at,
                   latency_ms_json
            FROM memory_shadow_retrieval_runs
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "run_id": str(row["run_id"]),
                "query_hash": str(row["query_hash"]),
                "query_time": str(row["query_time"]),
                "graph_revision": int(row["graph_revision"]),
                "memory_needed": bool(row["memory_needed"]),
                "pack_token_estimate": int(row["pack_token_estimate"]),
                "belief_ids": json.loads(row["belief_ids_json"] or "[]"),
                "error": row["error"],
                "created_at": str(row["created_at"]),
                "latency_ms": json.loads(row["latency_ms_json"] or "{}"),
            }
        )
    return out
