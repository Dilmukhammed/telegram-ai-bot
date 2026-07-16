from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from memory.config import MemoryConfig, validate_memory_config
from memory.db import utc_now_iso
from memory.ids import make_entity_id
from memory.resolution.canonical import canonical_entity_id
from memory.resolution.candidates import extract_stable_id, generate_candidates, trigram_jaccard
from memory.resolution.er_types import PairVerdict
from memory.resolution.events_store import (
    build_merge_event,
    build_split_event,
    insert_events_in_txn,
)
from memory.resolution.pairwise import unique_winner
from memory.resolution.pipeline import register_candidate_resolver
from memory.resolution.schemas import RESOLVER_VERSION
from memory.schema import SCHEMA_VERSION, ensure_schema
from memory.service import MemoryService
from memory.verification.scoring import DEFAULT_POLICY_VERSION


POLICY = DEFAULT_POLICY_VERSION


def _config(path: str, **overrides) -> MemoryConfig:
    base = MemoryConfig(
        ingest_enabled=False,
        db_path=path,
        worker_enabled=True,
        worker_concurrency=1,
        worker_poll_seconds=0.01,
        job_lease_seconds=10,
        job_max_attempts=2,
        job_retry_base_seconds=0.01,
        job_retry_max_seconds=0.02,
        job_claim_batch_size=1,
        verification_enabled=True,
        resolution_enabled=True,
        required_verification_policy_version=POLICY,
    )
    return MemoryConfig(**{**base.__dict__, **overrides})


class SchemaV10Tests(unittest.TestCase):
    def test_fresh_db_is_schema_v11(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "memory.sqlite")
            service = MemoryService(
                config=_config(
                    path,
                    worker_enabled=False,
                    verification_enabled=False,
                    resolution_enabled=False,
                )
            )
            with service.db.connection() as conn:
                ensure_schema(conn)
                version = int(
                    conn.execute(
                        "SELECT MAX(version) AS v FROM memory_schema_migrations"
                    ).fetchone()["v"]
                )
                tables = {
                    str(row["name"])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertEqual(SCHEMA_VERSION, 13)
            self.assertIn("memory_entity_resolution_events", tables)
            self.assertIn("memory_entity_alias_equivalences", tables)


class CandidateUnitTests(unittest.TestCase):
    def test_trigram_jaccard(self) -> None:
        self.assertGreater(trigram_jaccard("acme", "acme corp"), 0.2)
        self.assertEqual(trigram_jaccard("", ""), 1.0)
        self.assertEqual(trigram_jaccard("abc", "xyz"), 0.0)

    def test_extract_stable_id(self) -> None:
        mention = {
            "mention_id": "mmen_test",
            "mention_type": "person",
            "surface_text": "Alice",
            "attributes": {"email": "Alice@Example.COM"},
        }
        self.assertEqual(extract_stable_id(mention), "alice@example.com")

    def test_unique_winner_requires_single_accept(self) -> None:
        self.assertIsNone(unique_winner(()))
        self.assertIsNone(
            unique_winner(
                (
                    PairVerdict("e1", True, "a", "exact_alias", "critic"),
                    PairVerdict("e2", True, "b", "exact_alias", "critic"),
                )
            )
        )
        winner = unique_winner(
            (PairVerdict("e1", True, "a", "stable_id", "deterministic"),)
        )
        self.assertIsNotNone(winner)
        assert winner is not None
        self.assertEqual(winner.entity_id, "e1")


class GenerateCandidatesTests(unittest.TestCase):
    def test_person_never_merges_by_name_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "memory.sqlite")
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            ensure_schema(conn)
            now = utc_now_iso()
            user_id = 7
            other_id = make_entity_id(
                user_id=user_id,
                entity_type="person",
                identity_key="name:bob",
                resolver_version=RESOLVER_VERSION,
            )
            conn.execute(
                """
                INSERT INTO memory_entities(
                    entity_id, user_id, entity_type, identity_key, canonical_label,
                    status, resolver_version, created_at, updated_at
                ) VALUES (?, ?, 'person', 'name:bob', 'Bob', 'active', ?, ?, ?)
                """,
                (other_id, user_id, RESOLVER_VERSION, now, now),
            )
            conn.execute(
                """
                INSERT INTO memory_entity_aliases(
                    alias_id, user_id, entity_id, source_mention_id, alias,
                    normalized_alias, language, evidence_pointer_json, status, created_at
                ) VALUES ('malias_bob', ?, ?, NULL, 'Bob', 'bob', NULL, NULL, 'active', ?)
                """,
                (user_id, other_id, now),
            )
            conn.commit()
            mention = {
                "mention_id": "mmen_bob2",
                "mention_type": "person",
                "surface_text": "Bob",
            }
            candidate_set = generate_candidates(
                conn,
                user_id,
                mention,
                fuzzy_enabled=True,
                fuzzy_min_trigram=0.1,
                cross_language_enabled=True,
                max_candidates=8,
            )
            self.assertEqual(candidate_set.candidates, ())
            conn.close()


