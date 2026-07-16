from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from memory.ids import canonical_json
from memory.summaries.communities.rules import edge_matches_community, seed_score
from memory.summaries.schemas import ALL_COMMUNITY_TYPES, DETECTOR_VERSION


@dataclass(frozen=True, slots=True)
class DetectedCommunity:
    community_type: str
    seed_node_id: str
    member_node_ids: tuple[str, ...]
    member_belief_ids: tuple[str, ...]
    input_hash: str


def detect_communities(
    *,
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    max_hops: int = 3,
) -> list[DetectedCommunity]:
    by_id = {str(n["node_id"]): dict(n) for n in nodes}
    adjacency: dict[str, list[tuple[str, str, str]]] = {}
    for edge in edges:
        from_id = str(edge["from_node_id"])
        to_id = str(edge["to_node_id"])
        edge_type = str(edge["edge_type"])
        belief_id = str(edge["belief_id"])
        adjacency.setdefault(from_id, []).append((to_id, edge_type, belief_id))
        adjacency.setdefault(to_id, []).append((from_id, edge_type, belief_id))

    detected: list[DetectedCommunity] = []
    seen_keys: set[tuple[str, str]] = set()
    for community_type in ALL_COMMUNITY_TYPES:
        seeds = sorted(
            by_id.values(),
            key=lambda n: (-seed_score(n, community_type), str(n["node_id"])),
        )
        for seed in seeds:
            seed_id = str(seed["node_id"])
            key = (community_type, seed_id)
            if key in seen_keys:
                continue
            if seed_score(seed, community_type) < 1:
                continue
            members, beliefs = _bfs(
                seed_id=seed_id,
                community_type=community_type,
                adjacency=adjacency,
                max_hops=max_hops,
            )
            if len(members) < 2:
                continue
            seen_keys.add(key)
            payload = {
                "community_type": community_type,
                "seed_node_id": seed_id,
                "member_node_ids": sorted(members),
                "member_belief_ids": sorted(beliefs),
                "detector_version": DETECTOR_VERSION,
            }
            detected.append(
                DetectedCommunity(
                    community_type=community_type,
                    seed_node_id=seed_id,
                    member_node_ids=tuple(sorted(members)),
                    member_belief_ids=tuple(sorted(beliefs)),
                    input_hash=hashlib.sha256(
                        canonical_json(payload).encode("utf-8")
                    ).hexdigest(),
                )
            )
    return detected


def _bfs(
    *,
    seed_id: str,
    community_type: str,
    adjacency: Mapping[str, Sequence[tuple[str, str, str]]],
    max_hops: int,
) -> tuple[set[str], set[str]]:
    frontier = {seed_id}
    visited = {seed_id}
    beliefs: set[str] = set()
    for _ in range(max_hops):
        nxt: set[str] = set()
        for node_id in frontier:
            for neighbor, edge_type, belief_id in adjacency.get(node_id, ()):
                if not edge_matches_community(edge_type, community_type):
                    continue
                beliefs.add(belief_id)
                if neighbor not in visited:
                    visited.add(neighbor)
                    nxt.add(neighbor)
        if not nxt:
            break
        frontier = nxt
    return visited, beliefs
