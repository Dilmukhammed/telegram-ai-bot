from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from memory.attachment.context import lexical_overlap
from memory.attachment.schemas import ShortlistCandidate
from memory.attachment.taxonomy import load_taxonomy, match_taxonomy, normalize_label
from memory.ids import make_entity_id
from memory.resolution.schemas import RESOLVER_VERSION
from memory.retrieval.fusion import rrf_fuse
from memory.retrieval.schemas import RetrievalHit


def taxonomy_parent_entity_id(*, user_id: int, parent_key: str) -> str:
    """Deterministic concept entity id for taxonomy parents (e.g. taxonomy:german_cuisine)."""
    return make_entity_id(
        user_id=user_id,
        entity_type="concept",
        identity_key=f"taxonomy:{parent_key}",
        resolver_version=RESOLVER_VERSION,
    )


def retrieve_candidates(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    source_entity_id: str | None,
    source_label: str,
    attach_domains: tuple[str, ...],
    curated_taxonomy_enabled: bool,
    vector_enabled: bool,
    max_raw_hits: int = 48,
) -> tuple[ShortlistCandidate, ...]:
    channel_hits: dict[str, list[RetrievalHit]] = {}
    label_norm = normalize_label(source_label)

    taxonomy_hit = match_taxonomy(
        source_label, enabled=curated_taxonomy_enabled
    )
    if taxonomy_hit is not None:
        parent_id = taxonomy_parent_entity_id(
            user_id=user_id, parent_key=taxonomy_hit.parent
        )
        channel_hits["taxonomy"] = [
            RetrievalHit(
                channel="taxonomy",
                item_id=parent_id,
                item_kind="entity",
                score=1.0,
                label=taxonomy_hit.parent,
                entity_id=parent_id,
                metadata={
                    "op_hint": taxonomy_hit.op,
                    "parent_key": taxonomy_hit.parent,
                    "domain_pack": taxonomy_hit.domain_pack,
                    "curated": True,
                },
            )
        ]

    alias_hits = _alias_channel(conn, user_id=user_id, label=source_label)
    if alias_hits:
        channel_hits["alias"] = alias_hits

    lex_hits = _lexical_channel(
        conn, user_id=user_id, label=source_label, limit=max_raw_hits
    )
    if lex_hits:
        channel_hits["lexical"] = lex_hits

    if source_entity_id:
        graph_hits = _graph_channel(
            conn, user_id=user_id, source_entity_id=source_entity_id
        )
        if graph_hits:
            channel_hits["graph"] = graph_hits
        community_hits = _community_channel(
            conn,
            user_id=user_id,
            source_entity_id=source_entity_id,
            label=source_label,
        )
        if community_hits:
            channel_hits["community"] = community_hits

    if vector_enabled and source_entity_id:
        vector_hits = _vector_channel(
            conn,
            user_id=user_id,
            source_entity_id=source_entity_id,
            limit=max_raw_hits,
        )
        if vector_hits:
            channel_hits["vector"] = vector_hits

    if not channel_hits:
        return ()

    fused = rrf_fuse(channel_hits, limit=max_raw_hits)
    out: list[ShortlistCandidate] = []
    seen: set[str] = set()
    for hit in fused:
        target_id = hit.entity_id or hit.item_id
        if not target_id or target_id == source_entity_id:
            continue
        if target_id in seen:
            continue
        seen.add(target_id)
        meta = dict(hit.metadata)
        out.append(
            ShortlistCandidate(
                target_id=target_id,
                label=hit.label,
                entity_type=str(meta.get("entity_type") or "concept"),
                op_hint=meta.get("op_hint"),
                score=hit.score,
                channel=hit.channel,
                metadata=meta,
            )
        )
    return tuple(out)


def _alias_channel(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    label: str,
    limit: int = 24,
) -> list[RetrievalHit]:
    norm = normalize_label(label)
    rows = conn.execute(
        """
        SELECT a.entity_id, a.alias, e.entity_type, e.canonical_label
        FROM memory_entity_aliases a
        JOIN memory_entities e ON e.entity_id = a.entity_id
        WHERE a.user_id = ? AND a.status = 'active' AND e.status = 'active'
          AND a.normalized_alias LIKE ?
        LIMIT ?
        """,
        (user_id, f"%{norm[:24]}%", limit),
    ).fetchall()
    hits: list[RetrievalHit] = []
    for row in rows:
        hits.append(
            RetrievalHit(
                channel="alias",
                item_id=str(row["entity_id"]),
                item_kind="entity",
                score=0.9,
                label=str(row["canonical_label"] or row["alias"]),
                entity_id=str(row["entity_id"]),
                metadata={"entity_type": str(row["entity_type"])},
            )
        )
    return hits