class CanonicalMergeSplitTests(unittest.TestCase):
    def test_canonical_merge_then_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "memory.sqlite")
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            ensure_schema(conn)
            now = utc_now_iso()
            user_id = 7
            winner = make_entity_id(
                user_id=user_id,
                entity_type="organization",
                identity_key="org:acme",
                resolver_version=RESOLVER_VERSION,
            )
            loser = make_entity_id(
                user_id=user_id,
                entity_type="organization",
                identity_key="mention:mmen_acme",
                resolver_version=RESOLVER_VERSION,
            )
            for entity_id, identity_key, label in (
                (winner, "org:acme", "Acme Corp"),
                (loser, "mention:mmen_acme", "ACME"),
            ):
                conn.execute(
                    """
                    INSERT INTO memory_entities(
                        entity_id, user_id, entity_type, identity_key, canonical_label,
                        status, resolver_version, created_at, updated_at
                    ) VALUES (?, ?, 'organization', ?, ?, 'active', ?, ?, ?)
                    """,
                    (entity_id, user_id, identity_key, label, RESOLVER_VERSION, now, now),
                )
            merge = build_merge_event(
                user_id=user_id,
                winner_entity_id=winner,
                loser_entity_id=loser,
                cluster_key="mmen_acme",
                tier="exact_alias",
                evidence={"mention_id": "mmen_acme"},
                reason="exact_alias",
                decided_by="critic",
            )
            insert_events_in_txn(conn, user_id, (merge,), resolution_run_id=None, now=now)
            conn.commit()
            self.assertEqual(canonical_entity_id(conn, user_id, loser), winner)
            split = build_split_event(
                user_id=user_id,
                winner_entity_id=winner,
                loser_entity_id=loser,
                cluster_key="mmen_acme",
                tier="exact_alias",
                evidence={"invalidation_reason": "test"},
                reason="evidence_invalidated",
                decided_by="deterministic",
                merge_event_id=merge.event_id,
            )
            insert_events_in_txn(conn, user_id, (split,), resolution_run_id=None, now=now)
            conn.execute(
                """
                UPDATE memory_entity_resolution_events
                SET status = 'reverted'
                WHERE event_id = ?
                """,
                (merge.event_id,),
            )
            conn.commit()
            self.assertEqual(canonical_entity_id(conn, user_id, loser), loser)
            conn.close()


class ConfigGuardTests(unittest.TestCase):
    def test_candidate_generation_requires_merge_events(self) -> None:
        with self.assertRaises(ValueError):
            validate_memory_config(
                _config(
                    "unused.sqlite",
                    resolution_candidate_generation_enabled=True,
                    resolution_merge_events_enabled=False,
                )
            )

    def test_fuzzy_requires_candidate_generation(self) -> None:
        with self.assertRaises(ValueError):
            validate_memory_config(
                _config(
                    "unused.sqlite",
                    resolution_fuzzy_blocking_enabled=True,
                    resolution_candidate_generation_enabled=False,
                    resolution_merge_events_enabled=True,
                )
            )


class FlagOffClassicSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_flag_off_uses_classic_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "memory.sqlite")
            config = _config(
                path,
                resolution_candidate_generation_enabled=False,
                resolution_merge_events_enabled=False,
            )
            service = MemoryService(config=config)
            processor = register_candidate_resolver(
                service.registry,
                service=service,
                required_verification_policy=POLICY,
            )
            self.assertFalse(processor._er_config.candidate_generation_enabled)
            await service.stop_worker(grace_seconds=0.1)


if __name__ == "__main__":
    unittest.main()
