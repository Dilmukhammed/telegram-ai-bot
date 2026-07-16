from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from memory.service import MemoryService


def explain_belief(
    service: "MemoryService",
    *,
    user_id: int,
    belief_id: str,
) -> dict[str, Any]:
    """Walk belief → assertions → candidate → evidence → source pointer."""
    with service.db.connection() as conn:
        head = conn.execute(
            """
            SELECT b.belief_id, b.user_id, b.proposition_key, b.schema_name,
                   r.belief_revision_id, r.belief_status, r.utility_class,
                   r.polarity, r.resolved_arguments_json, r.utility_reason_codes_json
            FROM memory_belief_heads h
            JOIN memory_beliefs b ON b.belief_id = h.belief_id
            JOIN memory_belief_revisions r
              ON r.belief_revision_id = h.belief_revision_id
            WHERE h.belief_id = ? AND h.user_id = ?
            """,
            (belief_id, user_id),
        ).fetchone()
        if head is None:
            raise KeyError(f"belief not found: {belief_id}")

        support = conn.execute(
            """
            SELECT a.*
            FROM memory_belief_support s
            JOIN memory_assertions a ON a.assertion_id = s.assertion_id
            WHERE s.belief_revision_id = ?
            ORDER BY a.created_at, a.assertion_id
            """,
            (head["belief_revision_id"],),
        ).fetchall()

        edges = conn.execute(
            """
            SELECT edge_id, from_node_id, to_node_id, edge_type, status, payload_hash
            FROM graph_edges
            WHERE user_id = ? AND belief_id = ?
            ORDER BY created_at, edge_id
            """,
            (user_id, belief_id),
        ).fetchall()

        evidence_layers: list[dict[str, Any]] = []
        for assertion in support:
            candidate_id = str(assertion["candidate_id"])
            candidate = conn.execute(
                """
                SELECT candidate_id, candidate_kind, schema_name, status, polarity,
                       extraction_run_id
                FROM memory_claim_candidates
                WHERE candidate_id = ? AND user_id = ?
                """,
                (candidate_id, user_id),
            ).fetchone()
            score = conn.execute(
                """
                SELECT score_id, route_status, policy_version, status
                FROM memory_candidate_scores
                WHERE candidate_id = ? AND user_id = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (candidate_id, user_id),
            ).fetchone()
            evidence_rows = conn.execute(
                """
                SELECT segment_id, evidence_relation, exact_quote, pointer_json
                FROM memory_candidate_evidence
                WHERE candidate_id = ?
                ORDER BY segment_id
                """,
                (candidate_id,),
            ).fetchall()
            quotes: list[dict[str, Any]] = []
            for ev in evidence_rows:
                pointer = json.loads(str(ev["pointer_json"]))
                segment = conn.execute(
                    """
                    SELECT segment_id, text, source_version_id, pointer_json
                    FROM memory_segments
                    WHERE segment_id = ?
                    """,
                    (ev["segment_id"],),
                ).fetchone()
                source_text = None
                source_ref = None
                if segment is not None:
                    source_text = segment["text"]
                    version = conn.execute(
                        """
                        SELECT v.source_version_id, v.pointer_json, s.source_ref, s.source_type
                        FROM memory_source_versions v
                        JOIN memory_sources s ON s.source_id = v.source_id
                        WHERE v.source_version_id = ? AND s.user_id = ?
                        """,
                        (segment["source_version_id"], user_id),
                    ).fetchone()
                    if version is not None:
                        source_ref = {
                            "source_type": version["source_type"],
                            "source_ref": version["source_ref"],
                            "pointer": json.loads(str(version["pointer_json"])),
                        }
                quotes.append(
                    {
                        "exact_quote": ev["exact_quote"],
                        "relation": ev["evidence_relation"],
                        "evidence_pointer": pointer,
                        "segment_text": source_text,
                        "source": source_ref,
                    }
                )
            evidence_layers.append(
                {
                    "assertion_id": str(assertion["assertion_id"]),
                    "assertion_status": str(assertion["status"]),
                    "candidate": dict(candidate) if candidate else None,
                    "score": dict(score) if score else None,
                    "evidence": quotes,
                }
            )

    human_lines = [
        f"Belief {belief_id}",
        f"status={head['belief_status']} utility={head['utility_class']} "
        f"polarity={head['polarity']} schema={head['schema_name']}",
    ]
    for edge in edges:
        human_lines.append(
            f"graph edge {edge['edge_type']} "
            f"{edge['from_node_id']} -> {edge['to_node_id']} ({edge['status']})"
        )
    for layer in evidence_layers:
        for quote in layer["evidence"]:
            if quote.get("exact_quote"):
                human_lines.append(f"quote: {quote['exact_quote']}")
            elif quote.get("segment_text"):
                human_lines.append(f"segment: {quote['segment_text']}")

    return {
        "belief_id": belief_id,
        "user_id": user_id,
        "belief": {
            "proposition_key": head["proposition_key"],
            "schema_name": head["schema_name"],
            "belief_status": head["belief_status"],
            "utility_class": head["utility_class"],
            "polarity": head["polarity"],
            "belief_revision_id": head["belief_revision_id"],
            "resolved_arguments": json.loads(str(head["resolved_arguments_json"] or "[]")),
            "utility_reason_codes": json.loads(
                str(head["utility_reason_codes_json"] or "[]")
            ),
        },
        "graph_edges": [dict(row) for row in edges],
        "support": evidence_layers,
        "human_summary": "\n".join(human_lines),
    }
