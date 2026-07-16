from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Mapping, Sequence

from memory.db import parse_utc
from memory.retrieval.corpus import BeliefHeadDoc
from memory.retrieval.schemas import CHANNEL_TEMPORAL, ChannelResult, RetrievalHit


def search_temporal(
    *,
    query_time: datetime,
    beliefs: Sequence[BeliefHeadDoc],
    edges: Sequence[Mapping[str, Any]] = (),
    limit: int = 40,
) -> ChannelResult:
    """Filter beliefs/edges that carry temporal validity relative to query_time."""
    started = time.perf_counter()
    hits: list[RetrievalHit] = []
    edge_by_belief = {
        str(edge["belief_id"]): edge
        for edge in edges
        if edge.get("belief_id")
    }

    for doc in beliefs:
        edge = edge_by_belief.get(doc.belief_id)
        valid_from = _parse_maybe(edge.get("valid_from") if edge else None)
        valid_to = _parse_maybe(edge.get("valid_to") if edge else None)
        temporal = dict(doc.temporal or {})
        cue = str(temporal.get("normalized") or temporal.get("cue") or "")
        if not valid_from and not valid_to and not cue and doc.belief_status != "historical":
            continue

        in_window = True
        if valid_from and query_time < valid_from:
            in_window = False
        if valid_to and query_time > valid_to:
            in_window = False

        score = 0.0
        if doc.belief_status == "historical":
            score = 0.55
        if cue:
            score = max(score, 0.7)
        if in_window and (valid_from or valid_to):
            score = max(score, 0.9)
        if score <= 0:
            continue
        hits.append(
            RetrievalHit(
                channel=CHANNEL_TEMPORAL,
                item_id=doc.belief_id,
                item_kind="belief",
                score=score,
                label=doc.schema_name,
                statement=doc.statement,
                belief_id=doc.belief_id,
                status=doc.belief_status,
                utility_class=doc.utility_class,
                polarity=doc.polarity,
                support_pointers=doc.support_pointers,
                metadata={
                    "valid_from": valid_from.isoformat() if valid_from else None,
                    "valid_to": valid_to.isoformat() if valid_to else None,
                    "temporal_cue": cue or None,
                    "in_window": in_window,
                },
            )
        )
    hits.sort(key=lambda item: (-item.score, item.item_id))
    return ChannelResult(
        channel=CHANNEL_TEMPORAL,
        hits=tuple(hits[:limit]),
        latency_ms=(time.perf_counter() - started) * 1000.0,
    )


def _parse_maybe(raw: Any) -> datetime | None:
    if not raw:
        return None
    return parse_utc(str(raw))
