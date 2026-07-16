from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Mapping, Sequence

from memory.retrieval.corpus import BeliefHeadDoc, EntityDoc
from memory.retrieval.schemas import CHANNEL_GRAPH, ChannelResult, RetrievalHit


def search_graph(
    *,
    query: str,
    plan_entities: Sequence[str],
    entities: Sequence[EntityDoc],
    beliefs: Sequence[BeliefHeadDoc],
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    max_hops: int = 3,
    limit: int = 40,
) -> ChannelResult:
    started = time.perf_counter()
    if not edges or not nodes:
        return ChannelResult(
            channel=CHANNEL_GRAPH,
            hits=(),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            skipped=False,
        )

    node_by_id = {str(node["node_id"]): node for node in nodes}
    belief_by_id = {item.belief_id: item for item in beliefs}

    seed_node_ids = _seed_nodes(
        plan_entities=plan_entities,
        query=query,
        nodes=nodes,
        entities=entities,
    )
    if not seed_node_ids:
        # No entity seed: score edges by lexical overlap with edge_type / labels.
        return _lexical_edge_hits(
            query=query,
            edges=edges,
            node_by_id=node_by_id,
            belief_by_id=belief_by_id,
            started=started,
            limit=limit,
        )

    adjacency: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for edge in edges:
        adjacency[str(edge["from_node_id"])].append(edge)
        adjacency[str(edge["to_node_id"])].append(edge)

    visited_beliefs: dict[str, tuple[int, Mapping[str, Any], list[str]]] = {}
    queue: deque[tuple[str, int, list[str]]] = deque(
        (node_id, 0, [node_id]) for node_id in seed_node_ids
    )
    seen_nodes = set(seed_node_ids)

    while queue:
        node_id, dist, path = queue.popleft()
        if dist >= max_hops:
            continue
        for edge in adjacency.get(node_id, []):
            belief_id = str(edge["belief_id"])
            other = (
                str(edge["to_node_id"])
                if str(edge["from_node_id"]) == node_id
                else str(edge["from_node_id"])
            )
            next_dist = dist + 1
            next_path = path + [str(edge["edge_id"]), other]
            prior = visited_beliefs.get(belief_id)
            if prior is None or next_dist < prior[0]:
                visited_beliefs[belief_id] = (next_dist, edge, next_path)
            if other not in seen_nodes and next_dist < max_hops:
                seen_nodes.add(other)
                queue.append((other, next_dist, next_path))

    hits: list[RetrievalHit] = []
    for belief_id, (hop, edge, path) in visited_beliefs.items():
        belief = belief_by_id.get(belief_id)
        from_node = node_by_id.get(str(edge["from_node_id"]), {})
        to_node = node_by_id.get(str(edge["to_node_id"]), {})
        label = str(edge.get("edge_type") or "edge")
        statement = (
            belief.statement
            if belief is not None
            else f"{from_node.get('label')} -[{label}]-> {to_node.get('label')}"
        )
        score = 1.0 / (1.0 + hop)
        hits.append(
            RetrievalHit(
                channel=CHANNEL_GRAPH,
                item_id=belief_id,
                item_kind="belief",
                score=score,
                label=label,
                statement=statement,
                belief_id=belief_id,
                status=belief.belief_status if belief else "active",
                utility_class=belief.utility_class if belief else "durable",
                polarity=belief.polarity if belief else None,
                hop_distance=hop,
                support_pointers=belief.support_pointers if belief else (),
                metadata={
                    "path": path,
                    "from_label": from_node.get("label"),
                    "to_label": to_node.get("label"),
                    "edge_type": label,
                },
            )
        )
    hits.sort(key=lambda item: (-item.score, item.item_id))
    return ChannelResult(
        channel=CHANNEL_GRAPH,
        hits=tuple(hits[:limit]),
        latency_ms=(time.perf_counter() - started) * 1000.0,
    )


def _seed_nodes(
    *,
    plan_entities: Sequence[str],
    query: str,
    nodes: Sequence[Mapping[str, Any]],
    entities: Sequence[EntityDoc],
) -> list[str]:
    surfaces = [item.casefold() for item in plan_entities if item]
    query_cf = query.casefold()
    entity_labels = {
        item.entity_id: item.canonical_label.casefold() for item in entities
    }
    seeds: list[str] = []
    for node in nodes:
        label = str(node.get("label") or "").casefold()
        source = str(node.get("source_record_id") or "")
        if label and (label in surfaces or any(s in label for s in surfaces)):
            seeds.append(str(node["node_id"]))
            continue
        if source in entity_labels and (
            entity_labels[source] in surfaces or entity_labels[source] in query_cf
        ):
            seeds.append(str(node["node_id"]))
    return list(dict.fromkeys(seeds))


def _lexical_edge_hits(
    *,
    query: str,
    edges: Sequence[Mapping[str, Any]],
    node_by_id: Mapping[str, Mapping[str, Any]],
    belief_by_id: Mapping[str, BeliefHeadDoc],
    started: float,
    limit: int,
) -> ChannelResult:
    q = query.casefold()
    hits: list[RetrievalHit] = []
    for edge in edges:
        belief_id = str(edge["belief_id"])
        belief = belief_by_id.get(belief_id)
        from_node = node_by_id.get(str(edge["from_node_id"]), {})
        to_node = node_by_id.get(str(edge["to_node_id"]), {})
        blob = " ".join(
            [
                str(edge.get("edge_type") or ""),
                str(from_node.get("label") or ""),
                str(to_node.get("label") or ""),
                belief.statement if belief else "",
            ]
        ).casefold()
        if not q or not any(token and token in blob for token in q.split() if len(token) > 2):
            continue
        hits.append(
            RetrievalHit(
                channel=CHANNEL_GRAPH,
                item_id=belief_id,
                item_kind="belief",
                score=0.4,
                label=str(edge.get("edge_type") or "edge"),
                statement=belief.statement if belief else blob,
                belief_id=belief_id,
                status=belief.belief_status if belief else "active",
                utility_class=belief.utility_class if belief else "durable",
                polarity=belief.polarity if belief else None,
                hop_distance=1,
                support_pointers=belief.support_pointers if belief else (),
            )
        )
    hits.sort(key=lambda item: (-item.score, item.item_id))
    return ChannelResult(
        channel=CHANNEL_GRAPH,
        hits=tuple(hits[:limit]),
        latency_ms=(time.perf_counter() - started) * 1000.0,
    )
