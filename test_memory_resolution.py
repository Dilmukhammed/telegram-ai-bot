from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from memory.config import MemoryConfig
from memory.db import utc_now_iso
from memory.extraction.candidates import CandidateEvidenceInput, CandidateInput
from memory.extraction.mentions import MentionInput
from memory.extraction.schemas import (
    CandidateArgument,
    CandidateStatus,
    Epistemic,
    EpistemicMode,
    EpistemicScope,
    Polarity,
    SpeakerCommitment,
)
from memory.ids import content_hash_from_text, make_score_id
from memory.models import JobRequest, JobStatus, SegmentInput, SourceInput
from memory.pointers import EvidencePointer
from memory.resolution.jobs import resolution_input_hash, resolution_job_request
from memory.resolution.entities import resolve_literal_argument
from memory.resolution.normalization import lookup_key
from memory.resolution.pipeline import register_candidate_resolver
from memory.resolution.scheduler import ResolutionScheduler
from memory.resolution.schemas import ASSERTION_SCHEMA_VERSION, RESOLVER_VERSION
from memory.resolution.utility import classify_utility
from memory.schema import SCHEMA_VERSION, ensure_schema
from memory.service import MemoryService
from memory.verification.scoring import DEFAULT_POLICY_VERSION


POLICY = DEFAULT_POLICY_VERSION


class LiteralEntityIdentityTests(unittest.TestCase):
    def test_literal_concept_identity_does_not_depend_on_argument_role(self) -> None:
        conn = sqlite3.connect(":memory:")
        old_arg, old_entity = resolve_literal_argument(
            conn, user_id=7, role="new", literal="Japanese food"
        )
        value_arg, value_entity = resolve_literal_argument(
            conn, user_id=7, role="value", literal="Japanese food"
        )

        self.assertIsNotNone(old_entity)
        self.assertIsNotNone(value_entity)
        self.assertEqual(old_entity.entity_id, value_entity.entity_id)
        self.assertEqual(old_entity.identity_key, value_entity.identity_key)
        self.assertEqual(old_arg.entity_id, value_arg.entity_id)


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


class SchemaMigrationTests(unittest.TestCase):
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
            for name in (
                "memory_entities",
                "memory_entity_aliases",
                "memory_mention_links",
                "memory_assertions",
                "memory_beliefs",
                "memory_belief_revisions",
                "memory_belief_heads",
                "memory_belief_support",
                "memory_resolution_verdicts",
                "memory_entity_resolution_events",
                "memory_entity_alias_equivalences",
            ):
                self.assertIn(name, tables)


class UtilityTests(unittest.TestCase):
    def test_correction_and_provisional_are_deferred(self) -> None:
        klass, reasons = classify_utility(
            polarity="positive",
            epistemic={"mode": "asserted", "speaker_commitment": "certain"},
            has_provisional_identity=False,
            is_correction=True,
        )
        self.assertEqual(klass, "deferred")
        self.assertIn("correction_deferred", reasons)

        klass, reasons = classify_utility(
            polarity="positive",
            epistemic={"mode": "asserted", "speaker_commitment": "certain"},
            has_provisional_identity=True,
            is_correction=False,
        )
        self.assertEqual(klass, "deferred")
        self.assertIn("provisional_identity", reasons)

    def test_certain_is_durable(self) -> None:
        klass, _ = classify_utility(
            polarity="positive",
            epistemic={"mode": "asserted", "speaker_commitment": "certain"},
            has_provisional_identity=False,
            is_correction=False,
        )
        self.assertEqual(klass, "durable")

    def test_soft_epistemic_is_deferred(self) -> None:
        klass, reasons = classify_utility(
            polarity="positive",
            epistemic={"mode": "reported", "speaker_commitment": "possible"},
            has_provisional_identity=False,
            is_correction=False,
        )
        self.assertEqual(klass, "deferred")
        self.assertTrue(reasons)


class BeliefReconcileTests(unittest.TestCase):
    def _assertion(
        self,
        *,
        assertion_id: str,
        polarity: str,
        epistemic: dict | None = None,
        status: str = "active",
    ):
        from memory.resolution.schemas import AssertionRecord, ResolvedArgument

        return AssertionRecord(
            assertion_id=assertion_id,
            candidate_id=f"cand_{assertion_id}",
            proposition_key="prop:likes:self:italian",
            cluster_key="cluster:likes",
            candidate_kind="preference",
            schema_name="likes",
            schema_version="1",
            resolved_arguments=(
                ResolvedArgument(role="subject", value_kind="literal", literal="self"),
                ResolvedArgument(
                    role="value", value_kind="literal", literal="Italian food"
                ),
            ),
            attributes={},
            polarity=polarity,
            epistemic=epistemic
            or {
                "mode": "asserted",
                "speaker_commitment": "certain",
                "scope": "proposition",
            },
            temporal=None,
            observed_at=None,
            status=status,
        )

    def test_polarity_conflict_is_uncertain(self) -> None:
        from memory.resolution.beliefs import reconcile_belief

        pos = self._assertion(assertion_id="a1", polarity="positive")
        neg = self._assertion(assertion_id="a2", polarity="negative")
        rev = reconcile_belief(
            user_id=7,
            assertion=pos,
            supporting_assertions=(pos, neg),
            entity_by_id={},
            is_correction=False,
            prior_head_revision_id=None,
        )
        self.assertEqual(rev.belief_status, "uncertain")
        self.assertEqual(rev.polarity, "unknown")
        self.assertIn("polarity_conflict", rev.utility_reason_codes)
        self.assertEqual(rev.utility_class, "deferred")

    def test_soft_epistemic_is_uncertain(self) -> None:
        from memory.resolution.beliefs import reconcile_belief

        soft = self._assertion(
            assertion_id="a1",
            polarity="positive",
            epistemic={
                "mode": "reported",
                "speaker_commitment": "possible",
                "scope": "proposition",
            },
        )
        rev = reconcile_belief(
            user_id=7,
            assertion=soft,
            supporting_assertions=(soft,),
            entity_by_id={},
            is_correction=False,
            prior_head_revision_id=None,
        )
        self.assertEqual(rev.belief_status, "uncertain")
        self.assertIn("uncertain_claim", rev.utility_reason_codes)
        self.assertEqual(rev.utility_class, "deferred")


class ConfigStageGuardTests(unittest.TestCase):
    def test_pipeline_requires_worker(self) -> None:
        from memory.config import validate_memory_config

        with self.assertRaises(ValueError) as ctx:
            validate_memory_config(
                _config("unused.sqlite", worker_enabled=False, extraction_enabled=True)
            )
        self.assertIn("MEMORY_WORKER_ENABLED", str(ctx.exception))

    def test_resolution_requires_verification(self) -> None:
        from memory.config import validate_memory_config

        with self.assertRaises(ValueError) as ctx:
            validate_memory_config(
                _config(
                    "unused.sqlite",
                    worker_enabled=True,
                    verification_enabled=False,
                    resolution_enabled=True,
                )
            )
        self.assertIn("MEMORY_VERIFICATION_ENABLED", str(ctx.exception))

    def test_graph_requires_resolution(self) -> None:
        from memory.config import validate_memory_config

        with self.assertRaises(ValueError) as ctx:
            validate_memory_config(
                _config(
                    "unused.sqlite",
                    worker_enabled=True,
                    verification_enabled=True,
                    resolution_enabled=False,
                    graph_enabled=True,
                )
            )
        self.assertIn("MEMORY_RESOLUTION_ENABLED", str(ctx.exception))

    def test_policy_mismatch_blocked(self) -> None:
        from memory.config import validate_memory_config

        with self.assertRaises(ValueError) as ctx:
            validate_memory_config(
                _config(
                    "unused.sqlite",
                    worker_enabled=True,
                    verification_enabled=True,
                    resolution_enabled=True,
                    verification_policy_version="verification_policy_v1",
                    required_verification_policy_version="verification_policy_v2",
                )
            )
        self.assertIn("must match", str(ctx.exception))

    def test_shadow_stack_ok(self) -> None:
        from memory.config import validate_memory_config

        validate_memory_config(
            _config(
                "unused.sqlite",
                worker_enabled=True,
                verification_enabled=True,
                resolution_enabled=True,
                graph_enabled=True,
                verification_policy_version=POLICY,
                required_verification_policy_version=POLICY,
            )
        )


class ResolutionPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "memory.sqlite")
        self.config = _config(self.path)
        self.service = MemoryService(config=self.config)
        register_candidate_resolver(
            self.service.registry,
            service=self.service,
            required_verification_policy=POLICY,
        )

    async def asyncTearDown(self) -> None:
        await self.service.stop_worker(grace_seconds=0.2)
        self.tmp.cleanup()

    def _seed_ready_preference(self, *, user_id: int = 7, message_id: int = 1):
        text = "I like Italian food."
        ingest = self.service.register_source(
            SourceInput(
                user_id=user_id,
                source_type="chat_message",
                source_ref=f"chat_message_id:{message_id}",
                authority_class="user_direct_statement",
                content_hash=content_hash_from_text(text),
                occurred_at=datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc),
                pointer=EvidencePointer(
                    pointer_version=1,
                    kind="chat_message",
                    source_version_id="pending",
                    location={"chat_message_id": message_id},
                ),
            )
        )
        pointer = EvidencePointer(
            pointer_version=1,
            kind="chat_message",
            source_version_id=ingest.source_version_id,
            location={"chat_message_id": message_id},
        )
        self.service.segments.insert_segments(
            (
                SegmentInput(
                    source_version_id=ingest.source_version_id,
                    segment_type="chat_text",
                    ordinal=0,
                    text=text,
                    pointer=pointer,
                    normalizer_name="chat_text_normalizer",
                    normalizer_version="1",
                    input_hash=content_hash_from_text(text),
                ),
            ),
            user_id=user_id,
            lineage_store=self.service.lineage,
        )
        segment = self.service.segments.list_for_source_version(
            ingest.source_version_id, user_id=user_id
        )[0]
        job = self.service.jobs.enqueue(
            user_id,
            ingest.source_version_id,
            JobRequest(
                stage="candidate_extract",
                processor_name="seed_extractor",
                processor_version="1",
                prompt_version="seed",
                model_profile="fake",
                input_hash=f"seed-{message_id}",
                config_hash="seed",
            ),
        )
        run_id = f"mrun_seed_{message_id}"
        now = utc_now_iso()
        with self.service.db.transaction() as conn:
            conn.execute(
                """
                UPDATE memory_jobs
                SET status='done'
                WHERE job_id=?
                """,
                (job.job_id,),
            )
            conn.execute(
                """
                INSERT INTO memory_processor_runs(
                    run_id, job_id, user_id, processor_name, processor_version,
                    prompt_version, model_profile, started_at, completed_at,
                    outcome, input_hash, output_hash
                ) VALUES (?, ?, ?, 'seed_extractor', '1', 'seed', 'fake', ?, ?, 'completed', ?, ?)
                """,
                (run_id, job.job_id, user_id, now, now, f"seed-{message_id}", "out"),
            )
            self.service.candidates.insert_in_txn(
                conn,
                (
                    CandidateInput(
                        local_ref="c1",
                        segment_id=segment.segment_id,
                        kind="preference",
                        schema_name="likes",
                        schema_version="1",
                        arguments=(
                            CandidateArgument(role="subject", literal="self", has_literal=True),
                            CandidateArgument(
                                role="value", literal="Italian food", has_literal=True
                            ),
                        ),
                        attributes={},
                        polarity=Polarity.POSITIVE.value,
                        epistemic=Epistemic(
                            mode=EpistemicMode.ASSERTED,
                            speaker_commitment=SpeakerCommitment.CERTAIN,
                            scope=EpistemicScope.PROPOSITION,
                        ),
                        temporal=None,
                        status="ready_for_resolution",
                        evidence=(
                            CandidateEvidenceInput(
                                segment_id=segment.segment_id,
                                relation="supports",
                                pointer=EvidencePointer(
                                    pointer_version=1,
                                    kind="chat_span",
                                    source_version_id=ingest.source_version_id,
                                    location={
                                        "chat_message_id": message_id,
                                        "char_start": 0,
                                        "char_end": len(text),
                                    },
                                ),
                                exact_quote=text,
                            ),
                        ),
                        canonical_hint=None,
                        extractor_name="seed",
                        extractor_version="1",
                        prompt_version="seed",
                    ),
                ),
                user_id=user_id,
                extraction_run_id=run_id,
                mention_ids={},
                lineage_store=self.service.lineage,
            )
            # Force ready status (insert uses proposed).
            conn.execute(
                """
                UPDATE memory_claim_candidates
                SET status='ready_for_resolution', acceptance_policy=?
                WHERE extraction_run_id=?
                """,
                (POLICY, run_id),
            )
            cand = conn.execute(
                "SELECT candidate_id FROM memory_claim_candidates WHERE extraction_run_id=?",
                (run_id,),
            ).fetchone()
            candidate_id = str(cand["candidate_id"])
            verdict_set_hash = "vs_seed"
            score_id = make_score_id(
                candidate_id=candidate_id,
                policy_version=POLICY,
                verdict_set_hash=verdict_set_hash,
            )
            conn.execute(
                """
                INSERT INTO memory_candidate_scores(
                    score_id, user_id, candidate_id, policy_version, verdict_set_hash,
                    components_json, route_status, verification_run_id, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'ready_for_resolution', ?, ?, 'active')
                """,
                (
                    score_id,
                    user_id,
                    candidate_id,
                    POLICY,
                    verdict_set_hash,
                    json.dumps({"ok": True}),
                    run_id,
                    now,
                ),
            )
        return ingest, candidate_id, score_id, verdict_set_hash

    async def _wait_done(self, job_id: str) -> JobStatus:
        for _ in range(300):
            job = self.service.jobs.get_job(job_id)
            assert job is not None
            if job.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.DEAD}:
                return job.status
            await asyncio.sleep(0.01)
        self.fail("job did not finish")

    async def test_ready_preference_resolves_root_and_concept(self) -> None:
        ingest, candidate_id, score_id, verdict_set_hash = self._seed_ready_preference()
        request = resolution_job_request(
            candidate_id,
            score_id=score_id,
            verdict_set_hash=verdict_set_hash,
            required_verification_policy=POLICY,
        )
        enqueued = self.service.jobs.enqueue(7, ingest.source_version_id, request)
        await self.service.start_worker()
        status = await self._wait_done(enqueued.job_id)
        with self.service.db.connection() as conn:
            err = conn.execute(
                "SELECT last_error FROM memory_jobs WHERE job_id=?",
                (enqueued.job_id,),
            ).fetchone()["last_error"]
            entities = [
                dict(row)
                for row in conn.execute(
                    "SELECT entity_type, identity_key, status FROM memory_entities"
                ).fetchall()
            ]
            assertions = conn.execute(
                "SELECT status, polarity, schema_name FROM memory_assertions"
            ).fetchall()
            beliefs = conn.execute(
                """
                SELECT r.belief_status, r.utility_class, r.polarity
                FROM memory_belief_revisions r
                JOIN memory_belief_heads h ON h.belief_revision_id = r.belief_revision_id
                """
            ).fetchall()
        self.assertEqual(status, JobStatus.DONE, err)
        types = {item["entity_type"] for item in entities}
        self.assertIn("user", types)
        self.assertIn("concept", types)
        self.assertEqual(len(assertions), 1)
        self.assertEqual(assertions[0]["status"], "active")
        self.assertEqual(assertions[0]["schema_name"], "likes")
        self.assertEqual(len(beliefs), 1)
        self.assertEqual(beliefs[0]["belief_status"], "active")
        self.assertEqual(beliefs[0]["utility_class"], "durable")

    async def test_non_ready_not_schedulable(self) -> None:
        ingest, candidate_id, score_id, verdict_set_hash = self._seed_ready_preference()
        with self.service.db.transaction() as conn:
            conn.execute(
                "UPDATE memory_claim_candidates SET status='proposed' WHERE candidate_id=?",
                (candidate_id,),
            )
        rows = self.service.resolution.list_schedulable(
            required_verification_policy=POLICY, limit=10
        )
        self.assertEqual(rows, [])
        _ = ingest, score_id, verdict_set_hash

    async def test_scheduler_idempotent(self) -> None:
        ingest, candidate_id, score_id, verdict_set_hash = self._seed_ready_preference()
        scheduler = ResolutionScheduler(
            service=self.service,
            required_verification_policy=POLICY,
            interval_seconds=1.0,
            batch_size=10,
        )
        first = scheduler.scan_once()
        second = scheduler.scan_once()
        self.assertEqual(first.jobs_created, 1)
        self.assertEqual(second.jobs_created, 0)
        _ = ingest, candidate_id, score_id, verdict_set_hash

    async def test_person_names_do_not_merge(self) -> None:
        """Two mentions with same surface create distinct provisional entities."""
        text = "Alice met Alice."
        ingest = self.service.register_source(
            SourceInput(
                user_id=7,
                source_type="chat_message",
                source_ref="chat_message_id:99",
                authority_class="user_direct_statement",
                content_hash=content_hash_from_text(text),
                pointer=EvidencePointer(
                    pointer_version=1,
                    kind="chat_message",
                    source_version_id="pending",
                    location={"chat_message_id": 99},
                ),
            )
        )
        pointer = EvidencePointer(
            pointer_version=1,
            kind="chat_message",
            source_version_id=ingest.source_version_id,
            location={"chat_message_id": 99},
        )
        self.service.segments.insert_segments(
            (
                SegmentInput(
                    source_version_id=ingest.source_version_id,
                    segment_type="chat_text",
                    ordinal=0,
                    text=text,
                    pointer=pointer,
                    normalizer_name="chat_text_normalizer",
                    normalizer_version="1",
                    input_hash=content_hash_from_text(text),
                ),
            ),
            user_id=7,
            lineage_store=self.service.lineage,
        )
        segment = self.service.segments.list_for_source_version(
            ingest.source_version_id, user_id=7
        )[0]
        job = self.service.jobs.enqueue(
            7,
            ingest.source_version_id,
            JobRequest(
                stage="candidate_extract",
                processor_name="seed_extractor",
                processor_version="1",
                prompt_version="seed",
                model_profile="fake",
                input_hash="seed-person",
                config_hash="seed",
            ),
        )
        run_id = "mrun_seed_person"
        now = utc_now_iso()
        with self.service.db.transaction() as conn:
            conn.execute(
                "UPDATE memory_jobs SET status='done' WHERE job_id=?",
                (job.job_id,),
            )
            conn.execute(
                """
                INSERT INTO memory_processor_runs(
                    run_id, job_id, user_id, processor_name, processor_version,
                    prompt_version, model_profile, started_at, completed_at,
                    outcome, input_hash, output_hash
                ) VALUES (?, ?, 7, 'seed_extractor', '1', 'seed', 'fake', ?, ?, 'completed', 'seed-person', 'out')
                """,
                (run_id, job.job_id, now, now),
            )
            mention_ids = self.service.mentions.insert_in_txn(
                conn,
                (
                    MentionInput(
                        local_ref="a1",
                        segment_id=segment.segment_id,
                        mention_type="person",
                        surface_text="Alice",
                        normalized_hint="Alice",
                        pointer=EvidencePointer(
                            pointer_version=1,
                            kind="chat_span",
                            source_version_id=ingest.source_version_id,
                            location={
                                "chat_message_id": 99,
                                "char_start": 0,
                                "char_end": 5,
                            },
                        ),
                        extractor_name="seed",
                        extractor_version="1",
                        prompt_version="seed",
                    ),
                    MentionInput(
                        local_ref="a2",
                        segment_id=segment.segment_id,
                        mention_type="person",
                        surface_text="Alice",
                        normalized_hint="Alice",
                        pointer=EvidencePointer(
                            pointer_version=1,
                            kind="chat_span",
                            source_version_id=ingest.source_version_id,
                            location={
                                "chat_message_id": 99,
                                "char_start": 10,
                                "char_end": 15,
                            },
                        ),
                        extractor_name="seed",
                        extractor_version="1",
                        prompt_version="seed",
                    ),
                ),
                user_id=7,
                lineage_store=self.service.lineage,
            )
            self.service.candidates.insert_in_txn(
                conn,
                (
                    CandidateInput(
                        local_ref="c_meet",
                        segment_id=segment.segment_id,
                        kind="relation",
                        schema_name="met",
                        schema_version="1",
                        arguments=(
                            CandidateArgument(role="person_a", mention_ref="a1"),
                            CandidateArgument(role="person_b", mention_ref="a2"),
                        ),
                        attributes={},
                        polarity=Polarity.POSITIVE.value,
                        epistemic=Epistemic(
                            mode=EpistemicMode.ASSERTED,
                            speaker_commitment=SpeakerCommitment.CERTAIN,
                            scope=EpistemicScope.PROPOSITION,
                        ),
                        temporal=None,
                        status=CandidateStatus.PROPOSED.value,
                        evidence=(
                            CandidateEvidenceInput(
                                segment_id=segment.segment_id,
                                relation="supports",
                                pointer=EvidencePointer(
                                    pointer_version=1,
                                    kind="chat_span",
                                    source_version_id=ingest.source_version_id,
                                    location={
                                        "chat_message_id": 99,
                                        "char_start": 0,
                                        "char_end": len(text),
                                    },
                                ),
                                exact_quote=text,
                            ),
                        ),
                        canonical_hint=None,
                        extractor_name="seed",
                        extractor_version="1",
                        prompt_version="seed",
                    ),
                ),
                user_id=7,
                extraction_run_id=run_id,
                mention_ids=mention_ids,
                lineage_store=self.service.lineage,
            )
            conn.execute(
                """
                UPDATE memory_claim_candidates
                SET status='ready_for_resolution', acceptance_policy=?
                WHERE extraction_run_id=?
                """,
                (POLICY, run_id),
            )
            candidate_id = str(
                conn.execute(
                    "SELECT candidate_id FROM memory_claim_candidates WHERE extraction_run_id=?",
                    (run_id,),
                ).fetchone()["candidate_id"]
            )
            verdict_set_hash = "vs_person"
            score_id = make_score_id(
                candidate_id=candidate_id,
                policy_version=POLICY,
                verdict_set_hash=verdict_set_hash,
            )
            conn.execute(
                """
                INSERT INTO memory_candidate_scores(
                    score_id, user_id, candidate_id, policy_version, verdict_set_hash,
                    components_json, route_status, verification_run_id, created_at, status
                ) VALUES (?, 7, ?, ?, ?, '{}', 'ready_for_resolution', ?, ?, 'active')
                """,
                (score_id, candidate_id, POLICY, verdict_set_hash, run_id, now),
            )

        request = resolution_job_request(
            candidate_id,
            score_id=score_id,
            verdict_set_hash=verdict_set_hash,
            required_verification_policy=POLICY,
        )
        enqueued = self.service.jobs.enqueue(7, ingest.source_version_id, request)
        await self.service.start_worker()
        status = await self._wait_done(enqueued.job_id)
        with self.service.db.connection() as conn:
            err = conn.execute(
                "SELECT last_error FROM memory_jobs WHERE job_id=?",
                (enqueued.job_id,),
            ).fetchone()["last_error"]
            person_entities = conn.execute(
                "SELECT entity_id FROM memory_entities WHERE entity_type='person'"
            ).fetchall()
            belief = conn.execute(
                "SELECT utility_class FROM memory_belief_revisions"
            ).fetchone()
        self.assertEqual(status, JobStatus.DONE, err)
        self.assertEqual(len(person_entities), 2)
        self.assertEqual(belief["utility_class"], "deferred")

    async def test_idempotent_reresolve(self) -> None:
        ingest, candidate_id, score_id, verdict_set_hash = self._seed_ready_preference()
        request = resolution_job_request(
            candidate_id,
            score_id=score_id,
            verdict_set_hash=verdict_set_hash,
            required_verification_policy=POLICY,
        )
        await self.service.start_worker()
        j1 = self.service.jobs.enqueue(7, ingest.source_version_id, request)
        self.assertEqual(await self._wait_done(j1.job_id), JobStatus.DONE)
        # Second enqueue is same job id (idempotent enqueue).
        j2 = self.service.jobs.enqueue(7, ingest.source_version_id, request)
        self.assertEqual(j1.job_id, j2.job_id)
        with self.service.db.connection() as conn:
            count = int(
                conn.execute("SELECT COUNT(*) AS c FROM memory_assertions").fetchone()["c"]
            )
        self.assertEqual(count, 1)

    def test_lookup_key_casefold(self) -> None:
        self.assertEqual(lookup_key("Italian Food"), lookup_key("italian food"))

    def test_input_hash_stable(self) -> None:
        a = resolution_input_hash(
            "mcand_x",
            score_id="mscore_y",
            verdict_set_hash="vs",
            required_verification_policy=POLICY,
        )
        b = resolution_input_hash(
            "mcand_x",
            score_id="mscore_y",
            verdict_set_hash="vs",
            required_verification_policy=POLICY,
        )
        self.assertEqual(a, b)
        self.assertEqual(ASSERTION_SCHEMA_VERSION, "1")
        self.assertEqual(RESOLVER_VERSION, "2")


