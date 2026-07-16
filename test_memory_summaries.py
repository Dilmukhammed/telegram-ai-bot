from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memory.config import MemoryConfig, validate_memory_config
from memory.schema import SCHEMA_VERSION, ensure_schema
from memory.service import MemoryService
from memory.summaries.dirty import SummaryDirtyStore
from memory.summaries.eligibility import (
    beliefs_for_core_profile,
    beliefs_for_entity,
)
from memory.summaries.generation.generator import (
    DeterministicSummaryGenerator,
    generate_summary_draft,
)
from memory.summaries.generation.parser import parse_summary_output
from memory.summaries.jobs import decode_summary_target, encode_summary_target
from memory.summaries.schemas import (
    BeliefSnapshot,
    STATUS_ACTIVE,
    STATUS_REJECTED,
    SUMMARY_TYPE_CORE_PROFILE,
    SUMMARY_TYPE_ENTITY,
    SummaryDraft,
    SummarySentence,
    user_target_id,
)
from memory.summaries.store import SummaryStore
from memory.summaries.verification.pipeline import (
    FailClosedVerifierModel,
    verify_summary_draft,
)
from memory.summaries.verification.preflight import run_preflight


def _belief(
    *,
    belief_id: str,
    status: str = "active",
    utility: str = "durable",
    entity_ids: tuple[str, ...] = (),
    statement: str = "likes Italian food",
) -> BeliefSnapshot:
    return BeliefSnapshot(
        belief_id=belief_id,
        schema_name="likes",
        statement=statement,
        belief_status=status,
        utility_class=utility,
        polarity="positive",
        entity_ids=entity_ids,
        temporal=None,
    )


