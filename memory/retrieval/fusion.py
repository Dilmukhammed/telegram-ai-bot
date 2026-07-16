from __future__ import annotations

from collections.abc import Mapping, Sequence

from memory.retrieval.schemas import RetrievalHit

RRF_K = 60


def rrf_fuse(
    channel_hits: Mapping[str, Sequence[RetrievalHit]],
    *,
    limit: int,
    channel_weights: Mapping[str, float] | None = None,
) -> list[RetrievalHit]:
    """Deterministic reciprocal-rank fusion across retrieval channels."""
    weights = dict(channel_weights or {})
    scores: dict[tuple[str, str], float] = {}
    best: dict[tuple[str, str], RetrievalHit] = {}

    for channel, hits in channel_hits.items():
        weight = float(weights.get(channel, 1.0))
        for rank, hit in enumerate(hits, start=1):
            key = (hit.item_kind, hit.item_id)
            scores[key] = scores.get(key, 0.0) + weight * (1.0 / (RRF_K + rank))
            prior = best.get(key)
            if prior is None or hit.score > prior.score:
                best[key] = hit

    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1], item[0][0], item[0][1]),
    )
    out: list[RetrievalHit] = []
    for key, fused in ranked[: max(0, limit)]:
        hit = best[key]
        out.append(
            RetrievalHit(
                channel=hit.channel,
                item_id=hit.item_id,
                item_kind=hit.item_kind,
                score=fused,
                label=hit.label,
                statement=hit.statement,
                belief_id=hit.belief_id,
                entity_id=hit.entity_id,
                status=hit.status,
                utility_class=hit.utility_class,
                polarity=hit.polarity,
                hop_distance=hit.hop_distance,
                support_pointers=hit.support_pointers,
                metadata={**dict(hit.metadata), "fused_from": hit.channel},
            )
        )
    return out