class _FakeLinkModel:
    model_profile = "extraction"

    def __init__(self, verdict: str = "supported", *, profile: str = "extraction") -> None:
        self.verdict = verdict
        self.model_profile = profile
        self.calls = 0

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = "resolution_link",
    ) -> str:
        _ = messages, structured_schema
        self.calls += 1
        return json.dumps(
            {
                "schema_version": "1",
                "verdict": self.verdict,
                "scope_errors": [],
                "ambiguities": [],
                "missing_context": [],
                "corrected_resolution": None,
            }
        )


class LinkCriticTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "memory.sqlite")
        self.config = _config(self.path)
        self.service = MemoryService(config=self.config)

    async def asyncTearDown(self) -> None:
        await self.service.stop_worker(grace_seconds=0.2)
        self.tmp.cleanup()

    async def _wait_done(self, job_id: str) -> JobStatus:
        for _ in range(300):
            job = self.service.jobs.get_job(job_id)
            assert job is not None
            if job.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.DEAD}:
                return job.status
            await asyncio.sleep(0.01)
        self.fail("job did not finish")

    async def test_exact_alias_reuse_requires_critics(self) -> None:
        from memory.ids import make_alias_id, make_entity_id
        from memory.resolution.schemas import RESOLVER_VERSION
        from memory.resolution.parser import parse_link_verdict

        parsed = parse_link_verdict(
            {
                "schema_version": "1",
                "verdict": "supported",
                "scope_errors": [],
                "ambiguities": [],
                "missing_context": [],
                "corrected_resolution": None,
            }
        )
        self.assertEqual(parsed.verdict, "supported")

        # Seed existing org entity + alias.
        now = utc_now_iso()
        entity_id = make_entity_id(
            user_id=7,
            entity_type="organization",
            identity_key="mention:seed",
            resolver_version=RESOLVER_VERSION,
        )
        with self.service.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO memory_entities(
                    entity_id, user_id, entity_type, identity_key, canonical_label,
                    status, resolver_version, created_at, updated_at
                ) VALUES (?, 7, 'organization', 'mention:seed', 'Acme', 'active', ?, ?, ?)
                """,
                (entity_id, RESOLVER_VERSION, now, now),
            )
            alias_id = make_alias_id(
                user_id=7,
                entity_id=entity_id,
                normalized_alias="acme",
                source_mention_id=None,
            )
            conn.execute(
                """
                INSERT INTO memory_entity_aliases(
                    alias_id, user_id, entity_id, source_mention_id, alias,
                    normalized_alias, language, evidence_pointer_json, status, created_at
                ) VALUES (?, 7, ?, NULL, 'Acme', 'acme', NULL, NULL, 'active', ?)
                """,
                (alias_id, entity_id, now),
            )

        text = "I work at Acme."
        ingest = self.service.register_source(
            SourceInput(
                user_id=7,
                source_type="chat_message",
                source_ref="chat_message_id:200",
                authority_class="user_direct_statement",
                content_hash=content_hash_from_text(text),
                pointer=EvidencePointer(
                    pointer_version=1,
                    kind="chat_message",
                    source_version_id="pending",
                    location={"chat_message_id": 200},
                ),
            )
        )
        pointer = EvidencePointer(
            pointer_version=1,
            kind="chat_message",
            source_version_id=ingest.source_version_id,
            location={"chat_message_id": 200},
        )
        self.service.segments.insert_segments(
            (
                SegmentInput(
                    source_version_id=ingest.source_version_id,
                    segment_type="chat_text",
                    ordinal=0,
                    text=text,
                    pointer=pointer,
                    normalizer_name="chat_text_normalizer",
                    normalizer_version="1",
                    input_hash=content_hash_from_text(text),
                ),
            ),
            user_id=7,
            lineage_store=self.service.lineage,
        )
        segment = self.service.segments.list_for_source_version(
            ingest.source_version_id, user_id=7
        )[0]
        job = self.service.jobs.enqueue(
            7,
            ingest.source_version_id,
            JobRequest(
                stage="candidate_extract",
                processor_name="seed_extractor",
                processor_version="1",
                prompt_version="seed",
                model_profile="fake",
                input_hash="seed-org",
                config_hash="seed",
            ),
        )
        run_id = "mrun_seed_org"
        support = _FakeLinkModel("supported", profile="extraction")
        adversarial = _FakeLinkModel("supported", profile="agent")
        register_candidate_resolver(
            self.service.registry,
            service=self.service,
            required_verification_policy=POLICY,
            support_model=support,
            adversarial_model=adversarial,
            support_profile="extraction",
            adversarial_profile="agent",
        )
        with self.service.db.transaction() as conn:
            conn.execute("UPDATE memory_jobs SET status='done' WHERE job_id=?", (job.job_id,))
            conn.execute(
                """
                INSERT INTO memory_processor_runs(
                    run_id, job_id, user_id, processor_name, processor_version,
                    prompt_version, model_profile, started_at, completed_at,
                    outcome, input_hash, output_hash
                ) VALUES (?, ?, 7, 'seed_extractor', '1', 'seed', 'fake', ?, ?, 'completed', 'seed-org', 'out')
                """,
                (run_id, job.job_id, now, now),
            )
            mention_ids = self.service.mentions.insert_in_txn(
                conn,
                (
                    MentionInput(
                        local_ref="acme",
                        segment_id=segment.segment_id,
                        mention_type="organization",
                        surface_text="Acme",
                        normalized_hint="Acme",
                        pointer=EvidencePointer(
                            pointer_version=1,
                            kind="chat_span",
                            source_version_id=ingest.source_version_id,
                            location={
                                "chat_message_id": 200,
                                "char_start": 10,
                                "char_end": 14,
                            },
                        ),
                        extractor_name="seed",
                        extractor_version="1",
                        prompt_version="seed",
                    ),
                ),
                user_id=7,
                lineage_store=self.service.lineage,
            )
            self.service.candidates.insert_in_txn(
                conn,
                (
                    CandidateInput(
                        local_ref="c_org",
                        segment_id=segment.segment_id,
                        kind="relation",
                        schema_name="works_at",
                        schema_version="1",
                        arguments=(
                            CandidateArgument(role="subject", literal="self", has_literal=True),
                            CandidateArgument(role="organization", mention_ref="acme"),
                        ),
                        attributes={},
                        polarity=Polarity.POSITIVE.value,
                        epistemic=Epistemic(
                            mode=EpistemicMode.ASSERTED,
                            speaker_commitment=SpeakerCommitment.CERTAIN,
                            scope=EpistemicScope.PROPOSITION,
                        ),
                        temporal=None,
                        status=CandidateStatus.PROPOSED.value,
                        evidence=(
                            CandidateEvidenceInput(
                                segment_id=segment.segment_id,
                                relation="supports",
                                pointer=EvidencePointer(
                                    pointer_version=1,
                                    kind="chat_span",
                                    source_version_id=ingest.source_version_id,
                                    location={
                                        "chat_message_id": 200,
                                        "char_start": 0,
                                        "char_end": len(text),
                                    },
                                ),
                                exact_quote=text,
                            ),
                        ),
                        canonical_hint=None,
                        extractor_name="seed",
                        extractor_version="1",
                        prompt_version="seed",
                    ),
                ),
                user_id=7,
                extraction_run_id=run_id,
                mention_ids=mention_ids,
                lineage_store=self.service.lineage,
            )
            conn.execute(
                """
                UPDATE memory_claim_candidates
                SET status='ready_for_resolution', acceptance_policy=?
                WHERE extraction_run_id=?
                """,
                (POLICY, run_id),
            )
            candidate_id = str(
                conn.execute(
                    "SELECT candidate_id FROM memory_claim_candidates WHERE extraction_run_id=?",
                    (run_id,),
                ).fetchone()["candidate_id"]
            )
            verdict_set_hash = "vs_org"
            score_id = make_score_id(
                candidate_id=candidate_id,
                policy_version=POLICY,
                verdict_set_hash=verdict_set_hash,
            )
            conn.execute(
                """
                INSERT INTO memory_candidate_scores(
                    score_id, user_id, candidate_id, policy_version, verdict_set_hash,
                    components_json, route_status, verification_run_id, created_at, status
                ) VALUES (?, 7, ?, ?, ?, '{}', 'ready_for_resolution', ?, ?, 'active')
                """,
                (score_id, candidate_id, POLICY, verdict_set_hash, run_id, now),
            )

        request = resolution_job_request(
            candidate_id,
            score_id=score_id,
            verdict_set_hash=verdict_set_hash,
            required_verification_policy=POLICY,
            support_profile="extraction",
            adversarial_profile="agent",
        )
        enqueued = self.service.jobs.enqueue(7, ingest.source_version_id, request)
        await self.service.start_worker()
        status = await self._wait_done(enqueued.job_id)
        with self.service.db.connection() as conn:
            err = conn.execute(
                "SELECT last_error FROM memory_jobs WHERE job_id=?",
                (enqueued.job_id,),
            ).fetchone()["last_error"]
            link = conn.execute(
                "SELECT entity_id, decision FROM memory_mention_links"
            ).fetchone()
            critic_rows = conn.execute(
                "SELECT role, verdict FROM memory_resolution_verdicts ORDER BY role"
            ).fetchall()
        self.assertEqual(status, JobStatus.DONE, err)
        self.assertEqual(str(link["entity_id"]), entity_id)
        self.assertEqual(str(link["decision"]), "exact_alias_verified")
        self.assertEqual(support.calls, 1)
        self.assertEqual(adversarial.calls, 1)
        self.assertEqual(
            [(str(r["role"]), str(r["verdict"])) for r in critic_rows],
            [("adversarial", "supported"), ("support", "supported")],
        )

    async def test_critic_veto_keeps_provisional(self) -> None:
        from memory.ids import make_alias_id, make_entity_id
        from memory.resolution.schemas import RESOLVER_VERSION

        now = utc_now_iso()
        entity_id = make_entity_id(
            user_id=7,
            entity_type="organization",
            identity_key="mention:seed2",
            resolver_version=RESOLVER_VERSION,
        )
        with self.service.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO memory_entities(
                    entity_id, user_id, entity_type, identity_key, canonical_label,
                    status, resolver_version, created_at, updated_at
                ) VALUES (?, 7, 'organization', 'mention:seed2', 'Acme', 'active', ?, ?, ?)
                """,
                (entity_id, RESOLVER_VERSION, now, now),
            )
            alias_id = make_alias_id(
                user_id=7,
                entity_id=entity_id,
                normalized_alias="acme",
                source_mention_id=None,
            )
            conn.execute(
                """
                INSERT INTO memory_entity_aliases(
                    alias_id, user_id, entity_id, source_mention_id, alias,
                    normalized_alias, language, evidence_pointer_json, status, created_at
                ) VALUES (?, 7, ?, NULL, 'Acme', 'acme', NULL, NULL, 'active', ?)
                """,
                (alias_id, entity_id, now),
            )

        text = "Acme hired me."
        ingest = self.service.register_source(
            SourceInput(
                user_id=7,
                source_type="chat_message",
                source_ref="chat_message_id:201",
                authority_class="user_direct_statement",
                content_hash=content_hash_from_text(text),
                pointer=EvidencePointer(
                    pointer_version=1,
                    kind="chat_message",
                    source_version_id="pending",
                    location={"chat_message_id": 201},
                ),
            )
        )
        pointer = EvidencePointer(
            pointer_version=1,
            kind="chat_message",
            source_version_id=ingest.source_version_id,
            location={"chat_message_id": 201},
        )
        self.service.segments.insert_segments(
            (
                SegmentInput(
                    source_version_id=ingest.source_version_id,
                    segment_type="chat_text",
                    ordinal=0,
                    text=text,
                    pointer=pointer,
                    normalizer_name="chat_text_normalizer",
                    normalizer_version="1",
                    input_hash=content_hash_from_text(text),
                ),
            ),
            user_id=7,
            lineage_store=self.service.lineage,
        )
        segment = self.service.segments.list_for_source_version(
            ingest.source_version_id, user_id=7
        )[0]
        job = self.service.jobs.enqueue(
            7,
            ingest.source_version_id,
            JobRequest(
                stage="candidate_extract",
                processor_name="seed_extractor",
                processor_version="1",
                prompt_version="seed",
                model_profile="fake",
                input_hash="seed-org-veto",
                config_hash="seed",
            ),
        )
        run_id = "mrun_seed_org_veto"
        support = _FakeLinkModel("supported", profile="extraction")
        adversarial = _FakeLinkModel("contradicted", profile="agent")
        register_candidate_resolver(
            self.service.registry,
            service=self.service,
            required_verification_policy=POLICY,
            support_model=support,
            adversarial_model=adversarial,
        )
        with self.service.db.transaction() as conn:
            conn.execute("UPDATE memory_jobs SET status='done' WHERE job_id=?", (job.job_id,))
            conn.execute(
                """
                INSERT INTO memory_processor_runs(
                    run_id, job_id, user_id, processor_name, processor_version,
                    prompt_version, model_profile, started_at, completed_at,
                    outcome, input_hash, output_hash
                ) VALUES (?, ?, 7, 'seed_extractor', '1', 'seed', 'fake', ?, ?, 'completed', 'seed-org-veto', 'out')
                """,
                (run_id, job.job_id, now, now),
            )
            mention_ids = self.service.mentions.insert_in_txn(
                conn,
                (
                    MentionInput(
                        local_ref="acme",
                        segment_id=segment.segment_id,
                        mention_type="organization",
                        surface_text="Acme",
                        normalized_hint="Acme",
                        pointer=EvidencePointer(
                            pointer_version=1,
                            kind="chat_span",
                            source_version_id=ingest.source_version_id,
                            location={
                                "chat_message_id": 201,
                                "char_start": 0,
                                "char_end": 4,
                            },
                        ),
                        extractor_name="seed",
                        extractor_version="1",
                        prompt_version="seed",
                    ),
                ),
                user_id=7,
                lineage_store=self.service.lineage,
            )
            self.service.candidates.insert_in_txn(
                conn,
                (
                    CandidateInput(
                        local_ref="c_org2",
                        segment_id=segment.segment_id,
                        kind="relation",
                        schema_name="hired_by",
                        schema_version="1",
                        arguments=(
                            CandidateArgument(role="organization", mention_ref="acme"),
                            CandidateArgument(role="subject", literal="self", has_literal=True),
                        ),
                        attributes={},
                        polarity=Polarity.POSITIVE.value,
                        epistemic=Epistemic(
                            mode=EpistemicMode.ASSERTED,
                            speaker_commitment=SpeakerCommitment.CERTAIN,
                            scope=EpistemicScope.PROPOSITION,
                        ),
                        temporal=None,
                        status=CandidateStatus.PROPOSED.value,
                        evidence=(
                            CandidateEvidenceInput(
                                segment_id=segment.segment_id,
                                relation="supports",
                                pointer=EvidencePointer(
                                    pointer_version=1,
                                    kind="chat_span",
                                    source_version_id=ingest.source_version_id,
                                    location={
                                        "chat_message_id": 201,
                                        "char_start": 0,
                                        "char_end": len(text),
                                    },
                                ),
                                exact_quote=text,
                            ),
                        ),
                        canonical_hint=None,
                        extractor_name="seed",
                        extractor_version="1",
                        prompt_version="seed",
                    ),
                ),
                user_id=7,
                extraction_run_id=run_id,
                mention_ids=mention_ids,
                lineage_store=self.service.lineage,
            )
            conn.execute(
                """
                UPDATE memory_claim_candidates
                SET status='ready_for_resolution', acceptance_policy=?
                WHERE extraction_run_id=?
                """,
                (POLICY, run_id),
            )
            candidate_id = str(
                conn.execute(
                    "SELECT candidate_id FROM memory_claim_candidates WHERE extraction_run_id=?",
                    (run_id,),
                ).fetchone()["candidate_id"]
            )
            verdict_set_hash = "vs_org_veto"
            score_id = make_score_id(
                candidate_id=candidate_id,
                policy_version=POLICY,
                verdict_set_hash=verdict_set_hash,
            )
            conn.execute(
                """
                INSERT INTO memory_candidate_scores(
                    score_id, user_id, candidate_id, policy_version, verdict_set_hash,
                    components_json, route_status, verification_run_id, created_at, status
                ) VALUES (?, 7, ?, ?, ?, '{}', 'ready_for_resolution', ?, ?, 'active')
                """,
                (score_id, candidate_id, POLICY, verdict_set_hash, run_id, now),
            )

        request = resolution_job_request(
            candidate_id,
            score_id=score_id,
            verdict_set_hash=verdict_set_hash,
            required_verification_policy=POLICY,
        )
        enqueued = self.service.jobs.enqueue(7, ingest.source_version_id, request)
        await self.service.start_worker()
        status = await self._wait_done(enqueued.job_id)
        with self.service.db.connection() as conn:
            err = conn.execute(
                "SELECT last_error FROM memory_jobs WHERE job_id=?",
                (enqueued.job_id,),
            ).fetchone()["last_error"]
            link = conn.execute(
                "SELECT entity_id, decision FROM memory_mention_links"
            ).fetchone()
        self.assertEqual(status, JobStatus.DONE, err)
        self.assertNotEqual(str(link["entity_id"]), entity_id)
        self.assertEqual(str(link["decision"]), "provisional_new")


class ResolutionInvalidationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "memory.sqlite")
        self.config = _config(self.path)
        self.service = MemoryService(config=self.config)
        register_candidate_resolver(
            self.service.registry,
            service=self.service,
            required_verification_policy=POLICY,
        )

    async def asyncTearDown(self) -> None:
        await self.service.stop_worker(grace_seconds=0.2)
        self.tmp.cleanup()

    async def _resolve_preference(self):
        # Reuse pipeline helper machinery via a nested harness.
        harness = ResolutionPipelineTests()
        harness.service = self.service
        ingest, candidate_id, score_id, verdict_set_hash = harness._seed_ready_preference()
        request = resolution_job_request(
            candidate_id,
            score_id=score_id,
            verdict_set_hash=verdict_set_hash,
            required_verification_policy=POLICY,
        )
        enqueued = self.service.jobs.enqueue(7, ingest.source_version_id, request)
        await self.service.start_worker()
        for _ in range(300):
            job = self.service.jobs.get_job(enqueued.job_id)
            assert job is not None
            if job.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.DEAD}:
                break
            await asyncio.sleep(0.01)
        else:
            self.fail("job did not finish")
        self.assertEqual(job.status, JobStatus.DONE)
        return ingest, candidate_id

    async def test_source_invalidate_clears_assertion_and_belief(self) -> None:
        ingest, candidate_id = await self._resolve_preference()
        with self.service.db.connection() as conn:
            before = conn.execute(
                "SELECT status FROM memory_assertions WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            root_before = conn.execute(
                """
                SELECT entity_id, status FROM memory_entities
                WHERE entity_type='user' AND identity_key='root_user'
                """
            ).fetchone()
        self.assertEqual(before["status"], "active")
        self.assertEqual(root_before["status"], "active")

        result = self.service.sources.invalidate(
            ingest.source_id, user_id=7, reason="forget"
        )
        self.assertGreaterEqual(result.inactive_descendant_count, 1)

        with self.service.db.connection() as conn:
            assertion = conn.execute(
                "SELECT status FROM memory_assertions WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            belief = conn.execute(
                """
                SELECT r.belief_status, r.utility_class
                FROM memory_belief_revisions r
                JOIN memory_belief_heads h ON h.belief_revision_id = r.belief_revision_id
                """
            ).fetchone()
            root = conn.execute(
                """
                SELECT status FROM memory_entities
                WHERE entity_type='user' AND identity_key='root_user'
                """
            ).fetchone()
            links = [
                str(row["status"])
                for row in conn.execute("SELECT status FROM memory_mention_links").fetchall()
            ]
        self.assertEqual(assertion["status"], "invalidated")
        self.assertEqual(belief["belief_status"], "unsupported")
        self.assertEqual(belief["utility_class"], "deferred")
        self.assertEqual(root["status"], "active")
        self.assertTrue(all(status == "invalidated" for status in links))

    async def test_rebuild_enqueues_after_assertion_invalidation(self) -> None:
        from memory.resolution.rebuild import rebuild_ready_candidates

        ingest, candidate_id = await self._resolve_preference()
        self.assertEqual(
            self.service.resolution.list_schedulable(
                required_verification_policy=POLICY, limit=10
            ),
            [],
        )
        with self.service.db.transaction() as conn:
            conn.execute(
                """
                UPDATE memory_assertions
                SET status='invalidated'
                WHERE candidate_id=? AND user_id=7
                """,
                (candidate_id,),
            )
        rows = self.service.resolution.list_schedulable(
            required_verification_policy=POLICY, limit=10
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0]["candidate_id"]), candidate_id)

        rebuilt = rebuild_ready_candidates(
            self.service,
            user_id=7,
            limit=10,
            required_verification_policy=POLICY,
        )
        self.assertEqual(rebuilt.candidates_seen, 1)
        self.assertEqual(rebuilt.jobs_created, 1)
        again = rebuild_ready_candidates(
            self.service,
            user_id=7,
            limit=10,
            required_verification_policy=POLICY,
        )
        self.assertEqual(again.jobs_created, 0)
        _ = ingest

    def _seed_ready_correction(
        self,
        *,
        prior_segment_id: str,
        prior_source_version_id: str,
        user_id: int = 7,
        message_id: int = 2,
    ):
        text = "Actually I prefer German food."
        ingest = self.service.register_source(
            SourceInput(
                user_id=user_id,
                source_type="chat_message",
                source_ref=f"chat_message_id:{message_id}",
                authority_class="user_direct_statement",
                content_hash=content_hash_from_text(text),
                occurred_at=datetime(2026, 7, 12, 12, 5, tzinfo=timezone.utc),
                pointer=EvidencePointer(
                    pointer_version=1,
                    kind="chat_message",
                    source_version_id="pending",
                    location={"chat_message_id": message_id},
                ),
            )
        )
        pointer = EvidencePointer(
            pointer_version=1,
            kind="chat_message",
            source_version_id=ingest.source_version_id,
            location={"chat_message_id": message_id},
        )
        self.service.segments.insert_segments(
            (
                SegmentInput(
                    source_version_id=ingest.source_version_id,
                    segment_type="chat_text",
                    ordinal=0,
                    text=text,
                    pointer=pointer,
                    normalizer_name="chat_text_normalizer",
                    normalizer_version="1",
                    input_hash=content_hash_from_text(text),
                ),
            ),
            user_id=user_id,
            lineage_store=self.service.lineage,
        )
        segment = self.service.segments.list_for_source_version(
            ingest.source_version_id, user_id=user_id
        )[0]
        job = self.service.jobs.enqueue(
            user_id,
            ingest.source_version_id,
            JobRequest(
                stage="candidate_extract",
                processor_name="seed_extractor",
                processor_version="1",
                prompt_version="seed",
                model_profile="fake",
                input_hash=f"seed-{message_id}",
                config_hash="seed",
            ),
        )
        run_id = f"mrun_seed_{message_id}"
        now = utc_now_iso()
        with self.service.db.transaction() as conn:
            conn.execute(
                "UPDATE memory_jobs SET status='done' WHERE job_id=?",
                (job.job_id,),
            )
            conn.execute(
                """
                INSERT INTO memory_processor_runs(
                    run_id, job_id, user_id, processor_name, processor_version,
                    prompt_version, model_profile, started_at, completed_at,
                    outcome, input_hash, output_hash
                ) VALUES (?, ?, ?, 'seed_extractor', '1', 'seed', 'fake', ?, ?, 'completed', ?, ?)
                """,
                (run_id, job.job_id, user_id, now, now, f"seed-{message_id}", "out"),
            )
            self.service.candidates.insert_in_txn(
                conn,
                (
                    CandidateInput(
                        local_ref="c_corr",
                        segment_id=segment.segment_id,
                        kind="correction",
                        schema_name="corrects_preference",
                        schema_version="1",
                        arguments=(
                            CandidateArgument(
                                role="old", literal="Italian food", has_literal=True
                            ),
                            CandidateArgument(
                                role="new", literal="German food", has_literal=True
                            ),
                        ),
                        attributes={},
                        polarity=Polarity.POSITIVE.value,
                        epistemic=Epistemic(
                            mode=EpistemicMode.ASSERTED,
                            speaker_commitment=SpeakerCommitment.CERTAIN,
                            scope=EpistemicScope.PROPOSITION,
                        ),
                        temporal=None,
                        status="ready_for_resolution",
                        evidence=(
                            CandidateEvidenceInput(
                                segment_id=segment.segment_id,
                                relation="supports",
                                pointer=EvidencePointer(
                                    pointer_version=1,
                                    kind="chat_span",
                                    source_version_id=ingest.source_version_id,
                                    location={
                                        "chat_message_id": message_id,
                                        "char_start": 0,
                                        "char_end": len(text),
                                    },
                                ),
                                exact_quote=text,
                            ),
                            CandidateEvidenceInput(
                                segment_id=prior_segment_id,
                                relation="supports",
                                pointer=EvidencePointer(
                                    pointer_version=1,
                                    kind="chat_span",
                                    source_version_id=prior_source_version_id,
                                    location={
                                        "chat_message_id": 1,
                                        "char_start": 0,
                                        "char_end": len("I like Italian food."),
                                    },
                                ),
                                exact_quote="I like Italian food.",
                            ),
                        ),
                        canonical_hint=None,
                        extractor_name="seed",
                        extractor_version="1",
                        prompt_version="seed",
                    ),
                ),
                user_id=user_id,
                extraction_run_id=run_id,
                mention_ids={},
                lineage_store=self.service.lineage,
            )
            conn.execute(
                """
                UPDATE memory_claim_candidates
                SET status='ready_for_resolution', acceptance_policy=?
                WHERE extraction_run_id=?
                """,
                (POLICY, run_id),
            )
            cand = conn.execute(
                "SELECT candidate_id FROM memory_claim_candidates WHERE extraction_run_id=?",
                (run_id,),
            ).fetchone()
            candidate_id = str(cand["candidate_id"])
            verdict_set_hash = "vs_seed_corr"
            score_id = make_score_id(
                candidate_id=candidate_id,
                policy_version=POLICY,
                verdict_set_hash=verdict_set_hash,
            )
            conn.execute(
                """
                INSERT INTO memory_candidate_scores(
                    score_id, user_id, candidate_id, policy_version, verdict_set_hash,
                    components_json, route_status, verification_run_id, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'ready_for_resolution', ?, ?, 'active')
                """,
                (
                    score_id,
                    user_id,
                    candidate_id,
                    POLICY,
                    verdict_set_hash,
                    json.dumps({"ok": True}),
                    run_id,
                    now,
                ),
            )
        return ingest, candidate_id, score_id, verdict_set_hash

    async def test_correction_promotes_winner_and_historicalizes_loser(self) -> None:
        harness = ResolutionPipelineTests()
        harness.service = self.service
        ingest1, pref_cand, score1, vs1 = harness._seed_ready_preference()
        segment = self.service.segments.list_for_source_version(
            ingest1.source_version_id, user_id=7
        )[0]
        request1 = resolution_job_request(
            pref_cand,
            score_id=score1,
            verdict_set_hash=vs1,
            required_verification_policy=POLICY,
        )
        job1 = self.service.jobs.enqueue(7, ingest1.source_version_id, request1)
        await self.service.start_worker()
        for _ in range(300):
            job = self.service.jobs.get_job(job1.job_id)
            assert job is not None
            if job.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.DEAD}:
                break
            await asyncio.sleep(0.01)
        else:
            self.fail("preference job did not finish")
        self.assertEqual(job.status, JobStatus.DONE)

        ingest2, corr_cand, score2, vs2 = self._seed_ready_correction(
            prior_segment_id=segment.segment_id,
            prior_source_version_id=ingest1.source_version_id,
        )
        request2 = resolution_job_request(
            corr_cand,
            score_id=score2,
            verdict_set_hash=vs2,
            required_verification_policy=POLICY,
        )
        job2 = self.service.jobs.enqueue(7, ingest2.source_version_id, request2)
        for _ in range(300):
            job = self.service.jobs.get_job(job2.job_id)
            assert job is not None
            if job.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.DEAD}:
                break
            await asyncio.sleep(0.01)
        else:
            self.fail("correction job did not finish")
        with self.service.db.connection() as conn:
            err = conn.execute(
                "SELECT last_error FROM memory_jobs WHERE job_id=?",
                (job2.job_id,),
            ).fetchone()["last_error"]
        self.assertEqual(job.status, JobStatus.DONE, err)

        with self.service.db.connection() as conn:
            pref_assertions = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT schema_name, status, polarity, resolved_arguments_json
                    FROM memory_assertions
                    WHERE schema_name='likes'
                    ORDER BY created_at, assertion_id
                    """
                ).fetchall()
            ]
            corr = conn.execute(
                """
                SELECT r.utility_class, r.belief_status, b.schema_name
                FROM memory_belief_heads h
                JOIN memory_belief_revisions r
                  ON r.belief_revision_id = h.belief_revision_id
                JOIN memory_beliefs b ON b.belief_id = h.belief_id
                WHERE b.schema_name='corrects_preference'
                """
            ).fetchone()
            heads = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT b.schema_name, r.belief_status, r.utility_class,
                           r.resolved_arguments_json
                    FROM memory_belief_heads h
                    JOIN memory_belief_revisions r
                      ON r.belief_revision_id = h.belief_revision_id
                    JOIN memory_beliefs b ON b.belief_id = h.belief_id
                    WHERE b.schema_name='likes'
                    ORDER BY b.created_at, b.belief_id
                    """
                ).fetchall()
            ]

        self.assertGreaterEqual(len(pref_assertions), 2)
        statuses = {row["status"] for row in pref_assertions}
        self.assertIn("historical", statuses)
        self.assertIn("active", statuses)
        self.assertIsNotNone(corr)
        self.assertEqual(corr["utility_class"], "deferred")
        durable = [
            row
            for row in heads
            if row["belief_status"] == "active" and row["utility_class"] == "durable"
        ]
        historical = [row for row in heads if row["belief_status"] == "historical"]
        self.assertEqual(len(durable), 1)
        self.assertGreaterEqual(len(historical), 1)
        durable_args = json.loads(durable[0]["resolved_arguments_json"])
        labels = []
        with self.service.db.connection() as conn:
            for arg in durable_args:
                if arg.get("entity_id"):
                    lab = conn.execute(
                        "SELECT canonical_label FROM memory_entities WHERE entity_id=?",
                        (arg["entity_id"],),
                    ).fetchone()
                    if lab:
                        labels.append(str(lab["canonical_label"]))
        self.assertTrue(any("German" in lab for lab in labels))

    def _seed_ready_negative(
        self,
        *,
        prior_segment_id: str,
        prior_source_version_id: str,
        user_id: int = 7,
        message_id: int = 3,
    ):
        text = "I no longer like Italian food."
        ingest = self.service.register_source(
            SourceInput(
                user_id=user_id,
                source_type="chat_message",
                source_ref=f"chat_message_id:{message_id}",
                authority_class="user_direct_statement",
                content_hash=content_hash_from_text(text),
                occurred_at=datetime(2026, 7, 12, 12, 10, tzinfo=timezone.utc),
                pointer=EvidencePointer(
                    pointer_version=1,
                    kind="chat_message",
                    source_version_id="pending",
                    location={"chat_message_id": message_id},
                ),
            )
        )
        pointer = EvidencePointer(
            pointer_version=1,
            kind="chat_message",
            source_version_id=ingest.source_version_id,
            location={"chat_message_id": message_id},
        )
        self.service.segments.insert_segments(
            (
                SegmentInput(
                    source_version_id=ingest.source_version_id,
                    segment_type="chat_text",
                    ordinal=0,
                    text=text,
                    pointer=pointer,
                    normalizer_name="chat_text_normalizer",
                    normalizer_version="1",
                    input_hash=content_hash_from_text(text),
                ),
            ),
            user_id=user_id,
            lineage_store=self.service.lineage,
        )
        segment = self.service.segments.list_for_source_version(
            ingest.source_version_id, user_id=user_id
        )[0]
        job = self.service.jobs.enqueue(
            user_id,
            ingest.source_version_id,
            JobRequest(
                stage="candidate_extract",
                processor_name="seed_extractor",
                processor_version="1",
                prompt_version="seed",
                model_profile="fake",
                input_hash=f"seed-{message_id}",
                config_hash="seed",
            ),
        )
        run_id = f"mrun_seed_{message_id}"
        now = utc_now_iso()
        with self.service.db.transaction() as conn:
            conn.execute(
                "UPDATE memory_jobs SET status='done' WHERE job_id=?",
                (job.job_id,),
            )
            conn.execute(
                """
                INSERT INTO memory_processor_runs(
                    run_id, job_id, user_id, processor_name, processor_version,
                    prompt_version, model_profile, started_at, completed_at,
                    outcome, input_hash, output_hash
                ) VALUES (?, ?, ?, 'seed_extractor', '1', 'seed', 'fake', ?, ?, 'completed', ?, ?)
                """,
                (run_id, job.job_id, user_id, now, now, f"seed-{message_id}", "out"),
            )
            self.service.candidates.insert_in_txn(
                conn,
                (
                    CandidateInput(
                        local_ref="c_neg",
                        segment_id=segment.segment_id,
                        kind="preference",
                        schema_name="likes",
                        schema_version="1",
                        arguments=(
                            CandidateArgument(
                                role="subject", literal="self", has_literal=True
                            ),
                            CandidateArgument(
                                role="value",
                                literal="Italian food",
                                has_literal=True,
                            ),
                        ),
                        attributes={},
                        polarity=Polarity.NEGATIVE.value,
                        epistemic=Epistemic(
                            mode=EpistemicMode.ASSERTED,
                            speaker_commitment=SpeakerCommitment.CERTAIN,
                            scope=EpistemicScope.PROPOSITION,
                        ),
                        temporal=None,
                        status="ready_for_resolution",
                        evidence=(
                            CandidateEvidenceInput(
                                segment_id=segment.segment_id,
                                relation="supports",
                                pointer=EvidencePointer(
                                    pointer_version=1,
                                    kind="chat_span",
                                    source_version_id=ingest.source_version_id,
                                    location={
                                        "chat_message_id": message_id,
                                        "char_start": 0,
                                        "char_end": len(text),
                                    },
                                ),
                                exact_quote=text,
                            ),
                            CandidateEvidenceInput(
                                segment_id=prior_segment_id,
                                relation="supports",
                                pointer=EvidencePointer(
                                    pointer_version=1,
                                    kind="chat_span",
                                    source_version_id=prior_source_version_id,
                                    location={
                                        "chat_message_id": 1,
                                        "char_start": 0,
                                        "char_end": len("I like Italian food."),
                                    },
                                ),
                                exact_quote="I like Italian food.",
                            ),
                        ),
                        canonical_hint=None,
                        extractor_name="seed",
                        extractor_version="1",
                        prompt_version="seed",
                    ),
                ),
                user_id=user_id,
                extraction_run_id=run_id,
                mention_ids={},
                lineage_store=self.service.lineage,
            )
            conn.execute(
                """
                UPDATE memory_claim_candidates
                SET status='ready_for_resolution', acceptance_policy=?
                WHERE extraction_run_id=?
                """,
                (POLICY, run_id),
            )
            cand = conn.execute(
                "SELECT candidate_id FROM memory_claim_candidates WHERE extraction_run_id=?",
                (run_id,),
            ).fetchone()
            candidate_id = str(cand["candidate_id"])
            verdict_set_hash = "vs_seed_neg"
            score_id = make_score_id(
                candidate_id=candidate_id,
                policy_version=POLICY,
                verdict_set_hash=verdict_set_hash,
            )
            conn.execute(
                """
                INSERT INTO memory_candidate_scores(
                    score_id, user_id, candidate_id, policy_version, verdict_set_hash,
                    components_json, route_status, verification_run_id, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'ready_for_resolution', ?, ?, 'active')
                """,
                (
                    score_id,
                    user_id,
                    candidate_id,
                    POLICY,
                    verdict_set_hash,
                    json.dumps({"ok": True}),
                    run_id,
                    now,
                ),
            )
        return ingest, candidate_id, score_id, verdict_set_hash

    async def test_cessation_historicalizes_prior_positive(self) -> None:
        harness = ResolutionPipelineTests()
        harness.service = self.service
        ingest1, pref_cand, score1, vs1 = harness._seed_ready_preference()
        segment = self.service.segments.list_for_source_version(
            ingest1.source_version_id, user_id=7
        )[0]
        request1 = resolution_job_request(
            pref_cand,
            score_id=score1,
            verdict_set_hash=vs1,
            required_verification_policy=POLICY,
        )
        job1 = self.service.jobs.enqueue(7, ingest1.source_version_id, request1)
        await self.service.start_worker()
        for _ in range(300):
            job = self.service.jobs.get_job(job1.job_id)
            assert job is not None
            if job.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.DEAD}:
                break
            await asyncio.sleep(0.01)
        else:
            self.fail("preference job did not finish")
        self.assertEqual(job.status, JobStatus.DONE)

        ingest2, neg_cand, score2, vs2 = self._seed_ready_negative(
            prior_segment_id=segment.segment_id,
            prior_source_version_id=ingest1.source_version_id,
        )
        request2 = resolution_job_request(
            neg_cand,
            score_id=score2,
            verdict_set_hash=vs2,
            required_verification_policy=POLICY,
        )
        job2 = self.service.jobs.enqueue(7, ingest2.source_version_id, request2)
        for _ in range(300):
            job = self.service.jobs.get_job(job2.job_id)
            assert job is not None
            if job.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.DEAD}:
                break
            await asyncio.sleep(0.01)
        else:
            self.fail("cessation job did not finish")
        with self.service.db.connection() as conn:
            err = conn.execute(
                "SELECT last_error FROM memory_jobs WHERE job_id=?",
                (job2.job_id,),
            ).fetchone()["last_error"]
        self.assertEqual(job.status, JobStatus.DONE, err)

        with self.service.db.connection() as conn:
            statuses = {
                str(row["status"])
                for row in conn.execute(
                    """
                    SELECT status FROM memory_assertions
                    WHERE schema_name='likes' AND polarity='positive'
                    """
                ).fetchall()
            }
            heads = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT r.belief_status, r.polarity, r.utility_class
                    FROM memory_belief_heads h
                    JOIN memory_belief_revisions r
                      ON r.belief_revision_id = h.belief_revision_id
                    JOIN memory_beliefs b ON b.belief_id = h.belief_id
                    WHERE b.schema_name='likes'
                    """
                ).fetchall()
            ]
        self.assertIn("historical", statuses)
        with self.service.db.connection() as conn:
            active_pos = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT assertion_id FROM memory_assertions
                    WHERE schema_name='likes' AND polarity='positive' AND status='active'
                    """
                ).fetchall()
            ]
            neg_assertions = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT status, polarity FROM memory_assertions
                    WHERE schema_name='likes' AND polarity='negative'
                    """
                ).fetchall()
            ]
        self.assertEqual(active_pos, [])
        self.assertTrue(any(row["status"] == "active" for row in neg_assertions))
        # Same proposition_key → single head ends active+negative after cessation.
        durable_neg = [
            row
            for row in heads
            if row["belief_status"] == "active"
            and row["polarity"] == "negative"
            and row["utility_class"] == "durable"
        ]
        self.assertEqual(len(durable_neg), 1, heads)


class TemporalUnitTests(unittest.TestCase):
    def test_labels_compatible_morphology(self) -> None:
        from memory.resolution.temporal import labels_compatible

        self.assertTrue(labels_compatible("Italian food", "italian food"))
        self.assertTrue(labels_compatible("италянскую еду", "италянская еда"))
        self.assertFalse(labels_compatible("German food", "Italian food"))


if __name__ == "__main__":
    unittest.main()