def _lexical_channel(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    label: str,
    limit: int,
) -> list[RetrievalHit]:
    rows = conn.execute(
        """
        SELECT entity_id, entity_type, canonical_label, identity_key
        FROM memory_entities
        WHERE user_id = ? AND status = 'active'
        LIMIT 200
        """,
        (user_id,),
    ).fetchall()
    scored: list[tuple[float, Any]] = []
    for row in rows:
        text = str(row["canonical_label"] or row["identity_key"])
        score = lexical_overlap(label, text)
        if score > 0.2:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], str(item[1]["entity_id"])))
    hits: list[RetrievalHit] = []
    for score, row in scored[:limit]:
        hits.append(
            RetrievalHit(
                channel="lexical",
                item_id=str(row["entity_id"]),
                item_kind="entity",
                score=score,
                label=str(row["canonical_label"] or row["identity_key"]),
                entity_id=str(row["entity_id"]),
                metadata={"entity_type": str(row["entity_type"])},
            )
        )
    return hits


def _graph_channel(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    source_entity_id: str,
    limit: int = 24,
    max_depth: int = 2,
) -> list[RetrievalHit]:
    source = conn.execute(
        """
        SELECT node_id FROM graph_nodes
        WHERE user_id = ? AND source_record_id = ? AND status = 'active'
        LIMIT 1
        """,
        (user_id, source_entity_id),
    ).fetchone()
    if source is None:
        return []

    # Traverse both directions. Attachment placement needs incoming taxonomy
    # edges just as much as outgoing edges, and group candidates are commonly
    # one additional hop away. Paths are retained as evidence for the LLM and
    # later policy layer instead of reducing graph discovery to a bare score.
    source_node_id = str(source["node_id"])
    frontier: list[tuple[str, tuple[dict[str, Any], ...]]] = [(source_node_id, ())]
    visited = {source_node_id}
    hits: list[RetrievalHit] = []
    for distance in range(1, max(1, max_depth) + 1):
        next_frontier: list[tuple[str, tuple[dict[str, Any], ...]]] = []
        for node_id, path in frontier:
            rows = conn.execute(
                """
                SELECT e.edge_id, e.edge_type, e.from_node_id, e.to_node_id,
                       other.node_id AS other_node_id,
                       other.source_record_id AS entity_id,
                       other.label, other.node_type
                FROM graph_edges e
                JOIN graph_nodes other
                  ON other.node_id = CASE
                       WHEN e.from_node_id = ? THEN e.to_node_id
                       ELSE e.from_node_id
                     END
                WHERE e.user_id = ? AND e.status = 'active'
                  AND (e.from_node_id = ? OR e.to_node_id = ?)
                  AND other.status = 'active'
                ORDER BY e.edge_type, e.edge_id
                """,
                (node_id, user_id, node_id, node_id),
            ).fetchall()
            for row in rows:
                other_node_id = str(row["other_node_id"])
                direction = "outgoing" if str(row["from_node_id"]) == node_id else "incoming"
                step = {
                    "edge_id": str(row["edge_id"]),
                    "edge_type": str(row["edge_type"]),
                    "direction": direction,
                    "from_node_id": str(row["from_node_id"]),
                    "to_node_id": str(row["to_node_id"]),
                }
                candidate_path = (*path, step)
                entity_id = str(row["entity_id"] or "")
                if entity_id and entity_id != source_entity_id:
                    hits.append(
                        RetrievalHit(
                            channel="graph",
                            item_id=entity_id,
                            item_kind="entity",
                            score=max(0.25, 0.9 - (distance - 1) * 0.2),
                            label=str(row["label"] or entity_id),
                            entity_id=entity_id,
                            hop_distance=distance,
                            metadata={
                                "entity_type": str(row["node_type"] or "concept"),
                                "edge_type": str(row["edge_type"]),
                                "graph_distance": distance,
                                "graph_path": list(candidate_path),
                            },
                        )
                    )
                    if len(hits) >= limit:
                        return hits
                if other_node_id not in visited:
                    visited.add(other_node_id)
                    next_frontier.append((other_node_id, candidate_path))
        frontier = next_frontier
        if not frontier:
            break
    return hits


