from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from memory.config import MemoryConfig
from memory.db import utc_now_iso
from memory.extraction.candidates import CandidateEvidenceInput, CandidateInput
from memory.extraction.schemas import (
    CandidateArgument,
    Epistemic,
    EpistemicMode,
    EpistemicScope,
    Polarity,
    SpeakerCommitment,
)
from memory.graph.explain import explain_belief
from memory.graph.materializer import GraphMaterializer
from memory.graph.rebuild import rebuild_user_graph
from memory.graph.schemas import EDGE_STATUS_ACTIVE, EDGE_STATUS_EXPIRED
from memory.ids import content_hash_from_text, make_score_id
from memory.models import JobRequest, JobStatus, SegmentInput, SourceInput
from memory.pointers import EvidencePointer
from memory.resolution.jobs import resolution_job_request
from memory.resolution.pipeline import register_candidate_resolver
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
        graph_enabled=True,
        required_verification_policy_version=POLICY,
    )
    return MemoryConfig(**{**base.__dict__, **overrides})


class GraphSchemaTests(unittest.TestCase):
    def test_fresh_db_is_schema_v11(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "memory.sqlite")
            service = MemoryService(
                config=_config(
                    path,
                    worker_enabled=False,
                    verification_enabled=False,
                    resolution_enabled=False,
                    graph_enabled=False,
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
                "graph_nodes",
                "graph_edges",
                "graph_outbox",
                "graph_revisions",
                "graph_summaries",
                "graph_communities",
                "graph_summary_dirty",
                "graph_summary_user_state",
            ):
                self.assertIn(name, tables)


class GraphMaterializerTests(unittest.IsolatedAsyncioTestCase):
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
                        local_ref="c1",
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
        return ingest, candidate_id, score_id, verdict_set_hash, text

    async def _wait_done(self, job_id: str) -> JobStatus:
        for _ in range(300):
            job = self.service.jobs.get_job(job_id)
            assert job is not None
            if job.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.DEAD}:
                return job.status
            await asyncio.sleep(0.01)
        self.fail("job did not finish")

    async def _resolve_and_drain(self):
        ingest, candidate_id, score_id, verdict_set_hash, text = self._seed_ready_preference()
        request = resolution_job_request(
            candidate_id,
            score_id=score_id,
            verdict_set_hash=verdict_set_hash,
            required_verification_policy=POLICY,
        )
        enqueued = self.service.jobs.enqueue(7, ingest.source_version_id, request)
        await self.service.start_worker()
        status = await self._wait_done(enqueued.job_id)
        self.assertEqual(status, JobStatus.DONE)
        materializer = GraphMaterializer(
            self.service.db,
            store=self.service.graph,
            outbox=self.service.graph_outbox,
        )
        results = materializer.drain_once(limit=20)
        return ingest, text, results

    async def test_preference_creates_prefers_edge(self) -> None:
        ingest, text, results = await self._resolve_and_drain()
        self.assertTrue(any(not item.skipped for item in results))
        edges = self.service.graph.list_active_edges(user_id=7)
        nodes = self.service.graph.list_active_nodes(user_id=7)
        self.assertEqual(len(edges), 1)
        self.assertEqual(str(edges[0]["edge_type"]), "preference:likes")
        labels = {str(node["label"]) for node in nodes}
        self.assertIn("self", labels)
        self.assertIn("Italian food", labels)
        belief_id = str(edges[0]["belief_id"])
        explained = explain_belief(self.service, user_id=7, belief_id=belief_id)
        self.assertIn(text, explained["human_summary"])
        quotes = [
            quote.get("exact_quote")
            for layer in explained["support"]
            for quote in layer["evidence"]
        ]
        self.assertIn(text, quotes)
        _ = ingest

    async def test_idempotent_rematerialize_and_rebuild(self) -> None:
        await self._resolve_and_drain()
        edges_before = self.service.graph.list_active_edges(user_id=7)
        self.assertEqual(len(edges_before), 1)
        belief_id = str(edges_before[0]["belief_id"])
        materializer = GraphMaterializer(
            self.service.db,
            store=self.service.graph,
            outbox=self.service.graph_outbox,
        )
        again = materializer.materialize_belief(user_id=7, belief_id=belief_id)
        self.assertFalse(again.skipped)
        edges_mid = self.service.graph.list_active_edges(user_id=7)
        self.assertEqual(len(edges_mid), 1)
        self.assertEqual(str(edges_mid[0]["edge_id"]), str(edges_before[0]["edge_id"]))

        rebuilt = rebuild_user_graph(self.service.db, user_id=7, store=self.service.graph)
        self.assertEqual(rebuilt.edges_active, 1)
        edges_after = self.service.graph.list_active_edges(user_id=7)
        self.assertEqual(len(edges_after), 1)
        self.assertEqual(str(edges_after[0]["edge_type"]), "preference:likes")

    async def test_invalidate_expires_edge(self) -> None:
        ingest, _text, _results = await self._resolve_and_drain()
        edges = self.service.graph.list_active_edges(user_id=7)
        self.assertEqual(len(edges), 1)
        self.service.sources.invalidate(ingest.source_id, user_id=7, reason="forget")
        materializer = GraphMaterializer(
            self.service.db,
            store=self.service.graph,
            outbox=self.service.graph_outbox,
        )
        materializer.drain_once(limit=20)
        active = self.service.graph.list_active_edges(user_id=7)
        self.assertEqual(active, [])
        with self.service.db.connection() as conn:
            statuses = {
                str(row["status"])
                for row in conn.execute(
                    "SELECT status FROM graph_edges WHERE user_id=7"
                ).fetchall()
            }
        self.assertEqual(statuses, {EDGE_STATUS_EXPIRED})

    async def test_cross_user_isolation(self) -> None:
        await self._resolve_and_drain()
        other = self.service.graph.list_active_edges(user_id=99)
        self.assertEqual(other, [])
        owned = self.service.graph.list_active_edges(user_id=7)
        self.assertEqual(len(owned), 1)

    async def test_deferred_belief_skips_edge(self) -> None:
        # Person mention → provisional identity → deferred utility → remove/no edge.
        text = "Alice likes pasta."
        ingest = self.service.register_source(
            SourceInput(
                user_id=7,
                source_type="chat_message",
                source_ref="chat_message_id:77",
                authority_class="user_direct_statement",
                content_hash=content_hash_from_text(text),
                pointer=EvidencePointer(
                    pointer_version=1,
                    kind="chat_message",
                    source_version_id="pending",
                    location={"chat_message_id": 77},
                ),
            )
        )
        pointer = EvidencePointer(
            pointer_version=1,
            kind="chat_message",
            source_version_id=ingest.source_version_id,
            location={"chat_message_id": 77},
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
        from memory.extraction.mentions import MentionInput

        job = self.service.jobs.enqueue(
            7,
            ingest.source_version_id,
            JobRequest(
                stage="candidate_extract",
                processor_name="seed_extractor",
                processor_version="1",
                prompt_version="seed",
                model_profile="fake",
                input_hash="seed-alice",
                config_hash="seed",
            ),
        )
        run_id = "mrun_seed_alice"
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
                ) VALUES (?, ?, 7, 'seed_extractor', '1', 'seed', 'fake', ?, ?, 'completed', ?, ?)
                """,
                (run_id, job.job_id, now, now, "seed-alice", "out"),
            )
            mention_ids = self.service.mentions.insert_in_txn(
                conn,
                (
                    MentionInput(
                        local_ref="m_alice",
                        segment_id=segment.segment_id,
                        mention_type="person",
                        surface_text="Alice",
                        normalized_hint="Alice",
                        pointer=EvidencePointer(
                            pointer_version=1,
                            kind="chat_span",
                            source_version_id=ingest.source_version_id,
                            location={
                                "chat_message_id": 77,
                                "char_start": 0,
                                "char_end": 5,
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
                        local_ref="c_alice",
                        segment_id=segment.segment_id,
                        kind="preference",
                        schema_name="likes",
                        schema_version="1",
                        arguments=(
                            CandidateArgument(
                                role="subject",
                                mention_ref="m_alice",
                                has_literal=False,
                            ),
                            CandidateArgument(
                                role="value", literal="pasta", has_literal=True
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
                                        "chat_message_id": 77,
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
            verdict_set_hash = "vs_alice"
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
        self.assertEqual(status, JobStatus.DONE)
        GraphMaterializer(
            self.service.db,
            store=self.service.graph,
            outbox=self.service.graph_outbox,
        ).drain_once(limit=20)
        self.assertEqual(self.service.graph.list_active_edges(user_id=7), [])

    async def test_correction_swaps_durable_graph_edge(self) -> None:
        """Italian durable edge expires; German winner materializes."""
        from memory.extraction.candidates import CandidateEvidenceInput, CandidateInput
        from memory.extraction.schemas import (
            CandidateArgument,
            Epistemic,
            EpistemicMode,
            EpistemicScope,
            Polarity,
            SpeakerCommitment,
        )

        ingest1, cand1, score1, vs1, _text = self._seed_ready_preference()
        request1 = resolution_job_request(
            cand1,
            score_id=score1,
            verdict_set_hash=vs1,
            required_verification_policy=POLICY,
        )
        job1 = self.service.jobs.enqueue(7, ingest1.source_version_id, request1)
        await self.service.start_worker()
        self.assertEqual(await self._wait_done(job1.job_id), JobStatus.DONE)
        GraphMaterializer(
            self.service.db,
            store=self.service.graph,
            outbox=self.service.graph_outbox,
        ).drain_once(limit=20)
        edges_before = self.service.graph.list_active_edges(user_id=7)
        self.assertEqual(len(edges_before), 1)

        segment = self.service.segments.list_for_source_version(
            ingest1.source_version_id, user_id=7
        )[0]
        text = "Actually I prefer German food."
        ingest2 = self.service.register_source(
            SourceInput(
                user_id=7,
                source_type="chat_message",
                source_ref="chat_message_id:2",
                authority_class="user_direct_statement",
                content_hash=content_hash_from_text(text),
                occurred_at=datetime(2026, 7, 12, 12, 5, tzinfo=timezone.utc),
                pointer=EvidencePointer(
                    pointer_version=1,
                    kind="chat_message",
                    source_version_id="pending",
                    location={"chat_message_id": 2},
                ),
            )
        )
        pointer = EvidencePointer(
            pointer_version=1,
            kind="chat_message",
            source_version_id=ingest2.source_version_id,
            location={"chat_message_id": 2},
        )
        self.service.segments.insert_segments(
            (
                SegmentInput(
                    source_version_id=ingest2.source_version_id,
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
        corr_segment = self.service.segments.list_for_source_version(
            ingest2.source_version_id, user_id=7
        )[0]
        job = self.service.jobs.enqueue(
            7,
            ingest2.source_version_id,
            JobRequest(
                stage="candidate_extract",
                processor_name="seed_extractor",
                processor_version="1",
                prompt_version="seed",
                model_profile="fake",
                input_hash="seed-2",
                config_hash="seed",
            ),
        )
        run_id = "mrun_seed_2"
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
                ) VALUES (?, ?, 7, 'seed_extractor', '1', 'seed', 'fake', ?, ?, 'completed', 'seed-2', 'out')
                """,
                (run_id, job.job_id, now, now),
            )
            self.service.candidates.insert_in_txn(
                conn,
                (
                    CandidateInput(
                        local_ref="c_corr",
                        segment_id=corr_segment.segment_id,
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
                                segment_id=corr_segment.segment_id,
                                relation="supports",
                                pointer=EvidencePointer(
                                    pointer_version=1,
                                    kind="chat_span",
                                    source_version_id=ingest2.source_version_id,
                                    location={
                                        "chat_message_id": 2,
                                        "char_start": 0,
                                        "char_end": len(text),
                                    },
                                ),
                                exact_quote=text,
                            ),
                            CandidateEvidenceInput(
                                segment_id=segment.segment_id,
                                relation="supports",
                                pointer=EvidencePointer(
                                    pointer_version=1,
                                    kind="chat_span",
                                    source_version_id=ingest1.source_version_id,
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
                user_id=7,
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
            corr_cand = str(
                conn.execute(
                    "SELECT candidate_id FROM memory_claim_candidates WHERE extraction_run_id=?",
                    (run_id,),
                ).fetchone()["candidate_id"]
            )
            vs2 = "vs_corr"
            score2 = make_score_id(
                candidate_id=corr_cand,
                policy_version=POLICY,
                verdict_set_hash=vs2,
            )
            conn.execute(
                """
                INSERT INTO memory_candidate_scores(
                    score_id, user_id, candidate_id, policy_version, verdict_set_hash,
                    components_json, route_status, verification_run_id, created_at, status
                ) VALUES (?, 7, ?, ?, ?, '{}', 'ready_for_resolution', ?, ?, 'active')
                """,
                (score2, corr_cand, POLICY, vs2, run_id, now),
            )
        request2 = resolution_job_request(
            corr_cand,
            score_id=score2,
            verdict_set_hash=vs2,
            required_verification_policy=POLICY,
        )
        job2 = self.service.jobs.enqueue(7, ingest2.source_version_id, request2)
        self.assertEqual(await self._wait_done(job2.job_id), JobStatus.DONE)
        GraphMaterializer(
            self.service.db,
            store=self.service.graph,
            outbox=self.service.graph_outbox,
        ).drain_once(limit=50)

        edges = self.service.graph.list_active_edges(user_id=7)
        self.assertEqual(len(edges), 1)
        nodes = {
            str(row["node_id"]): str(row["label"] or "")
            for row in self.service.graph.list_active_nodes(user_id=7)
        }
        edge = edges[0]
        self.assertIn("German", nodes.get(str(edge["to_node_id"]), ""))


if __name__ == "__main__":
    unittest.main()
