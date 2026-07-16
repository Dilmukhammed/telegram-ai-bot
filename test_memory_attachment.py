from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from memory.attachment.critics import (
    accept_from_layers,
    run_adversarial_critic,
    run_alt_hypothesis_critic,
    run_hypothesis_layer,
    run_set_critic,
    accepted_hypotheses_from_critics,
    run_support_critic,
)
from memory.attachment.constraints import (
    apply_negative_preference_constraint_in_txn,
    blocks_inferred_preference,
    release_negative_preference_constraints_in_txn,
)
from memory.attachment.dirty import AttachmentDirtyStore
from memory.attachment.events_store import AttachmentEventsStore
from memory.attachment.firewall import apply_firewall
from memory.attachment.hypotheses import (
    AttachmentParseError,
    parse_hypotheses,
    select_compatible_hypotheses,
    filter_policy_compatible_hypotheses,
    seed_hypotheses_from_shortlist,
)
from memory.attachment.jobs import ATTACH_ANALYZE_STAGE, attach_job_request
from memory.attachment.materializer import AttachmentMaterializer
from memory.attachment.invalidator import AttachmentInvalidator
from memory.attachment.negative import is_negative_blocked
from memory.attachment.pipeline import analyze_attachment
from memory.attachment.policy import decide_utility_class, insert_negative
from memory.attachment.retrieve import retrieve_candidates, taxonomy_parent_entity_id
from memory.attachment.scheduler import AttachmentDirtyScheduler
from memory.attachment.schemas import (
    ATTACHMENT_SCHEMA_VERSION,
    AttachmentConfig,
    AttachmentHypothesis,
    LayerVerdict,
    ShortlistCandidate,
)
from memory.attachment.trigger import run_trigger_gate
from memory.config import MemoryConfig, validate_memory_config
from memory.db import MemoryDatabase, utc_now_iso
from memory.ids import make_belief_id, make_entity_id
from memory.graph.store import MemoryGraphStore
from memory.resolution.schemas import RESOLVER_VERSION
from memory.schema import SCHEMA_VERSION, ensure_schema
from memory.service import MemoryService, reset_memory_service


class FakeAttachmentModel:
    def __init__(self, responses: list[str], *, profile: str = "fake") -> None:
        self._responses = list(responses)
        self.model_profile = profile

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = None,
    ) -> str:
        if not self._responses:
            raise RuntimeError("no fake responses left")
        return self._responses.pop(0)


def _attach_config(**overrides: Any) -> AttachmentConfig:
    base = {
        "enabled": True,
        "generation_enabled": True,
        "verify_enabled": True,
        "two_generator_enabled": False,
        "vector_enabled": False,
        "curated_taxonomy_enabled": True,
        "inferred_preference_enabled": True,
        "write_graph_edges": False,
        "write_possible_events": False,
        "scan_interval_seconds": 1.0,
        "scan_batch_size": 10,
        "debounce_seconds": 0.0,
        "max_candidates": 12,
        "max_llm_calls": 6,
        "model_profile": "extraction",
        "support_model_profile": "extraction",
        "adversarial_model_profile": "agent",
        "cluster_model_profile": "agent",
        "max_tokens": 1536,
    }
    base.update(overrides)
    return AttachmentConfig(**base)


def _memory_config(db_path: str, **overrides: Any) -> MemoryConfig:
    base = MemoryConfig(
        ingest_enabled=False,
        db_path=db_path,
        worker_enabled=True,
        worker_concurrency=1,
        worker_poll_seconds=0.05,
        job_lease_seconds=30,
        job_max_attempts=2,
        job_retry_base_seconds=0.01,
        job_retry_max_seconds=0.05,
        job_claim_batch_size=5,
        resolution_enabled=True,
        verification_enabled=True,
        graph_enabled=True,
        attachment_enabled=True,
        attachment_generation_enabled=True,
    )
    data = {**base.__dict__, **overrides}
    return MemoryConfig(**data)