def _community_channel(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    source_entity_id: str,
    label: str,
    limit: int = 8,
) -> list[RetrievalHit]:
    node = conn.execute(
        "SELECT node_id FROM graph_nodes WHERE user_id=? AND source_record_id=? LIMIT 1",
        (user_id, source_entity_id),
    ).fetchone()
    source_node_id = str(node["node_id"]) if node else None
    source_embedding = conn.execute(
        """
        SELECT model_name,embedding_json FROM memory_attachment_embeddings
        WHERE user_id=? AND object_kind='entity' AND object_id=?
        ORDER BY updated_at DESC LIMIT 1
        """,
        (user_id, source_entity_id),
    ).fetchone()
    embedding_model = str(source_embedding["model_name"]) if source_embedding else None
    try:
        source_vector = (
            [float(value) for value in json.loads(str(source_embedding["embedding_json"]))]
            if source_embedding else []
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        source_vector = []
    rows = conn.execute(
        """
        SELECT community_id,community_type,label,member_node_ids_json,graph_revision
        FROM graph_communities
        WHERE user_id=? AND status='active'
        ORDER BY updated_at DESC,community_id
        LIMIT 100
        """,
        (user_id,),
    ).fetchall()
    hits: list[RetrievalHit] = []
    for row in rows:
        try:
            members = json.loads(str(row["member_node_ids_json"] or "[]"))
        except json.JSONDecodeError:
            members = []
        member = bool(source_node_id and source_node_id in members)
        overlap = lexical_overlap(label, str(row["label"] or ""))
        vector_similarity = 0.0
        if source_vector and embedding_model:
            community_embedding = conn.execute(
                """
                SELECT embedding_json FROM memory_attachment_embeddings
                WHERE user_id=? AND object_kind='community' AND object_id=?
                  AND model_name=? LIMIT 1
                """,
                (user_id, str(row["community_id"]), embedding_model),
            ).fetchone()
            if community_embedding is not None:
                try:
                    community_vector = [
                        float(value)
                        for value in json.loads(str(community_embedding["embedding_json"]))
                    ]
                    vector_similarity = _cosine_similarity(source_vector, community_vector)
                except (TypeError, ValueError, json.JSONDecodeError):
                    vector_similarity = 0.0
        if not member and overlap < 0.15 and vector_similarity < 0.55:
            continue
        score = 0.95 if member else max(0.55 + overlap * 0.25, vector_similarity)
        hits.append(
            RetrievalHit(
                channel="community",
                item_id=str(row["community_id"]),
                item_kind="community",
                score=score,
                label=str(row["label"] or row["community_id"]),
                entity_id=str(row["community_id"]),
                metadata={
                    "entity_type": "community",
                    "op_hint": "add_to_group",
                    "community_type": str(row["community_type"]),
                    "membership_evidence": member,
                    "vector_similarity": vector_similarity,
                    "graph_revision": int(row["graph_revision"]),
                },
            )
        )
    hits.sort(key=lambda hit: (-hit.score, hit.item_id))
    return hits[:limit]


def _vector_channel(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    source_entity_id: str,
    limit: int = 24,
    minimum_similarity: float = 0.55,
) -> list[RetrievalHit]:
    source = conn.execute(
        """
        SELECT model_name,embedding_json
        FROM memory_attachment_embeddings
        WHERE user_id=? AND object_kind='entity' AND object_id=?
        ORDER BY updated_at DESC LIMIT 1
        """,
        (user_id, source_entity_id),
    ).fetchone()
    if source is None:
        return []
    try:
        query = [float(value) for value in json.loads(str(source["embedding_json"]))]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not query:
        return []
    rows = conn.execute(
        """
        SELECT emb.object_id,emb.embedding_json,e.entity_type,e.canonical_label
        FROM memory_attachment_embeddings emb
        JOIN memory_entities e ON e.entity_id=emb.object_id AND e.user_id=emb.user_id
        WHERE emb.user_id=? AND emb.object_kind='entity' AND emb.model_name=?
          AND emb.object_id!=? AND e.status='active'
        LIMIT 500
        """,
        (user_id, str(source["model_name"]), source_entity_id),
    ).fetchall()
    scored: list[RetrievalHit] = []
    for row in rows:
        try:
            vector = [float(value) for value in json.loads(str(row["embedding_json"]))]
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        similarity = _cosine_similarity(query, vector)
        if similarity < minimum_similarity:
            continue
        entity_id = str(row["object_id"])
        scored.append(
            RetrievalHit(
                channel="vector",
                item_id=entity_id,
                item_kind="entity",
                score=similarity,
                label=str(row["canonical_label"] or entity_id),
                entity_id=entity_id,
                metadata={
                    "entity_type": str(row["entity_type"]),
                    "vector_similarity": similarity,
                    "embedding_model": str(source["model_name"]),
                },
            )
        )
    scored.sort(key=lambda hit: (-hit.score, hit.item_id))
    return scored[:limit]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def ensure_taxonomy_targets(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    candidates: tuple[ShortlistCandidate, ...],
    now: str,
) -> None:
    """Create concept entities for taxonomy parent targets when missing."""
    for cand in candidates:
        if not cand.metadata or not cand.metadata.get("curated"):
            continue
        parent_key = None
        if cand.metadata:
            parent_key = cand.metadata.get("parent_key")
        if not parent_key and cand.label:
            parent_key = cand.label
        if not parent_key:
            continue
        identity_key = f"taxonomy:{parent_key}"
        existing = conn.execute(
            """
            SELECT entity_id FROM memory_entities
            WHERE user_id = ? AND identity_key = ?
            """,
            (user_id, identity_key),
        ).fetchone()
        if existing is not None:
            continue
        entity_id = taxonomy_parent_entity_id(user_id=user_id, parent_key=str(parent_key))
        conn.execute(
            """
            INSERT OR IGNORE INTO memory_entities(
                entity_id, user_id, entity_type, identity_key,
                canonical_label, status, resolver_version, created_at, updated_at
            ) VALUES (?, ?, 'concept', ?, ?, 'active', ?, ?, ?)
            """,
            (
                entity_id,
                user_id,
                identity_key,
                str(parent_key).replace("_", " ").title(),
                RESOLVER_VERSION,
                now,
                now,
            ),
        )
