from __future__ import annotations

import json
import sqlite3
from collections import deque
from typing import Any

from memory.attachment.context import lexical_overlap
from memory.attachment.taxonomy import normalize_label


ALLOWED_REACT_TOOLS = frozenset(
    {
        "search_entities",
        "get_entity",
        "get_neighbors",
        "search_edges",
        "traverse_graph",
        "search_communities",
        "get_community",
        "attachment_history",
        "find_conflicts",
        "graph_snapshot",
    }
)


class AttachmentReactTools:
    """Bounded read-only graph queries scoped to exactly one user."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        max_results: int,
        max_hops: int,
    ) -> None:
        self._conn = conn
        self._user_id = user_id
        self._max_results = max(1, min(max_results, 20))
        self._max_hops = max(1, min(max_hops, 3))

    def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in ALLOWED_REACT_TOOLS:
            return {"error": "unknown_tool"}
        method = getattr(self, tool)
        try:
            return method(**arguments)
        except (TypeError, ValueError) as exc:
            return {"error": f"invalid_arguments: {exc}"}

    def _limit(self, requested: Any = None) -> int:
        try:
            value = int(requested) if requested is not None else self._max_results
        except (TypeError, ValueError):
            value = self._max_results
        return max(1, min(value, self._max_results))

    def graph_snapshot(self) -> dict[str, Any]:
        revision = self._conn.execute(
            "SELECT current_revision FROM graph_revisions WHERE user_id=?",
            (self._user_id,),
        ).fetchone()
        counts = self._conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM graph_nodes WHERE user_id=? AND status='active') AS nodes,
              (SELECT COUNT(*) FROM graph_edges WHERE user_id=? AND status='active') AS edges,
              (SELECT COUNT(*) FROM graph_communities WHERE user_id=? AND status='active') AS communities
            """,
            (self._user_id, self._user_id, self._user_id),
        ).fetchone()
        return {
            "graph_revision": int(revision["current_revision"]) if revision else 0,
            "active_nodes": int(counts["nodes"]) if counts else 0,
            "active_edges": int(counts["edges"]) if counts else 0,
            "active_communities": int(counts["communities"]) if counts else 0,
        }

    def search_entities(self, *, query: str, limit: int | None = None) -> dict[str, Any]:
        query = str(query).strip()
        if not query:
            return {"query": query, "hits": []}
        rows = self._conn.execute(
            """
            SELECT e.entity_id,e.entity_type,e.canonical_label,e.identity_key,e.status,
                   GROUP_CONCAT(a.alias, ' | ') AS aliases
            FROM memory_entities e
            LEFT JOIN memory_entity_aliases a
              ON a.entity_id=e.entity_id AND a.user_id=e.user_id AND a.status='active'
            WHERE e.user_id=? AND e.status='active'
            GROUP BY e.entity_id
            LIMIT 500
            """,
            (self._user_id,),
        ).fetchall()
        needle = normalize_label(query)
        hits = []
        for row in rows:
            label = str(row["canonical_label"] or row["identity_key"] or row["entity_id"])
            aliases = [item.strip() for item in str(row["aliases"] or "").split("|") if item.strip()]
            exact = needle in {normalize_label(label), *(normalize_label(item) for item in aliases)}
            score = max([lexical_overlap(query, label), *(lexical_overlap(query, item) for item in aliases)])
            if exact:
                score = 1.0
            if score <= 0.2:
                continue
            hits.append(
                {
                    "entity_id": str(row["entity_id"]),
                    "label": label,
                    "entity_type": str(row["entity_type"]),
                    "aliases": aliases[:8],
                    "score": round(score, 6),
                    "channel": "exact_alias" if exact else "lexical",
                }
            )
        hits.sort(key=lambda item: (-float(item["score"]), item["entity_id"]))
        return {"query": query, "hits": hits[: self._limit(limit)]}

    def get_entity(self, *, entity_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT entity_id,entity_type,canonical_label,identity_key,status,resolver_version
            FROM memory_entities WHERE user_id=? AND entity_id=? LIMIT 1
            """,
            (self._user_id, str(entity_id)),
        ).fetchone()
        if row is None:
            return {"entity": None, "error": "unknown_entity"}
        aliases = self._conn.execute(
            """
            SELECT alias,normalized_alias,language,source_mention_id FROM memory_entity_aliases
            WHERE user_id=? AND entity_id=? AND status='active'
            ORDER BY alias LIMIT 12
            """,
            (self._user_id, str(entity_id)),
        ).fetchall()
        return {"entity": {**dict(row), "aliases": [dict(item) for item in aliases]}}

    def _node_for_entity(self, entity_id: str) -> str | None:
        row = self._conn.execute(
            """
            SELECT node_id FROM graph_nodes
            WHERE user_id=? AND source_record_id=? AND status='active'
            LIMIT 1
            """,
            (self._user_id, str(entity_id)),
        ).fetchone()
        return str(row["node_id"]) if row else None

    def get_neighbors(
        self,
        *,
        entity_id: str,
        direction: str = "both",
        edge_types: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        node_id = self._node_for_entity(entity_id)
        if node_id is None:
            return {"entity_id": entity_id, "hits": [], "error": "entity_not_materialized"}
        if direction not in {"incoming", "outgoing", "both"}:
            return {"entity_id": entity_id, "hits": [], "error": "invalid_direction"}
        wanted = {str(item) for item in (edge_types or []) if str(item)}
        rows = self._conn.execute(
            """
            SELECT e.edge_id,e.edge_type,e.from_node_id,e.to_node_id,e.belief_id,
                   n.source_record_id AS other_id,n.label,n.node_type,
                   e.graph_revision,e.properties_json
            FROM graph_edges e
            JOIN graph_nodes n
              ON n.node_id=CASE WHEN e.from_node_id=? THEN e.to_node_id ELSE e.from_node_id END
            WHERE e.user_id=? AND e.status='active' AND n.status='active'
              AND (e.from_node_id=? OR e.to_node_id=?)
            ORDER BY e.edge_type,e.edge_id
            """,
            (node_id, self._user_id, node_id, node_id),
        ).fetchall()
        hits = []
        for row in rows:
            outgoing = str(row["from_node_id"]) == node_id
            edge_direction = "outgoing" if outgoing else "incoming"
            if direction != "both" and edge_direction != direction:
                continue
            if wanted and str(row["edge_type"]) not in wanted:
                continue
            hits.append(
                {
                    "edge_id": str(row["edge_id"]),
                    "edge_type": str(row["edge_type"]),
                    "direction": edge_direction,
                    "entity_id": str(row["other_id"]),
                    "label": str(row["label"] or row["other_id"]),
                    "node_type": str(row["node_type"]),
                    "belief_id": str(row["belief_id"]),
                    "graph_revision": int(row["graph_revision"]),
                    "score": 0.9,
                }
            )
        return {"entity_id": entity_id, "hits": hits[: self._limit(limit)]}

    def search_edges(
        self,
        *,
        edge_types: list[str],
        entity_id: str | None = None,
        direction: str = "both",
        limit: int | None = None,
    ) -> dict[str, Any]:
        if entity_id:
            return self.get_neighbors(
                entity_id=entity_id,
                direction=direction,
                edge_types=edge_types,
                limit=limit,
            )
        wanted = [str(item) for item in edge_types if str(item)]
        if not wanted:
            return {"hits": [], "error": "edge_types_required"}
        placeholders = ",".join("?" for _ in wanted)
        rows = self._conn.execute(
            f"""
            SELECT e.edge_id,e.edge_type,e.belief_id,e.graph_revision,
                   f.source_record_id AS from_id,f.label AS from_label,
                   t.source_record_id AS to_id,t.label AS to_label
            FROM graph_edges e
            JOIN graph_nodes f ON f.node_id=e.from_node_id
            JOIN graph_nodes t ON t.node_id=e.to_node_id
            WHERE e.user_id=? AND e.status='active' AND e.edge_type IN ({placeholders})
            ORDER BY e.edge_type,e.edge_id LIMIT ?
            """,
            (self._user_id, *wanted, self._limit(limit)),
        ).fetchall()
        return {"edge_types": wanted, "hits": [dict(row) for row in rows]}

    def traverse_graph(
        self,
        *,
        entity_id: str,
        edge_types: list[str] | None = None,
        max_hops: int = 2,
        direction: str = "both",
        limit: int | None = None,
    ) -> dict[str, Any]:
        start = self._node_for_entity(entity_id)
        if start is None:
            return {"entity_id": entity_id, "paths": [], "error": "entity_not_materialized"}
        hop_limit = max(1, min(int(max_hops), self._max_hops))
        result_limit = self._limit(limit)
        wanted = {str(item) for item in (edge_types or []) if str(item)}
        queue: deque[tuple[str, list[dict[str, Any]], set[str]]] = deque([(start, [], {start})])
        paths = []
        while queue and len(paths) < result_limit:
            node_id, path, visited = queue.popleft()
            if len(path) >= hop_limit:
                continue
            rows = self._conn.execute(
                """
                SELECT e.edge_id,e.edge_type,e.from_node_id,e.to_node_id,e.belief_id,
                       n.node_id AS other_node_id,n.source_record_id,n.label,n.node_type,e.graph_revision
                FROM graph_edges e
                JOIN graph_nodes n
                  ON n.node_id=CASE WHEN e.from_node_id=? THEN e.to_node_id ELSE e.from_node_id END
                WHERE e.user_id=? AND e.status='active' AND n.status='active'
                  AND (e.from_node_id=? OR e.to_node_id=?)
                ORDER BY e.edge_type,e.edge_id
                """,
                (node_id, self._user_id, node_id, node_id),
            ).fetchall()
            for row in rows:
                outgoing = str(row["from_node_id"]) == node_id
                step_direction = "outgoing" if outgoing else "incoming"
                if direction != "both" and direction != step_direction:
                    continue
                if wanted and str(row["edge_type"]) not in wanted:
                    continue
                other_node = str(row["other_node_id"])
                if other_node in visited:
                    continue
                step = {
                    "edge_id": str(row["edge_id"]),
                    "edge_type": str(row["edge_type"]),
                    "direction": step_direction,
                    "belief_id": str(row["belief_id"]),
                }
                next_path = [*path, step]
                paths.append(
                    {
                        "target_id": str(row["source_record_id"]),
                        "target_label": str(row["label"] or row["source_record_id"]),
                        "target_type": str(row["node_type"]),
                        "hops": len(next_path),
                        "score": round(max(0.25, 0.9 - 0.2 * (len(next_path) - 1)), 6),
                        "graph_revision": int(row["graph_revision"]),
                        "path": next_path,
                    }
                )
                queue.append((other_node, next_path, visited | {other_node}))
                if len(paths) >= result_limit:
                    break
        return {"entity_id": entity_id, "paths": paths}

    def search_communities(self, *, query: str, limit: int | None = None) -> dict[str, Any]:
        rows = self._conn.execute(
            """
            SELECT community_id,community_type,label,member_node_ids_json,graph_revision
            FROM graph_communities WHERE user_id=? AND status='active'
            ORDER BY updated_at DESC LIMIT 200
            """,
            (self._user_id,),
        ).fetchall()
        hits = []
        for row in rows:
            score = lexical_overlap(query, str(row["label"] or ""))
            if score <= 0.15:
                continue
            members = _loads_list(row["member_node_ids_json"])
            hits.append(
                {
                    "community_id": str(row["community_id"]),
                    "label": str(row["label"] or row["community_id"]),
                    "community_type": str(row["community_type"]),
                    "member_count": len(members),
                    "graph_revision": int(row["graph_revision"]),
                    "score": round(score, 6),
                }
            )
        hits.sort(key=lambda item: (-float(item["score"]), item["community_id"]))
        return {"query": query, "hits": hits[: self._limit(limit)]}

    def get_community(self, *, community_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT community_id,community_type,label,member_node_ids_json,graph_revision
            FROM graph_communities WHERE user_id=? AND community_id=? AND status='active'
            LIMIT 1
            """,
            (self._user_id, str(community_id)),
        ).fetchone()
        if row is None:
            return {"community": None, "error": "unknown_community"}
        node_ids = _loads_list(row["member_node_ids_json"])[: self._max_results]
        members = []
        for node_id in node_ids:
            node = self._conn.execute(
                """
                SELECT source_record_id,label,node_type FROM graph_nodes
                WHERE user_id=? AND node_id=? AND status='active'
                """,
                (self._user_id, node_id),
            ).fetchone()
            if node:
                members.append(dict(node))
        return {
            "community": {
                "community_id": str(row["community_id"]),
                "label": str(row["label"] or row["community_id"]),
                "community_type": str(row["community_type"]),
                "graph_revision": int(row["graph_revision"]),
                "members": members,
            }
        }

    def attachment_history(self, *, entity_id: str, limit: int | None = None) -> dict[str, Any]:
        rows = self._conn.execute(
            """
            SELECT event_id,op,source_entity_id,target_entity_id,status,utility_class,
                   tier,source_belief_id,graph_revision,created_at
            FROM memory_attachment_events
            WHERE user_id=? AND (source_entity_id=? OR target_entity_id=?)
            ORDER BY created_at DESC LIMIT ?
            """,
            (self._user_id, str(entity_id), str(entity_id), self._limit(limit)),
        ).fetchall()
        return {"entity_id": entity_id, "events": [dict(row) for row in rows]}

    def find_conflicts(self, *, entity_id: str, limit: int | None = None) -> dict[str, Any]:
        negatives = self._conn.execute(
            """
            SELECT negative_id,source_entity_id,op,target_entity_id,reason,layer,status,expires_at
            FROM memory_attachment_negatives
            WHERE user_id=? AND status='active'
              AND (source_entity_id=? OR target_entity_id=?)
            ORDER BY created_at DESC LIMIT ?
            """,
            (self._user_id, str(entity_id), str(entity_id), self._limit(limit)),
        ).fetchall()
        constraints = self._conn.execute(
            """
            SELECT constraint_id,target_entity_id,scope,reason_json,status,source_belief_id
            FROM memory_attachment_constraints
            WHERE user_id=? AND target_entity_id=? AND status='active'
            ORDER BY created_at DESC LIMIT ?
            """,
            (self._user_id, str(entity_id), self._limit(limit)),
        ).fetchall()
        return {
            "entity_id": entity_id,
            "negative_pairs": [dict(row) for row in negatives],
            "constraints": [dict(row) for row in constraints],
        }


def _loads_list(raw: Any) -> list[str]:
    try:
        value = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []
