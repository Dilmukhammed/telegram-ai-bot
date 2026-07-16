from __future__ import annotations

import unittest

from memory.db import MemoryDatabase
from memory.summaries.communities.detector import detect_communities
from memory.summaries.communities.rules import edge_matches_community
from memory.summaries.store import CommunityStore


class CommunityDetectorTests(unittest.TestCase):
    def test_community_upsert_is_idempotent_when_membership_changes(self) -> None:
        db = MemoryDatabase(":memory:")
        store = CommunityStore(db)
        with db.transaction() as conn:
            first_id = store.upsert_in_txn(
                conn,
                user_id=1,
                community_type="food",
                seed_node_id="n_self",
                member_node_ids=("n_self", "n_japanese"),
                member_belief_ids=("b_old",),
                input_hash="old-hash",
                graph_revision=1,
            )
            second_id = store.upsert_in_txn(
                conn,
                user_id=1,
                community_type="food",
                seed_node_id="n_self",
                member_node_ids=("n_self", "n_italian"),
                member_belief_ids=("b_new",),
                input_hash="new-hash",
                graph_revision=2,
            )
            count = conn.execute(
                "SELECT COUNT(*) FROM graph_communities WHERE user_id = 1"
            ).fetchone()[0]
            row = conn.execute(
                "SELECT input_hash, graph_revision FROM graph_communities WHERE community_id = ?",
                (first_id,),
            ).fetchone()

        self.assertEqual(second_id, first_id)
        self.assertEqual(count, 1)
        self.assertEqual(row["input_hash"], "new-hash")
        self.assertEqual(row["graph_revision"], 2)

    def test_family_bfs_from_synthetic_edges(self) -> None:
        nodes = [
            {
                "node_id": "n_self",
                "node_type": "entity",
                "source_record_id": "e_self",
                "label": "self",
                "properties": {"entity_type": "person"},
            },
            {
                "node_id": "n_mom",
                "node_type": "entity",
                "source_record_id": "e_mom",
                "label": "mom",
                "properties": {"entity_type": "person"},
            },
        ]
        edges = [
            {
                "from_node_id": "n_self",
                "to_node_id": "n_mom",
                "edge_type": "relation:family",
                "belief_id": "b_family",
            }
        ]
        self.assertTrue(edge_matches_community("relation:family", "family"))
        detected = detect_communities(nodes=nodes, edges=edges)
        family = [item for item in detected if item.community_type == "family"]
        self.assertTrue(family)
        self.assertIn("n_self", family[0].member_node_ids)
        self.assertIn("n_mom", family[0].member_node_ids)
        self.assertIn("b_family", family[0].member_belief_ids)

    def test_work_requires_work_edge_hint(self) -> None:
        nodes = [
            {
                "node_id": "n1",
                "node_type": "entity",
                "source_record_id": "e1",
                "label": "Acme",
                "properties": {"entity_type": "organization"},
            },
            {
                "node_id": "n2",
                "node_type": "entity",
                "source_record_id": "e2",
                "label": "Alice",
                "properties": {"entity_type": "person"},
            },
        ]
        edges = [
            {
                "from_node_id": "n2",
                "to_node_id": "n1",
                "edge_type": "entity_attribute:works_at",
                "belief_id": "b_work",
            }
        ]
        detected = detect_communities(nodes=nodes, edges=edges)
        work = [item for item in detected if item.community_type == "work"]
        self.assertTrue(work)
        self.assertGreaterEqual(len(work[0].member_node_ids), 2)