def _seed_belief_head(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    belief_id: str,
    schema_name: str,
    entity_id: str,
    label: str,
    entity_type: str = "product",
    polarity: str = "positive",
) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT OR IGNORE INTO memory_entities(
            entity_id, user_id, entity_type, identity_key,
            canonical_label, status, resolver_version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (
            entity_id,
            user_id,
            entity_type,
            f"label:{label.lower()}",
            label,
            RESOLVER_VERSION,
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO memory_beliefs(
            belief_id, user_id, proposition_key, cluster_key, schema_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (belief_id, user_id, f"likes:{label}", f"cluster:{label}", schema_name, now),
    )
    rev_id = f"{belief_id}:rev1"
    args = json.dumps(
        [
            {
                "role": "object",
                "value_kind": "entity",
                "entity_id": entity_id,
                "label": label,
                "entity_type": entity_type,
            }
        ]
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO memory_belief_revisions(
            belief_revision_id, user_id, belief_id, input_set_hash,
            resolved_arguments_json, resolved_value_json, polarity, temporal_json,
            belief_status, utility_class, utility_reason_codes_json,
            confidence_components_json, reconciliation_policy_version,
            utility_policy_version, supersedes_revision_id, created_at
        ) VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, 'active', 'durable', '[]', '{}', 'v1', 'v1', NULL, ?)
        """,
        (rev_id, user_id, belief_id, "hash1", args, polarity, now),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO memory_belief_heads(
            belief_id, user_id, belief_revision_id, updated_at
        ) VALUES (?, ?, ?, ?)
        """,
        (belief_id, user_id, rev_id, now),
    )


class AttachmentEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_memory_service()
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "memory.sqlite")
        self.db = MemoryDatabase(self.db_path)
        with self.db.connection() as conn:
            ensure_schema(conn)

    def tearDown(self) -> None:
        reset_memory_service()
        self._tmp.cleanup()

    def test_schema_v13(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 13)
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT MAX(version) AS v FROM memory_schema_migrations"
            ).fetchone()
            self.assertEqual(int(row["v"]), 13)
            conn.execute("SELECT 1 FROM memory_attachment_events LIMIT 1")
            conn.execute("SELECT 1 FROM memory_attachment_negatives LIMIT 1")
            conn.execute("SELECT 1 FROM memory_attachment_dirty LIMIT 1")
            conn.execute("SELECT 1 FROM memory_attachment_dependencies LIMIT 1")
            conn.execute("SELECT 1 FROM memory_attachment_constraints LIMIT 1")

    def test_attachment_v2_live_eval_pack_is_well_formed_and_nontrivial(self) -> None:
        pack = json.loads(
            Path("data/memory_corpus/attachment_v2_live_eval.json").read_text(encoding="utf-8")
        )
        self.assertEqual(pack["schema_version"], "1")
        self.assertGreaterEqual(len(pack["cases"]), 10)
        case_ids = [case["case_id"] for case in pack["cases"]]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertTrue(any(len(case["required"]) > 1 for case in pack["cases"]))
        self.assertTrue(all(case["shortlist"] for case in pack["cases"]))

    def test_l0_accepts_likes_food_schema(self) -> None:
        result = run_trigger_gate(
            schema_name="likes_food",
            entity_type="concept",
            mention_type=None,
            label="Kartoffelsalat",
            belief_status="active",
            utility_class="durable",
            curated_taxonomy_enabled=True,
            candidate_kind="preference",
        )
        self.assertTrue(result.should_run)
        self.assertIn("food", result.attach_domains)

    def test_subject_prefers_value_over_self(self) -> None:
        from memory.attachment.trigger import subject_from_belief_head

        entity_id, label, entity_type = subject_from_belief_head(
            {
                "schema_name": "likes_food",
                "resolved_arguments_json": json.dumps(
                    [
                        {
                            "role": "subject",
                            "value_kind": "entity",
                            "entity_id": "ment_self",
                            "entity_type": "user",
                            "label": "self",
                        },
                        {
                            "role": "value",
                            "value_kind": "entity",
                            "entity_id": "ment_food",
                            "entity_type": "concept",
                            "label": "Kartoffelsalat",
                        },
                    ]
                ),
            }
        )
        self.assertEqual(entity_id, "ment_food")
        self.assertEqual(label, "Kartoffelsalat")
        self.assertEqual(entity_type, "concept")

    def test_l0_skips_person(self) -> None:
        result = run_trigger_gate(
            schema_name="preference",
            entity_type="person",
            mention_type="person",
            label="Ivan",
            belief_status="active",
            utility_class="durable",
            curated_taxonomy_enabled=True,
        )
        self.assertFalse(result.should_run)
        self.assertEqual(result.skip_reason, "person_skipped")

    def test_l3_firewall_drops_cross_type(self) -> None:
        shortlist = (
            ShortlistCandidate(
                target_id="p1",
                label="Ivan",
                entity_type="person",
                score=0.9,
            ),
        )

        def _never(**_kwargs: Any) -> bool:
            return False

        kept = apply_firewall(
            shortlist,
            user_id=1,
            source_entity_id="d1",
            source_entity_type="product",
            attach_domains=("food",),
            existing_attachments=(),
            negatives_check=_never,
            max_candidates=12,
        )
        self.assertEqual(kept, ())

    def test_curated_kartoffelsalat_german_cuisine(self) -> None:
        user_id = 1
        entity_id = make_entity_id(
            user_id=user_id,
            entity_type="product",
            identity_key="label:kartoffelsalat",
            resolver_version=RESOLVER_VERSION,
        )
        belief_id = make_belief_id(user_id=user_id, proposition_key="likes:kartoffelsalat")
        with self.db.transaction() as conn:
            _seed_belief_head(
                conn,
                user_id=user_id,
                belief_id=belief_id,
                schema_name="preference",
                entity_id=entity_id,
                label="Kartoffelsalat",
            )
            cfg = _attach_config()
            support = FakeAttachmentModel(
                [
                    json.dumps(
                        {
                            "schema_version": ATTACHMENT_SCHEMA_VERSION,
                            "verdict": "supported",
                        }
                    )
                ]
            )
            result = asyncio.run(
                analyze_attachment(
                    conn,
                    user_id=user_id,
                    belief_id=belief_id,
                    config=cfg,
                    support_model=support,
                    commit=True,
                    events_store=AttachmentEventsStore(self.db),
                )
            )
        self.assertTrue(result.accepted)
        self.assertIsNotNone(result.hypothesis)
        assert result.hypothesis is not None
        self.assertEqual(result.hypothesis.op, "cuisine_of")
        parent_id = taxonomy_parent_entity_id(
            user_id=user_id, parent_key="german_cuisine"
        )
        self.assertEqual(result.hypothesis.target_id, parent_id)
        self.assertEqual(result.utility_class, "deferred")
        with self.db.connection() as conn:
            dependencies = conn.execute(
                """
                SELECT dependency_type,dependency_id
                FROM memory_attachment_dependencies
                ORDER BY dependency_type,dependency_id
                """
            ).fetchall()
        self.assertIn(("belief", belief_id), [tuple(row) for row in dependencies])

    def test_empty_shortlist_abstain_no_llm(self) -> None:
        calls = {"n": 0}

        class CountingModel(FakeAttachmentModel):
            async def generate(self, *args: Any, **kwargs: Any) -> str:
                calls["n"] += 1
                return await super().generate(*args, **kwargs)

        user_id = 1
        entity_id = make_entity_id(
            user_id=user_id,
            entity_type="topic",
            identity_key="label:obscure_topic_xyz",
            resolver_version=RESOLVER_VERSION,
        )
        belief_id = make_belief_id(user_id=user_id, proposition_key="likes:obscure")
        with self.db.connection() as conn:
            _seed_belief_head(
                conn,
                user_id=user_id,
                belief_id=belief_id,
                schema_name="topic",
                entity_id=entity_id,
                label="obscure_topic_xyz",
                entity_type="topic",
            )
            cfg = _attach_config(curated_taxonomy_enabled=False)
            result = asyncio.run(
                analyze_attachment(
                    conn,
                    user_id=user_id,
                    belief_id=belief_id,
                    config=cfg,
                    hypothesis_model=CountingModel([]),
                    commit=False,
                )
            )
        self.assertFalse(result.accepted)
        self.assertEqual(result.abstain_reason, "empty_shortlist")
        self.assertEqual(calls["n"], 0)

    def test_l7_prefers_other_target_abstain(self) -> None:
        winner = AttachmentHypothesis(op="cuisine_of", target_id="t1")
        shortlist = (
            ShortlistCandidate(target_id="t1", label="A", entity_type="concept"),
            ShortlistCandidate(target_id="t2", label="B", entity_type="concept"),
        )
        alt = FakeAttachmentModel(
            [
                json.dumps(
                    {
                        "schema_version": ATTACHMENT_SCHEMA_VERSION,
                        "preferred": True,
                        "op": "cuisine_of",
                        "target_id": "t2",
                    }
                )
            ]
        )
        layer, _calls = asyncio.run(
            run_alt_hypothesis_critic(
                alt,
                hypothesis=winner,
                shortlist=shortlist,
                context_statement="likes sushi",
            )
        )
        accepted, reason = accept_from_layers(
            winner=winner,
            layers=(
                LayerVerdict("L5", "supported"),
                LayerVerdict("L6", "supported"),
                layer,
            ),
        )
        self.assertFalse(accepted)
        self.assertEqual(reason, "alt_hypothesis_preferred")

    def test_parser_rejects_unknown_target(self) -> None:
        raw = json.dumps(
            {
                "schema_version": ATTACHMENT_SCHEMA_VERSION,
                "hypotheses": [{"op": "cuisine_of", "target_id": "not_in_list"}],
            }
        )
        with self.assertRaises(AttachmentParseError):
            parse_hypotheses(raw, shortlist_ids=["allowed"])

    def test_multi_hypothesis_selection_keeps_compatible_graph_and_group_links(self) -> None:
        parsed = parse_hypotheses(
            {
                "schema_version": ATTACHMENT_SCHEMA_VERSION,
                "hypotheses": [
                    {
                        "op": "cuisine_of",
                        "target_id": "japanese_cuisine",
                        "confidence": 0.97,
                        "reason_codes": ["taxonomy_path"],
                    },
                    {
                        "op": "add_to_group",
                        "target_id": "food_preferences",
                        "confidence": 0.91,
                        "reason_codes": ["community_fit"],
                    },
                ],
            },
            shortlist_ids=["japanese_cuisine", "food_preferences"],
        )
        selected = select_compatible_hypotheses(parsed, max_items=3)
        self.assertEqual(
            [(item.op, item.target_id) for item in selected],
            [
                ("cuisine_of", "japanese_cuisine"),
                ("add_to_group", "food_preferences"),
            ],
        )
        self.assertEqual(selected[0].reason_codes, ("taxonomy_path",))

    def test_multi_hypothesis_selection_rejects_competing_targets_for_same_relation(self) -> None:
        selected = select_compatible_hypotheses(
            (
                AttachmentHypothesis("cuisine_of", "japanese", confidence=0.92),
                AttachmentHypothesis("cuisine_of", "korean", confidence=0.89),
                AttachmentHypothesis("add_to_group", "food", confidence=0.80),
            ),
            max_items=3,
        )
        self.assertEqual(
            [(item.op, item.target_id) for item in selected],
            [("cuisine_of", "japanese"), ("add_to_group", "food")],
        )

    def test_policy_gate_enforces_candidate_op_hint_and_domain(self) -> None:
        shortlist = (
            ShortlistCandidate(
                target_id="japanese", label="Japanese cuisine",
                entity_type="concept", op_hint="cuisine_of",
            ),
        )
        kept = filter_policy_compatible_hypotheses(
            (
                AttachmentHypothesis("inferred_preference", "japanese", confidence=0.99),
                AttachmentHypothesis("cuisine_of", "japanese", confidence=0.95),
                AttachmentHypothesis("located_in", "japanese", confidence=0.90),
            ),
            shortlist=shortlist,
            attach_domains=("food",),
        )
        self.assertEqual([(item.op, item.target_id) for item in kept], [("cuisine_of", "japanese")])

    def test_deterministic_seeds_keep_active_strong_evidence_but_not_historical_or_person(self) -> None:
        seeded = seed_hypotheses_from_shortlist(
            (
                ShortlistCandidate(
                    "postgres", "PostgreSQL", "software", op_hint="part_of", score=0.96,
                    channel="graph", metadata={"graph_distance": 1, "edge_status": "active"},
                ),
                ShortlistCandidate(
                    "sqlite", "SQLite", "software", op_hint="part_of", score=0.95,
                    channel="graph", metadata={"graph_distance": 1, "edge_status": "historical"},
                ),
                ShortlistCandidate(
                    "dima", "Dima", "person", op_hint="same_as", score=0.99,
                    channel="alias", metadata={"exact_alias": True},
                ),
            )
        )
        self.assertEqual([(item.op, item.target_id) for item in seeded], [("part_of", "postgres")])

    def test_negative_pair_suppresses_retry(self) -> None:
        user_id = 1
        source = "ent_src"
        target = "ent_tgt"
        with self.db.transaction() as conn:
            insert_negative(
                conn,
                user_id=user_id,
                source_entity_id=source,
                op="cuisine_of",
                target_entity_id=target,
                reason="adversarial",
                layer="L6",
            )
            blocked = is_negative_blocked(
                conn,
                user_id=user_id,
                source_entity_id=source,
                op="cuisine_of",
                target_entity_id=target,
            )
        self.assertTrue(blocked)

    def test_graph_retrieval_searches_incoming_and_two_hop_neighbors(self) -> None:
        user_id = 1
        source = "entity_japanese_cuisine"
        dish = "entity_sushi"
        group = "entity_food_preferences"
        with self.db.transaction() as conn:
            now = utc_now_iso()
            for entity_id, label in (
                (source, "Japanese cuisine"),
                (dish, "Sushi"),
                (group, "Food preferences"),
            ):
                conn.execute(
                    """
                    INSERT INTO memory_entities(
                        entity_id,user_id,entity_type,identity_key,canonical_label,
                        status,resolver_version,created_at,updated_at
                    ) VALUES (?,?,'concept',?,?,'active',?,?,?)
                    """,
                    (entity_id, user_id, f"test:{entity_id}", label, RESOLVER_VERSION, now, now),
                )
            store = MemoryGraphStore(self.db)
            revision = store.bump_revision_in_txn(conn, user_id=user_id)
            node_ids = {
                entity_id: store.upsert_node_in_txn(
                    conn,
                    user_id=user_id,
                    node_type="concept",
                    source_record_id=entity_id,
                    label=label,
                    properties={},
                    graph_revision=revision,
                )
                for entity_id, label in (
                    (source, "Japanese cuisine"),
                    (dish, "Sushi"),
                    (group, "Food preferences"),
                )
            }
            for belief_id in ("belief_taxonomy", "belief_group"):
                conn.execute(
                    "INSERT INTO memory_beliefs VALUES (?,?,?,?,'test',?)",
                    (belief_id, user_id, belief_id, belief_id, now),
                )
            # Incoming first hop: Sushi -> Japanese cuisine.
            store.upsert_edge_in_txn(
                conn, user_id=user_id, belief_id="belief_taxonomy",
                from_node_id=node_ids[dish], to_node_id=node_ids[source],
                edge_type="attach:cuisine_of", properties={}, payload_hash="p1",
                graph_revision=revision,
            )
            # Second hop: Sushi -> Food preferences.
            store.upsert_edge_in_txn(
                conn, user_id=user_id, belief_id="belief_group",
                from_node_id=node_ids[dish], to_node_id=node_ids[group],
                edge_type="member_of", properties={}, payload_hash="p2",
                graph_revision=revision,
            )

            candidates = retrieve_candidates(
                conn,
                user_id=user_id,
                source_entity_id=source,
                source_label="Japanese cuisine",
                attach_domains=("food",),
                curated_taxonomy_enabled=False,
                vector_enabled=False,
            )

        by_id = {candidate.target_id: candidate for candidate in candidates}
        self.assertIn(dish, by_id)
        self.assertIn(group, by_id)
        self.assertEqual(by_id[dish].metadata["graph_distance"], 1)
        self.assertEqual(by_id[group].metadata["graph_distance"], 2)
        self.assertTrue(by_id[group].metadata["graph_path"])

    def test_retrieval_considers_existing_semantic_communities(self) -> None:
        user_id = 1
        source = "entity_ramen"
        with self.db.transaction() as conn:
            now = utc_now_iso()
            conn.execute(
                """
                INSERT INTO memory_entities(
                    entity_id,user_id,entity_type,identity_key,canonical_label,status,
                    resolver_version,created_at,updated_at
                ) VALUES (?,?,'concept','literal:string:ramen','Ramen','active',?,?,?)
                """,
                (source, user_id, RESOLVER_VERSION, now, now),
            )
            store = MemoryGraphStore(self.db)
            revision = store.bump_revision_in_txn(conn, user_id=user_id)
            source_node = store.upsert_node_in_txn(
                conn, user_id=user_id, node_type="concept", source_record_id=source,
                label="Ramen", properties={}, graph_revision=revision,
            )
            conn.execute(
                """
                INSERT INTO graph_communities(
                    community_id,user_id,community_type,label,member_node_ids_json,
                    member_belief_ids_json,seed_node_id,input_hash,detector_version,
                    graph_revision,status,created_at,updated_at
                ) VALUES ('community_food',?,'semantic','Food preferences',?,'[]',
                          ?,'community-input','test-v1',?,'active',?,?)
                """,
                (user_id, json.dumps([source_node]), source_node, revision, now, now),
            )
            candidates = retrieve_candidates(
                conn, user_id=user_id, source_entity_id=source, source_label="Ramen",
                attach_domains=("food",), curated_taxonomy_enabled=False,
                vector_enabled=False,
            )
        group = next(c for c in candidates if c.target_id == "community_food")
        self.assertEqual(group.op_hint, "add_to_group")
        self.assertEqual(group.entity_type, "community")
        self.assertTrue(group.metadata["membership_evidence"])

    def test_vector_channel_finds_semantic_candidate_without_lexical_overlap(self) -> None:
        user_id = 1
        source = "entity_japanese_food_vector"
        target = "entity_washoku_vector"
        with self.db.transaction() as conn:
            now = utc_now_iso()
            for entity_id, label in ((source, "Japanese food"), (target, "Washoku")):
                conn.execute(
                    """
                    INSERT INTO memory_entities(
                        entity_id,user_id,entity_type,identity_key,canonical_label,status,
                        resolver_version,created_at,updated_at
                    ) VALUES (?,?,'concept',?,?,'active',?,?,?)
                    """,
                    (entity_id, user_id, f"vector:{entity_id}", label, RESOLVER_VERSION, now, now),
                )
            for entity_id, vector in ((source, [1.0, 0.0, 0.0]), (target, [0.98, 0.05, 0.0])):
                conn.execute(
                    """
                    INSERT INTO memory_attachment_embeddings(
                        embed_id,user_id,object_kind,object_id,model_name,
                        embedding_json,content_hash,updated_at
                    ) VALUES (?,?, 'entity',?,'test-embedding-v1',?,?,?)
                    """,
                    (f"embed:{entity_id}", user_id, entity_id, json.dumps(vector), f"hash:{entity_id}", now),
                )
            without_vector = retrieve_candidates(
                conn, user_id=user_id, source_entity_id=source,
                source_label="Japanese food", attach_domains=("food",),
                curated_taxonomy_enabled=False, vector_enabled=False,
            )
            with_vector = retrieve_candidates(
                conn, user_id=user_id, source_entity_id=source,
                source_label="Japanese food", attach_domains=("food",),
                curated_taxonomy_enabled=False, vector_enabled=True,
            )
        self.assertNotIn(target, {item.target_id for item in without_vector})
        found = next(item for item in with_vector if item.target_id == target)
        self.assertEqual(found.channel, "vector")
        self.assertGreater(found.metadata["vector_similarity"], 0.95)

    def test_community_fit_uses_embeddings_for_non_member_without_name_overlap(self) -> None:
        user_id = 1
        source = "entity_tempura_group_vector"
        community = "community_cuisine_preferences_vector"
        with self.db.transaction() as conn:
            now = utc_now_iso()
            conn.execute(
                """
                INSERT INTO memory_entities(
                    entity_id,user_id,entity_type,identity_key,canonical_label,status,
                    resolver_version,created_at,updated_at
                ) VALUES (?,?,'concept','literal:string:tempura','Tempura','active',?,?,?)
                """,
                (source, user_id, RESOLVER_VERSION, now, now),
            )
            conn.execute(
                """
                INSERT INTO graph_communities(
                    community_id,user_id,community_type,label,member_node_ids_json,
                    member_belief_ids_json,seed_node_id,input_hash,detector_version,
                    graph_revision,status,created_at,updated_at
                ) VALUES (?,?,'semantic','Cluster 17','[]','[]','seed','input','v1',
                          0,'active',?,?)
                """,
                (community, user_id, now, now),
            )
            for kind, object_id, vector in (
                ("entity", source, [0.1, 0.9, 0.0]),
                ("community", community, [0.12, 0.88, 0.01]),
            ):
                conn.execute(
                    """
                    INSERT INTO memory_attachment_embeddings(
                        embed_id,user_id,object_kind,object_id,model_name,
                        embedding_json,content_hash,updated_at
                    ) VALUES (?,?,?,?, 'test-embedding-v1',?,?,?)
                    """,
                    (f"embed:{object_id}", user_id, kind, object_id, json.dumps(vector), f"hash:{object_id}", now),
                )
            candidates = retrieve_candidates(
                conn, user_id=user_id, source_entity_id=source, source_label="Tempura",
                attach_domains=("food",), curated_taxonomy_enabled=False,
                vector_enabled=True,
            )
        found = next(item for item in candidates if item.target_id == community)
        self.assertEqual(found.op_hint, "add_to_group")
        self.assertFalse(found.metadata["membership_evidence"])
        self.assertGreater(found.metadata["vector_similarity"], 0.99)

    def test_materializer_is_idempotent_and_reverts_expired_event_edges(self) -> None:
        user_id = 1
        source = "entity_source"
        target = "entity_target"
        belief_id = "belief_attachment_source"
        with self.db.transaction() as conn:
            _seed_belief_head(
                conn, user_id=user_id, belief_id=belief_id, schema_name="likes_food",
                entity_id=source, label="Sushi", entity_type="concept",
            )
            now = utc_now_iso()
            conn.execute(
                """
                INSERT INTO memory_entities(
                    entity_id,user_id,entity_type,identity_key,canonical_label,
                    status,resolver_version,created_at,updated_at
                ) VALUES (?,?,'concept',?,?,'active',?,?,?)
                """,
                (target, user_id, "taxonomy:japanese", "Japanese cuisine", RESOLVER_VERSION, now, now),
            )
            events = AttachmentEventsStore(self.db)
            event_id = events.insert_in_txn(
                conn, user_id=user_id, op="cuisine_of", source_belief_id=belief_id,
                source_entity_id=source, target_entity_id=target, domain_pack="food",
                tier="curated", status="active", utility_class="deferred",
                evidence={"belief_id": belief_id}, evidence_hash="evidence-1",
                critic_report=None, layer_trace={"layers": []}, input_hash="input-1",
                resolver_version=RESOLVER_VERSION,
            )

        materializer = AttachmentMaterializer(self.db)
        self.assertEqual(materializer.reconcile_events(user_id=user_id), 1)
        revision_after_first = MemoryGraphStore(self.db).current_revision(user_id)
        self.assertEqual(materializer.reconcile_events(user_id=user_id), 0)
        self.assertEqual(MemoryGraphStore(self.db).current_revision(user_id), revision_after_first)

        with self.db.transaction() as conn:
            changed = events.revert_for_belief_in_txn(
                conn, user_id=user_id, belief_id=belief_id, reason="explicit_contradiction"
            )
        self.assertEqual(changed, 1)
        self.assertEqual(materializer.reconcile_events(user_id=user_id), 1)
        with self.db.connection() as conn:
            event_status = conn.execute(
                "SELECT status FROM memory_attachment_events WHERE event_id=?", (event_id,)
            ).fetchone()["status"]
            edge_status = conn.execute(
                "SELECT status FROM graph_edges WHERE edge_type='attach:cuisine_of'"
            ).fetchone()["status"]
        self.assertEqual(event_status, "reverted")
        self.assertEqual(edge_status, "expired")

    def test_new_analysis_supersedes_prior_active_event_for_same_relation(self) -> None:
        events = AttachmentEventsStore(self.db)
        with self.db.transaction() as conn:
            common = {
                "user_id": 1,
                "op": "cuisine_of",
                "source_belief_id": None,
                "source_entity_id": "ramen",
                "target_entity_id": "japanese",
                "domain_pack": "food",
                "tier": "llm_committee",
                "status": "active",
                "utility_class": "deferred",
                "critic_report": None,
                "layer_trace": {"layers": []},
                "resolver_version": RESOLVER_VERSION,
            }
            first = events.insert_in_txn(
                conn, **common, evidence={"confidence": 0.88},
                evidence_hash="evidence-old", input_hash="input-old",
            )
            second = events.insert_in_txn(
                conn, **common, evidence={"confidence": 0.96},
                evidence_hash="evidence-new", input_hash="input-new",
            )
            rows = conn.execute(
                """
                SELECT event_id,status,supersedes_event_id
                FROM memory_attachment_events ORDER BY created_at,event_id
                """
            ).fetchall()
        by_id = {str(row["event_id"]): dict(row) for row in rows}
        self.assertEqual(by_id[first]["status"], "reverted")
        self.assertEqual(by_id[second]["status"], "active")
        self.assertEqual(by_id[second]["supersedes_event_id"], first)

    def test_belief_change_invalidates_attachment_depending_on_its_graph_edge(self) -> None:
        user_id = 1
        source_belief = "belief_source_ramen"
        taxonomy_belief = "belief_taxonomy_ramen"
        events = AttachmentEventsStore(self.db)
        dirty = AttachmentDirtyStore(self.db)
        with self.db.transaction() as conn:
            now = utc_now_iso()
            for belief_id in (source_belief, taxonomy_belief):
                conn.execute(
                    "INSERT INTO memory_beliefs VALUES (?,?,?,?,'test',?)",
                    (belief_id, user_id, belief_id, belief_id, now),
                )
            for entity_id,label in (("ramen","Ramen"),("japanese","Japanese cuisine")):
                conn.execute(
                    """
                    INSERT INTO memory_entities(
                        entity_id,user_id,entity_type,identity_key,canonical_label,status,
                        resolver_version,created_at,updated_at
                    ) VALUES (?,?,'concept',?,?,'active',?,?,?)
                    """,
                    (entity_id,user_id,f"test:{entity_id}",label,RESOLVER_VERSION,now,now),
                )
            graph = MemoryGraphStore(self.db)
            revision = graph.bump_revision_in_txn(conn,user_id=user_id)
            ramen_node = graph.upsert_node_in_txn(
                conn,user_id=user_id,node_type="concept",source_record_id="ramen",
                label="Ramen",properties={},graph_revision=revision,
            )
            cuisine_node = graph.upsert_node_in_txn(
                conn,user_id=user_id,node_type="concept",source_record_id="japanese",
                label="Japanese cuisine",properties={},graph_revision=revision,
            )
            edge_id = graph.upsert_edge_in_txn(
                conn,user_id=user_id,belief_id=taxonomy_belief,
                from_node_id=ramen_node,to_node_id=cuisine_node,
                edge_type="attach:cuisine_of",properties={},payload_hash="taxonomy",
                graph_revision=revision,
            )
            event_id = events.insert_in_txn(
                conn,user_id=user_id,op="add_to_group",source_belief_id=source_belief,
                source_entity_id="ramen",target_entity_id="community_food",
                domain_pack="food",tier="llm_committee",status="active",
                utility_class="deferred",evidence={"path":[edge_id]},
                evidence_hash="dependent-evidence",critic_report=None,
                layer_trace={"layers":[]},input_hash="dependent-input",
                resolver_version=RESOLVER_VERSION,
            )
            events.insert_dependencies_in_txn(
                conn,event_id=event_id,user_id=user_id,
                dependencies=[
                    {"dependency_type":"belief","dependency_id":source_belief},
                    {"dependency_type":"graph_edge","dependency_id":edge_id,"path":[edge_id]},
                ],
            )
            AttachmentInvalidator(dirty=dirty,config=_attach_config()).mark_from_belief_change_in_txn(
                conn,user_id=user_id,belief_id=taxonomy_belief,
            )
            event_status = conn.execute(
                "SELECT status FROM memory_attachment_events WHERE event_id=?",(event_id,)
            ).fetchone()["status"]
            dep_status = conn.execute(
                """
                SELECT status FROM memory_attachment_dependencies
                WHERE event_id=? AND dependency_type='graph_edge'
                """,(event_id,)
            ).fetchone()["status"]
        self.assertEqual(event_status,"reverted")
        self.assertEqual(dep_status,"invalidated")

    def test_explicit_negative_constraint_reverts_and_blocks_inferred_preference(self) -> None:
        events = AttachmentEventsStore(self.db)
        with self.db.transaction() as conn:
            event_id = events.insert_in_txn(
                conn, user_id=1, op="inferred_preference", source_belief_id=None,
                source_entity_id="dish_sushi", target_entity_id="japanese_cuisine",
                domain_pack="food", tier="llm_committee", status="active",
                utility_class="deferred", evidence={"path": ["sushi", "japanese"]},
                evidence_hash="inferred-evidence", critic_report=None,
                layer_trace={"layers": []}, input_hash="inferred-input",
                resolver_version=RESOLVER_VERSION,
            )
            constraint_id, reverted = apply_negative_preference_constraint_in_txn(
                conn, user_id=1, target_entity_id="japanese_cuisine",
                source_belief_id="belief_dislikes_japanese",
                reason={"polarity": "negative", "explicit": True},
            )
            blocked = blocks_inferred_preference(
                conn, user_id=1, target_entity_id="japanese_cuisine"
            )
            status = conn.execute(
                "SELECT status FROM memory_attachment_events WHERE event_id=?", (event_id,)
            ).fetchone()["status"]
        self.assertTrue(constraint_id.startswith("mac_"))
        self.assertEqual(reverted, 1)
        self.assertTrue(blocked)
        self.assertEqual(status, "reverted")

    def test_new_explicit_positive_releases_negative_constraint(self) -> None:
        with self.db.transaction() as conn:
            apply_negative_preference_constraint_in_txn(
                conn, user_id=1, target_entity_id="japanese_cuisine",
                source_belief_id="belief_negative",
            )
            self.assertTrue(
                blocks_inferred_preference(
                    conn, user_id=1, target_entity_id="japanese_cuisine"
                )
            )
            released = release_negative_preference_constraints_in_txn(
                conn, user_id=1, target_entity_id="japanese_cuisine"
            )
            blocked = blocks_inferred_preference(
                conn, user_id=1, target_entity_id="japanese_cuisine"
            )
        self.assertEqual(released, 1)
        self.assertFalse(blocked)

    def test_negative_preference_pipeline_applies_constraint_without_llm(self) -> None:
        user_id = 1
        target = "japanese_cuisine"
        belief_id = "belief_dislikes_japanese"
        with self.db.transaction() as conn:
            _seed_belief_head(
                conn, user_id=user_id, belief_id=belief_id,
                schema_name="likes_food", entity_id=target,
                label="Japanese cuisine", entity_type="concept", polarity="negative",
            )
            result = asyncio.run(
                analyze_attachment(
                    conn, user_id=user_id, belief_id=belief_id,
                    config=_attach_config(), hypothesis_model=FakeAttachmentModel([]),
                    commit=True, events_store=AttachmentEventsStore(self.db),
                )
            )
            blocked = blocks_inferred_preference(
                conn, user_id=user_id, target_entity_id=target
            )
        self.assertFalse(result.accepted)
        self.assertEqual(result.abstain_reason, "negative_constraint_applied")
        self.assertEqual(result.llm_calls, 0)
        self.assertTrue(blocked)

    def test_pipeline_commits_multiple_independently_verified_attachments(self) -> None:
        user_id = 1
        source = "entity_ramen_multi"
        cuisine = "entity_japanese_cuisine_multi"
        group = "community_ramen_preferences"
        belief_id = "belief_likes_ramen_multi"
        with self.db.transaction() as conn:
            _seed_belief_head(
                conn, user_id=user_id, belief_id=belief_id, schema_name="likes_food",
                entity_id=source, label="Ramen", entity_type="concept",
            )
            now = utc_now_iso()
            conn.execute(
                """
                INSERT INTO memory_entities(
                    entity_id,user_id,entity_type,identity_key,canonical_label,status,
                    resolver_version,created_at,updated_at
                ) VALUES (?,?,'concept','taxonomy:japanese','Ramen Japanese cuisine',
                          'active',?,?,?)
                """,
                (cuisine, user_id, RESOLVER_VERSION, now, now),
            )
            conn.execute(
                """
                INSERT INTO graph_communities(
                    community_id,user_id,community_type,label,member_node_ids_json,
                    member_belief_ids_json,seed_node_id,input_hash,detector_version,
                    graph_revision,status,created_at,updated_at
                ) VALUES (?,?, 'semantic','Ramen preferences','[]','[]','seed-node',
                          'community-input','test-v1',0,'active',?,?)
                """,
                (group, user_id, now, now),
            )
            hypothesis_model = FakeAttachmentModel(
                [
                    json.dumps(
                        {
                            "schema_version": ATTACHMENT_SCHEMA_VERSION,
                            "hypotheses": [
                                {"op": "cuisine_of", "target_id": cuisine, "confidence": 0.97},
                                {"op": "add_to_group", "target_id": group, "confidence": 0.91},
                            ],
                        }
                    )
                ]
            )
            support_model = FakeAttachmentModel(
                [
                    json.dumps(
                        {
                            "schema_version": ATTACHMENT_SCHEMA_VERSION,
                            "verdicts": [
                                {"op": "cuisine_of", "target_id": cuisine, "verdict": "supported"},
                                {"op": "add_to_group", "target_id": group, "verdict": "supported"},
                            ],
                        }
                    )
                ]
            )
            adversarial_model = FakeAttachmentModel(
                [
                    json.dumps(
                        {
                            "schema_version": ATTACHMENT_SCHEMA_VERSION,
                            "verdicts": [
                                {"op": "cuisine_of", "target_id": cuisine, "verdict": "supported"},
                                {"op": "add_to_group", "target_id": group, "verdict": "supported"},
                            ],
                        }
                    )
                ]
            )
            result = asyncio.run(
                analyze_attachment(
                    conn, user_id=user_id, belief_id=belief_id,
                    config=_attach_config(curated_taxonomy_enabled=False),
                    hypothesis_model=hypothesis_model, support_model=support_model,
                    adversarial_model=adversarial_model, commit=True,
                    events_store=AttachmentEventsStore(self.db),
                )
            )
            active = conn.execute(
                """
                SELECT op,target_entity_id FROM memory_attachment_events
                WHERE user_id=? AND status='active' ORDER BY op,target_entity_id
                """,
                (user_id,),
            ).fetchall()
        self.assertTrue(result.accepted, result)
        self.assertEqual(len(result.accepted_hypotheses), 2)
        self.assertEqual(
            [tuple(row) for row in active],
            [("add_to_group", group), ("cuisine_of", cuisine)],
        )
        self.assertEqual(result.llm_calls, 3)
        materialized = AttachmentMaterializer(self.db).reconcile_events(user_id=user_id)
        with self.db.connection() as conn:
            edges = conn.execute(
                """
                SELECT edge_type,status FROM graph_edges
                WHERE edge_type LIKE 'attach:%' ORDER BY edge_type
                """
            ).fetchall()
        self.assertEqual(materialized, 2)
        self.assertEqual(
            [tuple(row) for row in edges],
            [("attach:add_to_group", "active"), ("attach:cuisine_of", "active")],
        )

    def test_gradual_first_cuisine_deferred_second_promotes(self) -> None:
        user_id = 1
        source_a = "dish_a"
        source_b = "dish_b"
        target = taxonomy_parent_entity_id(user_id=user_id, parent_key="italian_cuisine")
        with self.db.connection() as conn:
            first = decide_utility_class(
                conn,
                user_id=user_id,
                source_entity_id=source_a,
                op="cuisine_of",
                target_entity_id=target,
            )
            events = AttachmentEventsStore(self.db)
            events.insert_in_txn(
                conn,
                user_id=user_id,
                op="cuisine_of",
                source_belief_id="b1",
                source_entity_id=source_a,
                target_entity_id=target,
                domain_pack="food",
                tier="curated",
                status="active",
                utility_class=first,
                evidence={"belief_id": "b1"},
                evidence_hash="h1",
                critic_report=None,
                layer_trace={"layers": []},
                input_hash="in1",
                resolver_version=RESOLVER_VERSION,
            )
            second = decide_utility_class(
                conn,
                user_id=user_id,
                source_entity_id=source_b,
                op="cuisine_of",
                target_entity_id=target,
            )
            inferred = decide_utility_class(
                conn,
                user_id=user_id,
                source_entity_id=source_b,
                op="inferred_preference",
                target_entity_id=target,
            )
        self.assertEqual(first, "deferred")
        self.assertEqual(second, "durable")
        self.assertEqual(inferred, "deferred")

    def test_flag_off_no_attach_jobs(self) -> None:
        service = MemoryService(
            config=_memory_config(
                self.db_path,
                attachment_enabled=False,
                attachment_generation_enabled=False,
                attachment_verify_enabled=False,
                attachment_inferred_preference_enabled=False,
            )
        )
        dirty = AttachmentDirtyStore(service.db)
        with service.db.transaction() as conn:
            dirty.mark_in_txn(
                conn,
                user_id=1,
                belief_id="belief_x",
                debounce_seconds=0.0,
            )
        scheduler = AttachmentDirtyScheduler(service=service)
        result = scheduler.scan_once()
        self.assertEqual(result.jobs_created, 0)
        with service.db.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM memory_jobs WHERE stage = ?",
                (ATTACH_ANALYZE_STAGE,),
            ).fetchone()
        self.assertEqual(int(row["c"]), 0)

    def test_accept_rule_unique_winner(self) -> None:
        hyps = (
            AttachmentHypothesis(op="cuisine_of", target_id="t1"),
            AttachmentHypothesis(op="cuisine_of", target_id="t1"),
        )
        from memory.attachment.hypotheses import pick_unique_winner

        self.assertIsNotNone(pick_unique_winner(hyps))
        mixed = (
            AttachmentHypothesis(op="cuisine_of", target_id="t1"),
            AttachmentHypothesis(op="cuisine_of", target_id="t2"),
        )
        self.assertIsNone(pick_unique_winner(mixed))

    def test_attach_job_uses_belief_target(self) -> None:
        req = attach_job_request(
            user_id=1,
            belief_id="belief_abc",
            generation_enabled=True,
            verify_enabled=True,
            model_profile="extraction",
        )
        self.assertEqual(req.target_kind, "belief")
        self.assertEqual(req.target_id, "belief_abc")
        self.assertEqual(req.stage, ATTACH_ANALYZE_STAGE)

    def test_validate_memory_config_attachment_chain(self) -> None:
        with self.assertRaises(ValueError):
            validate_memory_config(
                _memory_config(self.db_path, graph_enabled=False, attachment_enabled=True)
            )
        with self.assertRaises(ValueError):
            validate_memory_config(
                _memory_config(
                    self.db_path,
                    attachment_generation_enabled=True,
                    attachment_enabled=False,
                )
            )