class SummarySchemaTests(unittest.TestCase):
    def test_fresh_db_is_schema_v11(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "memory.sqlite")
            service = MemoryService(
                config=MemoryConfig(
                    ingest_enabled=False,
                    db_path=path,
                    worker_enabled=False,
                    worker_concurrency=1,
                    worker_poll_seconds=1.0,
                    job_lease_seconds=10,
                    job_max_attempts=1,
                    job_retry_base_seconds=1.0,
                    job_retry_max_seconds=1.0,
                    job_claim_batch_size=1,
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
                cols = {
                    str(row["name"])
                    for row in conn.execute(
                        "PRAGMA table_info(memory_shadow_retrieval_runs)"
                    ).fetchall()
                }
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertEqual(SCHEMA_VERSION, 13)
            for name in (
                "graph_summaries",
                "graph_communities",
                "graph_summary_dirty",
                "graph_summary_user_state",
                "memory_attachment_events",
                "memory_attachment_negatives",
                "memory_attachment_dirty",
            ):
                self.assertIn(name, tables)
            self.assertIn("summary_pack_json", cols)


class EligibilityTests(unittest.TestCase):
    def test_core_profile_durable_only(self) -> None:
        beliefs = (
            _belief(belief_id="b1"),
            _belief(belief_id="b2", utility="task"),
            _belief(belief_id="b3", status="uncertain"),
        )
        eligible = beliefs_for_core_profile(beliefs)
        self.assertEqual([b.belief_id for b in eligible], ["b1"])

    def test_entity_filters_by_entity_id(self) -> None:
        beliefs = (
            _belief(belief_id="b1", entity_ids=("e1",)),
            _belief(belief_id="b2", entity_ids=("e2",)),
        )
        eligible = beliefs_for_entity(beliefs, entity_id="e1")
        self.assertEqual([b.belief_id for b in eligible], ["b1"])


class DirtyTests(unittest.TestCase):
    def test_mark_debounces_and_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "memory.sqlite")
            from memory.db import MemoryDatabase

            db = MemoryDatabase(path)
            with db.connection() as conn:
                ensure_schema(conn)
            dirty = SummaryDirtyStore(db)
            uid = user_target_id(7)
            with db.transaction() as conn:
                dirty.mark_in_txn(
                    conn,
                    user_id=7,
                    summary_type=SUMMARY_TYPE_CORE_PROFILE,
                    target_id=uid,
                    debounce_seconds=120.0,
                )
            self.assertEqual(dirty.backlog_count(), 1)
            self.assertEqual(dirty.claim(limit=5), [])
            with db.transaction() as conn:
                conn.execute(
                    """
                    UPDATE graph_summary_dirty
                    SET not_before = ?
                    WHERE user_id = ?
                    """,
                    (
                        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                        7,
                    ),
                )
            claimed = dirty.claim(limit=5)
            self.assertEqual(len(claimed), 1)
            self.assertEqual(claimed[0].summary_type, SUMMARY_TYPE_CORE_PROFILE)


class VerifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_fail_closed_rejects_unsupported(self) -> None:
        beliefs = (_belief(belief_id="b1", statement="likes pasta"),)
        draft = SummaryDraft(
            sentences=(
                SummarySentence(
                    text="User owns a submarine.",
                    belief_ids=("b1",),
                ),
            ),
            content="User owns a submarine.",
            belief_ids=("b1",),
            sentence_support={"0": ("b1",)},
        )
        result = await verify_summary_draft(
            draft,
            input_beliefs=beliefs,
            model=FailClosedVerifierModel(),
            verify_enabled=True,
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.reject_reason, "sentence_0_unsupported")

    async def test_preflight_rejects_unknown_belief(self) -> None:
        beliefs = (_belief(belief_id="b1"),)
        draft = parse_summary_output(
            json.dumps(
                {
                    "sentences": [
                        {"text": "likes pasta", "belief_ids": ["missing"]},
                    ]
                }
            )
        )
        ok, reason = run_preflight(draft, input_beliefs=beliefs)
        self.assertFalse(ok)
        self.assertIn("unknown_belief", reason or "")


class GeneratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_generator_never_reads_old_summary(self) -> None:
        source = inspect.getsource(generate_summary_draft)
        self.assertNotIn("get_active", source)
        self.assertNotIn("graph_summaries", source)
        beliefs = (_belief(belief_id="b1"),)
        draft = await generate_summary_draft(
            user_id=1,
            summary_type=SUMMARY_TYPE_CORE_PROFILE,
            target_id=user_target_id(1),
            beliefs=beliefs,
            model=DeterministicSummaryGenerator(),
        )
        self.assertEqual(draft.belief_ids, ("b1",))


class ProcessorFailClosedTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_keeps_prior_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "memory.sqlite")
            from memory.db import MemoryDatabase

            db = MemoryDatabase(path)
            with db.connection() as conn:
                ensure_schema(conn)
            summaries = SummaryStore(db)
            beliefs = (_belief(belief_id="b1"),)
            good = SummaryDraft(
                sentences=(SummarySentence(text="likes pasta", belief_ids=("b1",)),),
                content="likes pasta",
                belief_ids=("b1",),
                sentence_support={"0": ("b1",)},
            )
            bad = SummaryDraft(
                sentences=(
                    SummarySentence(
                        text="unsupported claim",
                        belief_ids=("b1",),
                    ),
                ),
                content="unsupported claim",
                belief_ids=("b1",),
                sentence_support={"0": ("b1",)},
            )
            with db.transaction() as conn:
                summaries.insert_in_txn(
                    conn,
                    user_id=1,
                    summary_type=SUMMARY_TYPE_ENTITY,
                    target_id="e1",
                    draft=good,
                    input_hash="hash-good",
                    status=STATUS_ACTIVE,
                    graph_revision=0,
                    model_profile="test",
                )
            verification = await verify_summary_draft(
                bad,
                input_beliefs=beliefs,
                model=FailClosedVerifierModel(),
                verify_enabled=True,
            )
            self.assertFalse(verification.accepted)
            with db.transaction() as conn:
                summaries.insert_in_txn(
                    conn,
                    user_id=1,
                    summary_type=SUMMARY_TYPE_ENTITY,
                    target_id="e1",
                    draft=bad,
                    input_hash="hash-bad",
                    status=STATUS_REJECTED,
                    graph_revision=0,
                    model_profile="test",
                )
            active = summaries.get_active(
                user_id=1,
                summary_type=SUMMARY_TYPE_ENTITY,
                target_id="e1",
            )
            self.assertIsNotNone(active)
            self.assertEqual(active.content, "likes pasta")
            counts = summaries.count_by_status(user_id=1)
            self.assertGreaterEqual(counts.get(STATUS_REJECTED, 0), 1)


class ConfigGuardTests(unittest.TestCase):
    def test_flag_off_defaults_validate(self) -> None:
        validate_memory_config(
            MemoryConfig(
                ingest_enabled=False,
                db_path=":memory:",
                worker_enabled=False,
                worker_concurrency=1,
                worker_poll_seconds=1.0,
                job_lease_seconds=10,
                job_max_attempts=1,
                job_retry_base_seconds=1.0,
                job_retry_max_seconds=1.0,
                job_claim_batch_size=1,
            )
        )

    def test_summaries_requires_graph_and_worker(self) -> None:
        with self.assertRaises(ValueError):
            validate_memory_config(
                MemoryConfig(
                    ingest_enabled=False,
                    db_path=":memory:",
                    worker_enabled=False,
                    worker_concurrency=1,
                    worker_poll_seconds=1.0,
                    job_lease_seconds=10,
                    job_max_attempts=1,
                    job_retry_base_seconds=1.0,
                    job_retry_max_seconds=1.0,
                    job_claim_batch_size=1,
                    summaries_enabled=True,
                    graph_enabled=False,
                )
            )


class TargetCodecTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        encoded = encode_summary_target(
            summary_type=SUMMARY_TYPE_CORE_PROFILE,
            target_id=user_target_id(3),
        )
        summary_type, target_id = decode_summary_target(encoded)
        self.assertEqual(summary_type, SUMMARY_TYPE_CORE_PROFILE)
        self.assertEqual(target_id, user_target_id(3))