class AttachmentCriticsTests(unittest.TestCase):
    def test_fake_models_l4_l6(self) -> None:
        shortlist = (
            ShortlistCandidate(target_id="t1", label="German", entity_type="concept"),
        )
        hyp_model = FakeAttachmentModel(
            [
                json.dumps(
                    {
                        "schema_version": ATTACHMENT_SCHEMA_VERSION,
                        "hypotheses": [{"op": "cuisine_of", "target_id": "t1"}],
                    }
                )
            ]
        )
        support = FakeAttachmentModel(
            [json.dumps({"schema_version": ATTACHMENT_SCHEMA_VERSION, "verdict": "supported"})]
        )
        adv = FakeAttachmentModel(
            [json.dumps({"schema_version": ATTACHMENT_SCHEMA_VERSION, "verdict": "supported"})]
        )
        hyps, l4, c4 = asyncio.run(
            run_hypothesis_layer(
                hyp_model,
                context_statement="likes Kartoffelsalat",
                shortlist=shortlist,
                attach_domains=("food",),
            )
        )
        self.assertEqual(c4, 1)
        self.assertEqual(len(hyps), 1)
        l5, _ = asyncio.run(
            run_support_critic(
                support,
                hypothesis=hyps[0],
                context_statement="likes Kartoffelsalat",
            )
        )
        l6, _ = asyncio.run(
            run_adversarial_critic(
                adv,
                hypothesis=hyps[0],
                context_statement="likes Kartoffelsalat",
            )
        )
        accepted, reason = accept_from_layers(
            winner=hyps[0],
            layers=(l4, l5, l6),
        )
        self.assertTrue(accepted)
        self.assertIsNone(reason)

    def test_batch_critics_validate_each_hypothesis_and_keep_supported_subset(self) -> None:
        hypotheses = (
            AttachmentHypothesis("cuisine_of", "japanese", confidence=0.96),
            AttachmentHypothesis("add_to_group", "food_group", confidence=0.90),
        )
        support_model = FakeAttachmentModel(
            [
                json.dumps(
                    {
                        "schema_version": ATTACHMENT_SCHEMA_VERSION,
                        "verdicts": [
                            {"op": "cuisine_of", "target_id": "japanese", "verdict": "supported"},
                            {"op": "add_to_group", "target_id": "food_group", "verdict": "supported"},
                        ],
                    }
                )
            ]
        )
        adversarial_model = FakeAttachmentModel(
            [
                json.dumps(
                    {
                        "schema_version": ATTACHMENT_SCHEMA_VERSION,
                        "verdicts": [
                            {"op": "cuisine_of", "target_id": "japanese", "verdict": "supported"},
                            {"op": "add_to_group", "target_id": "food_group", "verdict": "contradicted"},
                        ],
                    }
                )
            ]
        )
        support, support_calls = asyncio.run(
            run_set_critic(
                support_model, layer="L5", hypotheses=hypotheses,
                context_statement="I like ramen", adversarial=False,
            )
        )
        adversarial, adversarial_calls = asyncio.run(
            run_set_critic(
                adversarial_model, layer="L6", hypotheses=hypotheses,
                context_statement="I like ramen", adversarial=True,
            )
        )
        accepted = accepted_hypotheses_from_critics(
            hypotheses, support=support, adversarial=adversarial
        )
        self.assertEqual(support_calls + adversarial_calls, 2)
        self.assertEqual([(item.op, item.target_id) for item in accepted], [("cuisine_of", "japanese")])

    def test_reversible_group_can_fallback_on_strong_fit_and_failed_attack(self) -> None:
        hypothesis = AttachmentHypothesis(
            "add_to_group", "food_group", confidence=0.9
        )
        accepted = accepted_hypotheses_from_critics(
            (hypothesis,),
            support={(hypothesis.op, hypothesis.target_id): LayerVerdict("L5", "malformed")},
            adversarial={(hypothesis.op, hypothesis.target_id): LayerVerdict("L6", "supported")},
            shortlist=(
                ShortlistCandidate(
                    "food_group", "Food group", "community", op_hint="add_to_group",
                    metadata={"vector_similarity": 0.9, "membership_evidence": False},
                ),
            ),
        )
        self.assertEqual(accepted, (hypothesis,))

    def test_reversible_relation_can_triangulate_malformed_support(self) -> None:
        hypothesis = AttachmentHypothesis("part_of", "postgres", confidence=0.96)
        accepted = accepted_hypotheses_from_critics(
            (hypothesis,),
            support={(hypothesis.op, hypothesis.target_id): LayerVerdict("L5", "malformed")},
            adversarial={(hypothesis.op, hypothesis.target_id): LayerVerdict("L6", "supported")},
            shortlist=(
                ShortlistCandidate(
                    "postgres", "PostgreSQL", "software", op_hint="part_of",
                    metadata={"graph_distance": 1, "edge_status": "active"},
                ),
            ),
        )
        identity = AttachmentHypothesis("same_as", "postgres", confidence=0.99)
        rejected_identity = accepted_hypotheses_from_critics(
            (identity,),
            support={(identity.op, identity.target_id): LayerVerdict("L5", "malformed")},
            adversarial={(identity.op, identity.target_id): LayerVerdict("L6", "supported")},
            shortlist=(
                ShortlistCandidate(
                    "postgres", "PostgreSQL", "software", op_hint="same_as",
                    metadata={"graph_distance": 1, "edge_status": "active"},
                ),
            ),
        )
        self.assertEqual(accepted, (hypothesis,))
        self.assertEqual(rejected_identity, ())


if __name__ == "__main__":
    unittest.main()
