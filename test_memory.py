from __future__ import annotations

import asyncio
import concurrent.futures
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from memory.config import MemoryConfig, validate_memory_config
from memory.db import MemoryDatabase, configure_connection, utc_now_iso
from memory.ids import (
    canonical_json,
    content_hash_from_text,
    make_job_id,
    make_source_id,
    make_source_version_id,
    normalize_workspace_path,
)
from memory.jobs import (
    MemoryJobOwnershipError,
    MemoryJobQueue,
    MemoryLeaseError,
    MemorySourceInactiveError,
)
from memory.models import JobRequest, JobStatus, LineageRelation, ProcessorOutput, SegmentInput, SourceInput
from memory.pointers import (
    EvidencePointer,
    PointerOwnershipError,
    PointerValidationError,
    dereference_contract,
    pointer_from_mapping,
    pointer_to_mapping,
    verify_pointer_ownership,
)
from memory.processors import NoopProcessor, ProcessorRegistry
from memory.schema import SCHEMA_VERSION, MemorySchemaError, ensure_schema
from memory.service import MemoryService, reset_memory_service
from memory.sources import MemoryOwnershipError


def _file_config(tmp: tempfile.TemporaryDirectory[str], **overrides) -> MemoryConfig:
    db_path = str(Path(tmp.name) / "memory.sqlite")
    return _test_config(db_path=db_path, **overrides)


def _lease_args(job) -> dict:
    assert job.lease_token is not None
    return {
        "worker_id": str(job.lease_owner),
        "lease_token": job.lease_token,
        "attempt": job.attempts,
        "input_hash": job.input_hash,
    }


def _test_config(**overrides) -> MemoryConfig:
    base = MemoryConfig(
        ingest_enabled=False,
        db_path=":memory:",
        worker_enabled=False,
        worker_concurrency=2,
        worker_poll_seconds=0.05,
        job_lease_seconds=2,
        job_max_attempts=3,
        job_retry_base_seconds=0.01,
        job_retry_max_seconds=0.05,
        job_claim_batch_size=5,
    )
    return MemoryConfig(**{**base.__dict__, **overrides})


def _chat_pointer(*, message_id: int = 1, version_id: str = "pending") -> EvidencePointer:
    return EvidencePointer(
        pointer_version=1,
        kind="chat_message",
        source_version_id=version_id,
        location={"chat_message_id": message_id},
    )


def _source_input(
    *,
    user_id: int = 1,
    content: str = "hello",
    source_ref: str = "chat_message_id:1",
    pointer: EvidencePointer | None = None,
) -> SourceInput:
    return SourceInput(
        user_id=user_id,
        source_type="chat_message",
        source_ref=source_ref,
        authority_class="user_direct_statement",
        content_hash=content_hash_from_text(content),
        pointer=pointer or _chat_pointer(),
        session_id="sess-1",
    )


class MemorySchemaTests(unittest.TestCase):
    def test_create_and_reopen_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "memory.sqlite")
            MemoryService(db_path=db_path, config=_test_config(db_path=db_path))
            reopened = MemoryService(db_path=db_path, config=_test_config(db_path=db_path))
            status = reopened.status()
            self.assertEqual(status.schema_version, SCHEMA_VERSION)

    def test_migrations_idempotent(self) -> None:
        db = MemoryDatabase(":memory:")
        with db.connection() as conn:
            ensure_schema(conn)
            ensure_schema(conn)
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM memory_schema_migrations WHERE version = ?",
                (SCHEMA_VERSION,),
            ).fetchone()
            self.assertEqual(int(row["c"]), 1)

    def test_foreign_keys_and_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "memory.sqlite")
            conn = sqlite3.connect(db_path)
            configure_connection(conn)
            ensure_schema(conn)
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
            conn.close()
            self.assertEqual(fk, 1)
            self.assertEqual(journal.lower(), "wal")

    def test_future_schema_version_fails(self) -> None:
        db = MemoryDatabase(":memory:")
        with db.connection() as conn:
            ensure_schema(conn)
            conn.execute(
                "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION + 1, utc_now_iso()),
            )
            conn.commit()
        with self.assertRaises(MemorySchemaError):
            with db.connection() as conn:
                ensure_schema(conn)

    def test_corrupt_schema_missing_required_index_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "memory.sqlite")
            db = MemoryDatabase(db_path)
            with db.transaction() as conn:
                conn.execute("DROP INDEX idx_memory_jobs_claim")
            with db.connection() as conn:
                with self.assertRaises(MemorySchemaError):
                    ensure_schema(conn)

    def test_non_contiguous_migrations_fail(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE memory_schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (?, ?)",
            (2, utc_now_iso()),
        )
        with self.assertRaises(MemorySchemaError):
            ensure_schema(conn)
        conn.close()

    def test_import_has_no_database_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "memory.sqlite"
            env = dict(os.environ)
            env["MEMORY_DB_PATH"] = str(db_path)
            result = subprocess.run(
                [sys.executable, "-c", "import memory"],
                cwd=Path(__file__).parent,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(db_path.exists())


class DeterministicIdTests(unittest.TestCase):
    def test_equal_inputs_same_ids(self) -> None:
        a = make_source_id(user_id=1, source_type="chat_message", source_ref="chat_message_id:1")
        b = make_source_id(user_id=1, source_type="chat_message", source_ref="chat_message_id:1")
        self.assertEqual(a, b)

    def test_different_users_different_source_ids(self) -> None:
        a = make_source_id(user_id=1, source_type="chat_message", source_ref="chat_message_id:1")
        b = make_source_id(user_id=2, source_type="chat_message", source_ref="chat_message_id:1")
        self.assertNotEqual(a, b)

    def test_same_bytes_different_refs_remain_different_sources(self) -> None:
        content_hash = content_hash_from_text("same")
        ref_a = make_source_id(user_id=1, source_type="chat_message", source_ref="chat_message_id:1")
        ref_b = make_source_id(user_id=1, source_type="chat_message", source_ref="chat_message_id:2")
        self.assertNotEqual(ref_a, ref_b)
        self.assertEqual(
            make_source_version_id(source_id=ref_a, content_hash=content_hash),
            make_source_version_id(source_id=ref_a, content_hash=content_hash),
        )

    def test_content_change_creates_new_version_id(self) -> None:
        source_id = make_source_id(user_id=1, source_type="chat_message", source_ref="chat_message_id:1")
        v1 = make_source_version_id(source_id=source_id, content_hash=content_hash_from_text("a"))
        v2 = make_source_version_id(source_id=source_id, content_hash=content_hash_from_text("b"))
        self.assertNotEqual(v1, v2)

    def test_canonical_json_order_stable(self) -> None:
        first = canonical_json({"b": 1, "a": 2})
        second = canonical_json({"a": 2, "b": 1})
        self.assertEqual(first, second)


class SourceRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_memory_service()
        self.tmp = tempfile.TemporaryDirectory()
        self.config = _file_config(self.tmp)
        self.service = MemoryService(config=self.config)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_first_registration_creates_source_version_and_jobs(self) -> None:
        job = JobRequest(
            stage="noop",
            processor_name="noop",
            processor_version="1",
            input_hash="in",
        )
        result = self.service.register_source(_source_input(), initial_jobs=[job])
        self.assertTrue(result.source_created)
        self.assertTrue(result.version_created)
        self.assertEqual(len(result.enqueued_job_ids), 1)

    def test_duplicate_registration_is_noop(self) -> None:
        job = JobRequest(stage="noop", processor_name="noop", processor_version="1", input_hash="in")
        first = self.service.register_source(_source_input(), initial_jobs=[job])
        second = self.service.register_source(_source_input(), initial_jobs=[job])
        self.assertFalse(second.source_created)
        self.assertFalse(second.version_created)
        self.assertEqual(second.enqueued_job_ids, ())
        self.assertEqual(first.source_id, second.source_id)

    def test_content_update_supersedes_prior_version(self) -> None:
        first = self.service.register_source(_source_input(content="v1"))
        second = self.service.register_source(_source_input(content="v2"))
        self.assertTrue(second.version_created)
        self.assertIsNotNone(second.superseded_version_id)
        self.assertEqual(second.superseded_version_id, first.source_version_id)
        old = self.service.sources.get_version(first.source_version_id, user_id=1)
        assert old is not None
        self.assertEqual(old.status.value, "superseded")

    def test_cross_user_read_fails(self) -> None:
        result = self.service.register_source(_source_input(user_id=1))
        with self.assertRaises(MemoryOwnershipError):
            self.service.sources.get_source(result.source_id, user_id=2)

    def test_invalidation_is_user_scoped(self) -> None:
        owned = self.service.register_source(_source_input(user_id=1))
        other = self.service.register_source(
            _source_input(user_id=2, source_ref="chat_message_id:2", pointer=_chat_pointer(message_id=2)),
        )
        with self.assertRaises(MemoryOwnershipError):
            self.service.sources.invalidate(owned.source_id, user_id=2, reason="test")
        self.service.sources.invalidate(owned.source_id, user_id=1, reason="test")
        still_active = self.service.sources.get_source(other.source_id, user_id=2)
        assert still_active is not None
        self.assertEqual(still_active.status.value, "active")

    def test_invalidated_source_cannot_be_registered_again(self) -> None:
        result = self.service.register_source(_source_input())
        self.service.sources.invalidate(result.source_id, user_id=1, reason="forget")
        with self.assertRaises(RuntimeError):
            self.service.register_source(_source_input())

    def test_registration_rolls_back_if_initial_job_is_invalid(self) -> None:
        bad_job = JobRequest(
            stage="noop",
            processor_name="noop",
            processor_version="1",
            input_hash="input",
            max_attempts=0,
        )
        with self.assertRaises(ValueError):
            self.service.register_source(
                _source_input(source_ref="chat_message_id:rollback"),
                initial_jobs=[bad_job],
            )
        with self.service.db.connection() as conn:
            source_count = int(
                conn.execute("SELECT COUNT(*) AS c FROM memory_sources").fetchone()["c"]
            )
            version_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM memory_source_versions"
                ).fetchone()["c"]
            )
        self.assertEqual((source_count, version_count), (0, 0))

    def test_concurrent_duplicate_registration_is_atomic(self) -> None:
        other = MemoryService(config=self.config)
        request = JobRequest(
            stage="noop",
            processor_name="noop",
            processor_version="1",
            input_hash="input",
        )
        barrier = threading.Barrier(2)

        def register(service: MemoryService):
            barrier.wait()
            return service.register_source(
                _source_input(source_ref="chat_message_id:concurrent"),
                initial_jobs=[request],
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(register, (self.service, other)))
        self.assertEqual(sum(result.source_created for result in (first, second)), 1)
        self.assertEqual(sum(result.version_created for result in (first, second)), 1)
        with self.service.db.connection() as conn:
            counts = (
                int(conn.execute("SELECT COUNT(*) AS c FROM memory_sources").fetchone()["c"]),
                int(
                    conn.execute(
                        "SELECT COUNT(*) AS c FROM memory_source_versions"
                    ).fetchone()["c"]
                ),
                int(conn.execute("SELECT COUNT(*) AS c FROM memory_jobs").fetchone()["c"]),
            )
        self.assertEqual(counts, (1, 1, 1))


class PointerTests(unittest.TestCase):
    def test_chat_span_round_trip(self) -> None:
        pointer = EvidencePointer(
            pointer_version=1,
            kind="chat_span",
            source_version_id="msv_test",
            location={"chat_message_id": 5, "char_start": 1, "char_end": 4},
        )
        restored = pointer_from_mapping(pointer_to_mapping(pointer))
        self.assertEqual(restored, pointer)

    def test_invalid_span_rejected(self) -> None:
        with self.assertRaises(PointerValidationError):
            pointer_from_mapping(
                {
                    "pointer_version": 1,
                    "kind": "chat_span",
                    "source_version_id": "msv_x",
                    "location": {"chat_message_id": 1, "char_start": 5, "char_end": 2},
                }
            )

    def test_unknown_pointer_version_fails_closed(self) -> None:
        with self.assertRaises(PointerValidationError):
            pointer_from_mapping(
                {
                    "pointer_version": 99,
                    "kind": "chat_message",
                    "source_version_id": "msv_x",
                    "location": {"chat_message_id": 1},
                }
            )

    def test_workspace_path_must_be_relative(self) -> None:
        with self.assertRaises(ValueError):
            normalize_workspace_path("/etc/passwd")
        with self.assertRaises(ValueError):
            normalize_workspace_path("C:relative.txt")

    def test_workspace_pointer_is_canonicalized(self) -> None:
        pointer = EvidencePointer(
            pointer_version=1,
            kind="workspace_file",
            source_version_id="msv_1",
            location={"workspace_path": r"folder\\sub/./file.txt"},
        )
        self.assertEqual(pointer.location["workspace_path"], "folder/sub/file.txt")

    def test_direct_pointer_construction_validates(self) -> None:
        with self.assertRaises(PointerValidationError):
            EvidencePointer(
                pointer_version=1,
                kind="unknown",
                source_version_id="msv_1",
                location={},
            )

    def test_all_pointer_kinds_round_trip(self) -> None:
        locations = {
            "chat_message": {"chat_message_id": 1},
            "chat_span": {
                "chat_message_id": 1,
                "char_start": 0,
                "char_end": 2,
            },
            "tool_result": {"tool_result_ref": "tool-result-1"},
            "workspace_file": {"workspace_path": "docs/file.txt"},
            "document_region": {
                "workspace_path": "docs/file.pdf",
                "page": 1,
                "bbox": [0, 0, 20, 30],
            },
            "image_region": {
                "workspace_path": "images/photo.jpg",
                "region": [0, 0, 1, 1],
            },
        }
        for kind, location in locations.items():
            with self.subTest(kind=kind):
                pointer = EvidencePointer(
                    pointer_version=1,
                    kind=kind,
                    source_version_id="msv_1",
                    location=location,
                )
                self.assertEqual(
                    pointer_from_mapping(pointer_to_mapping(pointer)),
                    pointer,
                )

    def test_non_finite_and_negative_coordinates_are_rejected(self) -> None:
        with self.assertRaises(PointerValidationError):
            EvidencePointer(
                pointer_version=1,
                kind="image_region",
                source_version_id="msv_1",
                location={
                    "workspace_path": "image.png",
                    "region": [0, 0, float("nan"), 1],
                },
            )
        with self.assertRaises(PointerValidationError):
            EvidencePointer(
                pointer_version=1,
                kind="document_region",
                source_version_id="msv_1",
                location={
                    "workspace_path": "document.pdf",
                    "page": 1,
                    "bbox": [-1, 0, 10, 10],
                },
            )

    def test_ownership_required(self) -> None:
        pointer = _chat_pointer(version_id="msv_1")
        with self.assertRaises(PointerOwnershipError):
            verify_pointer_ownership(
                pointer,
                user_id=1,
                source_version_id="msv_1",
                source_user_id=2,
            )
        dereference_contract(pointer, user_id=1, source_user_id=1)


class ProcessorRegistryTests(unittest.TestCase):
    def test_equivalent_registration_is_idempotent(self) -> None:
        registry = ProcessorRegistry()
        registry.register(NoopProcessor())
        registry.register(NoopProcessor())
        self.assertIsInstance(registry.resolve("noop", "noop", "1"), NoopProcessor)

    def test_incompatible_registration_fails(self) -> None:
        class OtherProcessor(NoopProcessor):
            pass

        registry = ProcessorRegistry()
        registry.register(NoopProcessor())
        with self.assertRaises(ValueError):
            registry.register(OtherProcessor())


class JobQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.config = _file_config(self.tmp)
        self.service = MemoryService(config=self.config)
        self.db = self.service.db
        self.jobs = self.service.jobs
        self.version_id = self.service.register_source(_source_input()).source_version_id

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _request(self, **kwargs) -> JobRequest:
        base = {
            "stage": "noop",
            "processor_name": "noop",
            "processor_version": "1",
            "input_hash": "input",
        }
        base.update(kwargs)
        return JobRequest(**base)

    def test_enqueue_idempotent(self) -> None:
        request = self._request()
        first = self.jobs.enqueue(1, self.version_id, request)
        second = self.jobs.enqueue(1, self.version_id, request)
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.job_id, second.job_id)

    def test_priority_ordering(self) -> None:
        low = self.jobs.enqueue(1, self.version_id, self._request(priority=0, input_hash="low"))
        high = self.jobs.enqueue(1, self.version_id, self._request(priority=10, input_hash="high"))
        claimed = self.jobs.claim(worker_id="w1", limit=2, lease_seconds=30)
        self.assertEqual(claimed[0].job_id, high.job_id)
        self.assertEqual(claimed[1].job_id, low.job_id)

    def test_only_one_worker_claims(self) -> None:
        self.jobs.enqueue(1, self.version_id, self._request())
        a = self.jobs.claim(worker_id="w1", limit=1, lease_seconds=30)
        b = self.jobs.claim(worker_id="w2", limit=1, lease_seconds=30)
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 0)

    def test_expired_lease_reclaimed(self) -> None:
        self.jobs.enqueue(1, self.version_id, self._request())
        claimed = self.jobs.claim(worker_id="w1", limit=1, lease_seconds=1)
        with self.db.transaction(immediate=True) as conn:
            past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
            conn.execute(
                "UPDATE memory_jobs SET lease_until = ? WHERE job_id = ?",
                (past, claimed[0].job_id),
            )
        reclaimed = self.jobs.claim(worker_id="w2", limit=1, lease_seconds=30)
        self.assertEqual(reclaimed[0].job_id, claimed[0].job_id)
        self.assertFalse(
            self.jobs.complete(
                claimed[0].job_id,
                **_lease_args(claimed[0]),
                output_hash="x",
                output_json={},
            )
        )

    def test_same_worker_stale_attempt_is_fenced(self) -> None:
        self.jobs.enqueue(1, self.version_id, self._request())
        first = self.jobs.claim(worker_id="same", limit=1, lease_seconds=1)[0]
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE memory_jobs SET lease_until = ? WHERE job_id = ?",
                (
                    (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                    first.job_id,
                ),
            )
        second = self.jobs.claim(worker_id="same", limit=1, lease_seconds=30)[0]
        self.assertNotEqual(first.lease_token, second.lease_token)
        self.assertFalse(
            self.jobs.complete(
                first.job_id,
                **_lease_args(first),
                output_hash="old",
                output_json={"attempt": 1},
            )
        )
        self.assertTrue(
            self.jobs.complete(
                second.job_id,
                **_lease_args(second),
                output_hash="new",
                output_json={"attempt": 2},
            )
        )

    def test_heartbeat_extends_ownership(self) -> None:
        self.jobs.enqueue(1, self.version_id, self._request())
        claimed = self.jobs.claim(worker_id="w1", limit=1, lease_seconds=1)
        self.assertTrue(
            self.jobs.heartbeat(
                claimed[0].job_id,
                **_lease_args(claimed[0]),
                lease_seconds=60,
            )
        )
        self.assertTrue(
            self.jobs.complete(
                claimed[0].job_id,
                **_lease_args(claimed[0]),
                output_hash="hash",
                output_json={"ok": True},
            )
        )

    def test_heartbeat_after_expiry_is_rejected(self) -> None:
        self.jobs.enqueue(1, self.version_id, self._request())
        claimed = self.jobs.claim(worker_id="w1", limit=1, lease_seconds=1)[0]
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE memory_jobs SET lease_until = ? WHERE job_id = ?",
                (
                    (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                    claimed.job_id,
                ),
            )
        self.assertFalse(
            self.jobs.heartbeat(
                claimed.job_id,
                **_lease_args(claimed),
                lease_seconds=30,
            )
        )

    def test_non_retryable_failure_becomes_failed(self) -> None:
        self.jobs.enqueue(1, self.version_id, self._request(max_attempts=2))
        claimed = self.jobs.claim(worker_id="w1", limit=1, lease_seconds=30)
        status = self.jobs.fail(
            claimed[0].job_id,
            **_lease_args(claimed[0]),
            error=ValueError("bad"),
            retryable=False,
        )
        self.assertEqual(status, JobStatus.FAILED)

    def test_retry_exhaustion_becomes_dead(self) -> None:
        self.jobs.enqueue(1, self.version_id, self._request(max_attempts=1))
        claimed = self.jobs.claim(worker_id="w1", limit=1, lease_seconds=30)
        status = self.jobs.fail(
            claimed[0].job_id,
            **_lease_args(claimed[0]),
            error=RuntimeError("boom"),
            retryable=True,
        )
        self.assertEqual(status, JobStatus.DEAD)

    def test_crashed_final_attempt_becomes_dead_on_reclaim(self) -> None:
        result = self.jobs.enqueue(
            1,
            self.version_id,
            self._request(max_attempts=1),
        )
        claimed = self.jobs.claim(worker_id="w1", limit=1, lease_seconds=1)
        self.assertEqual(len(claimed), 1)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE memory_jobs SET lease_until = ? WHERE job_id = ?",
                (
                    (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                    result.job_id,
                ),
            )
        self.assertEqual(
            self.jobs.claim(worker_id="w2", limit=1, lease_seconds=30),
            [],
        )
        row = self.jobs.get_job(result.job_id)
        assert row is not None
        self.assertEqual(row.status, JobStatus.DEAD)

    def test_retry_backoff_is_bounded(self) -> None:
        from memory.jobs import _retry_delay_seconds

        with patch("memory.jobs.random.uniform", return_value=0):
            self.assertEqual(
                _retry_delay_seconds(attempts=1, base=5, maximum=100),
                5,
            )
            self.assertEqual(
                _retry_delay_seconds(attempts=100, base=5, maximum=100),
                100,
            )

    def test_cancellation_prevents_claim(self) -> None:
        self.jobs.enqueue(1, self.version_id, self._request())
        cancelled = self.jobs.cancel_for_source_version(self.version_id, user_id=1, reason="invalidate")
        self.assertEqual(cancelled, 1)
        self.assertEqual(self.jobs.claim(worker_id="w1", limit=1, lease_seconds=30), [])

    def test_cross_user_enqueue_is_rejected(self) -> None:
        with self.assertRaises(MemoryJobOwnershipError):
            self.jobs.enqueue(2, self.version_id, self._request())

    def test_inactive_version_rejects_enqueue(self) -> None:
        source = self.service.sources.get_version(self.version_id, user_id=1)
        assert source is not None
        self.service.sources.invalidate(source.source_id, user_id=1, reason="forget")
        with self.assertRaises(MemorySourceInactiveError):
            self.jobs.enqueue(1, self.version_id, self._request())

    def test_file_backed_concurrent_claim_has_single_winner(self) -> None:
        self.jobs.enqueue(1, self.version_id, self._request())
        other = MemoryService(config=self.config)
        barrier = threading.Barrier(2)

        def claim(service: MemoryService, worker: str):
            barrier.wait()
            return service.jobs.claim(worker_id=worker, limit=1, lease_seconds=30)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda item: claim(*item),
                    ((self.service, "w1"), (other, "w2")),
                )
            )
        self.assertEqual(sum(len(items) for items in results), 1)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        reset_memory_service()
        self.tmp = tempfile.TemporaryDirectory()
        self.config = _file_config(
            self.tmp,
            worker_enabled=True,
            worker_poll_seconds=0.01,
            job_lease_seconds=30,
        )
        self.service = MemoryService(config=self.config)

    async def asyncTearDown(self) -> None:
        await self.service.stop_worker(grace_seconds=0.1)
        self.tmp.cleanup()

    async def test_start_stop_idempotent(self) -> None:
        await self.service.start_worker()
        await self.service.start_worker()
        await self.service.stop_worker()
        await self.service.stop_worker()

    async def test_disabled_worker_does_not_start(self) -> None:
        disabled_path = str(Path(self.tmp.name) / "disabled.sqlite")
        disabled = MemoryService(
            config=_test_config(
                db_path=disabled_path,
                worker_enabled=False,
            )
        )
        await disabled.start_worker()
        self.assertIsNone(disabled._worker)

    async def test_noop_processor_completes_job(self) -> None:
        job = JobRequest(stage="noop", processor_name="noop", processor_version="1", input_hash="in")
        ingest = self.service.register_source(_source_input(), initial_jobs=[job])
        await self.service.start_worker()
        for _ in range(50):
            job_row = self.service.jobs.get_job(ingest.enqueued_job_ids[0])
            assert job_row is not None
            if job_row.status is JobStatus.DONE:
                break
            await asyncio.sleep(0.02)
        await self.service.stop_worker()
        final = self.service.jobs.get_job(ingest.enqueued_job_ids[0])
        assert final is not None
        self.assertEqual(final.status, JobStatus.DONE)

    async def test_processor_exception_does_not_crash_supervisor(self) -> None:
        class BoomProcessor(NoopProcessor):
            async def process(self, context):  # type: ignore[override]
                raise RuntimeError("processor boom")

        registry = ProcessorRegistry()
        registry.register(BoomProcessor())
        service = MemoryService(config=self.config, registry=registry)
        job = JobRequest(stage="noop", processor_name="noop", processor_version="1", input_hash="in")
        ingest = service.register_source(_source_input(), initial_jobs=[job])
        worker = service._worker = __import__("memory.worker", fromlist=["MemoryWorker"]).MemoryWorker(
            service=service,
            config=self.config,
            registry=registry,
        )
        await worker.start()
        for _ in range(50):
            row = service.jobs.get_job(ingest.enqueued_job_ids[0])
            assert row is not None
            if row.status in {JobStatus.DEAD, JobStatus.FAILED, JobStatus.PENDING}:
                break
            await asyncio.sleep(0.02)
        await worker.stop()
        self.assertFalse(worker.started)
        final = service.jobs.get_job(ingest.enqueued_job_ids[0])
        assert final is not None
        self.assertNotEqual(final.status, JobStatus.DONE)

    async def test_graceful_stop_cancels_slow_processors(self) -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        class SlowProcessor(NoopProcessor):
            name = "slow"
            stages = frozenset({"slow"})

            async def process(self, context):  # type: ignore[override]
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        registry = ProcessorRegistry()
        registry.register(SlowProcessor())
        service = MemoryService(config=self.config, registry=registry)
        job = JobRequest(
            stage="slow",
            processor_name="slow",
            processor_version="1",
            input_hash="slow",
        )
        ingest = service.register_source(
            _source_input(source_ref="chat_message_id:slow"),
            initial_jobs=[job],
        )
        await service.start_worker()
        await asyncio.wait_for(started.wait(), timeout=1)
        await service.stop_worker(grace_seconds=0.01)
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        assert service._worker is not None
        self.assertFalse(service._worker.started)
        self.assertEqual(service._worker.active_job_count, 0)
        final = service.jobs.get_job(ingest.enqueued_job_ids[0])
        assert final is not None
        self.assertEqual(final.status, JobStatus.PENDING)
        reclaimed = service.jobs.claim(
            worker_id="recovery-worker",
            limit=1,
            lease_seconds=30,
        )
        self.assertEqual(len(reclaimed), 1)

    async def test_worker_enforces_concurrency_limit(self) -> None:
        running = 0
        maximum = 0
        two_started = asyncio.Event()
        release = asyncio.Event()

        class BoundedProcessor(NoopProcessor):
            name = "bounded"
            stages = frozenset({"bounded"})

            async def process(self, context):  # type: ignore[override]
                nonlocal running, maximum
                running += 1
                maximum = max(maximum, running)
                if running == 2:
                    two_started.set()
                try:
                    await release.wait()
                    return await super().process(context)
                finally:
                    running -= 1

        registry = ProcessorRegistry()
        registry.register(BoundedProcessor())
        service = MemoryService(config=self.config, registry=registry)
        requests = [
            JobRequest(
                stage="bounded",
                processor_name="bounded",
                processor_version="1",
                input_hash=f"input-{index}",
            )
            for index in range(3)
        ]
        ingest = service.register_source(
            _source_input(source_ref="chat_message_id:bounded"),
            initial_jobs=requests,
        )
        await service.start_worker()
        await asyncio.wait_for(two_started.wait(), timeout=1)
        self.assertEqual(maximum, 2)
        self.assertEqual(service._worker.active_job_count, 2)  # type: ignore[union-attr]
        release.set()
        for _ in range(100):
            rows = [service.jobs.get_job(job_id) for job_id in ingest.enqueued_job_ids]
            if all(row is not None and row.status is JobStatus.DONE for row in rows):
                break
            await asyncio.sleep(0.01)
        await service.stop_worker()
        self.assertEqual(maximum, 2)

    async def test_worker_stage_allowlist_limits_claims(self) -> None:
        from memory.worker import MemoryWorker

        service = MemoryService(config=self.config)
        requests = (
            JobRequest(
                stage="noop",
                processor_name="noop",
                processor_version="1",
                input_hash="allowed",
            ),
            JobRequest(
                stage="blocked",
                processor_name="noop",
                processor_version="1",
                input_hash="blocked",
            ),
        )
        ingest = service.register_source(
            _source_input(source_ref="chat_message_id:allowlist"),
            initial_jobs=requests,
        )
        worker = MemoryWorker(
            service=service,
            config=self.config,
            registry=service.registry,
            stages={"noop"},
        )
        await worker.start()
        for _ in range(50):
            allowed = service.jobs.get_job(ingest.enqueued_job_ids[0])
            if allowed is not None and allowed.status is JobStatus.DONE:
                break
            await asyncio.sleep(0.01)
        await worker.stop()
        allowed = service.jobs.get_job(ingest.enqueued_job_ids[0])
        blocked = service.jobs.get_job(ingest.enqueued_job_ids[1])
        assert allowed is not None and blocked is not None
        self.assertEqual(allowed.status, JobStatus.DONE)
        self.assertEqual(blocked.status, JobStatus.PENDING)


class ProcessorCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.config = _file_config(self.tmp)
        self.service = MemoryService(config=self.config)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _claimed_job(self):
        request = JobRequest(
            stage="noop",
            processor_name="noop",
            processor_version="1",
            input_hash="input",
        )
        ingest = self.service.register_source(
            _source_input(),
            initial_jobs=[request],
        )
        job = self.service.jobs.claim(
            worker_id="worker",
            limit=1,
            lease_seconds=30,
        )[0]
        return ingest, job

    @staticmethod
    def _segment(source_version_id: str) -> SegmentInput:
        return SegmentInput(
            source_version_id=source_version_id,
            segment_type="message",
            ordinal=0,
            text="hello",
            pointer=EvidencePointer(
                pointer_version=1,
                kind="chat_message",
                source_version_id=source_version_id,
                location={"chat_message_id": 1},
            ),
            normalizer_name="noop",
            normalizer_version="1",
            input_hash="segment",
        )

    def test_invalidation_fences_running_processor_commit(self) -> None:
        from memory.ids import make_run_id

        ingest, job = self._claimed_job()
        run_id = make_run_id()
        self.service.record_processor_run_start(run_id=run_id, job=job)
        self.service.sources.invalidate(ingest.source_id, user_id=1, reason="forget")
        committed = self.service.commit_processor_output(
            run_id=run_id,
            job=job,
            worker_id="worker",
            output=ProcessorOutput(
                output_hash="out",
                output_json={"ok": True},
                new_segments=(self._segment(ingest.source_version_id),),
            ),
        )
        self.assertFalse(committed)
        with self.service.db.connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM memory_segments"
            ).fetchone()["c"]
        self.assertEqual(int(count), 0)

    def test_processor_output_transaction_rolls_back_on_bad_lineage(self) -> None:
        from memory.ids import make_run_id
        from memory.models import LineageInput

        ingest, job = self._claimed_job()
        run_id = make_run_id()
        self.service.record_processor_run_start(run_id=run_id, job=job)
        output = ProcessorOutput(
            output_hash="out",
            output_json={"ok": True},
            new_segments=(self._segment(ingest.source_version_id),),
            lineage=(
                LineageInput(
                    parent_kind="source_version",
                    parent_id=ingest.source_version_id,
                    child_kind="segment",
                    child_id="missing-segment",
                    relation=LineageRelation.DERIVED_FROM,
                ),
            ),
        )
        with self.assertRaises(ValueError):
            self.service.commit_processor_output(
                run_id=run_id,
                job=job,
                worker_id="worker",
                output=output,
            )
        with self.service.db.connection() as conn:
            segment_count = int(
                conn.execute("SELECT COUNT(*) AS c FROM memory_segments").fetchone()["c"]
            )
        self.assertEqual(segment_count, 0)
        current = self.service.jobs.get_job(job.job_id)
        assert current is not None
        self.assertEqual(current.status, JobStatus.RUNNING)

    def test_expired_lease_cannot_commit_processor_output(self) -> None:
        from memory.ids import make_run_id

        ingest, job = self._claimed_job()
        run_id = make_run_id()
        self.service.record_processor_run_start(run_id=run_id, job=job)
        with self.service.db.transaction() as conn:
            conn.execute(
                "UPDATE memory_jobs SET lease_until = ? WHERE job_id = ?",
                (
                    (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                    job.job_id,
                ),
            )
        committed = self.service.commit_processor_output(
            run_id=run_id,
            job=job,
            worker_id="worker",
            output=ProcessorOutput(
                output_hash="out",
                output_json={"ok": True},
                new_segments=(self._segment(ingest.source_version_id),),
            ),
        )
        self.assertFalse(committed)
        with self.service.db.connection() as conn:
            count = int(
                conn.execute("SELECT COUNT(*) AS c FROM memory_segments").fetchone()["c"]
            )
        self.assertEqual(count, 0)


class LineageInvalidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MemoryService(config=_file_config(self.tmp))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_invalidation_marks_segment_descendants(self) -> None:
        ingest = self.service.register_source(_source_input())
        pointer = EvidencePointer(
            pointer_version=1,
            kind="chat_message",
            source_version_id=ingest.source_version_id,
            location={"chat_message_id": 1},
        )
        segment = SegmentInput(
            source_version_id=ingest.source_version_id,
            segment_type="message",
            ordinal=0,
            text="hello",
            pointer=pointer,
            normalizer_name="noop",
            normalizer_version="1",
            input_hash="seg",
        )
        self.service.segments.insert_segments([segment], user_id=1, lineage_store=self.service.lineage)
        result = self.service.sources.invalidate(ingest.source_id, user_id=1, reason="forget")
        self.assertGreaterEqual(result.inactive_descendant_count, 1)
        with self.service.db.connection() as conn:
            row = conn.execute(
                "SELECT status FROM memory_segments WHERE source_version_id = ?",
                (ingest.source_version_id,),
            ).fetchone()
        assert row is not None
        self.assertEqual(row["status"], "invalidated")
        repeated = self.service.sources.invalidate(ingest.source_id, user_id=1, reason="forget")
        self.assertEqual(repeated.cancelled_job_count, 0)
        self.assertEqual(repeated.inactive_descendant_count, 0)

    def test_cross_user_segment_and_lineage_writes_fail(self) -> None:
        first = self.service.register_source(_source_input(user_id=1))
        second = self.service.register_source(
            _source_input(
                user_id=2,
                source_ref="chat_message_id:2",
                pointer=_chat_pointer(message_id=2),
            )
        )
        pointer = EvidencePointer(
            pointer_version=1,
            kind="chat_message",
            source_version_id=first.source_version_id,
            location={"chat_message_id": 1},
        )
        segment = SegmentInput(
            source_version_id=first.source_version_id,
            segment_type="message",
            ordinal=0,
            text="hello",
            pointer=pointer,
            normalizer_name="noop",
            normalizer_version="1",
            input_hash="seg",
        )
        with self.assertRaises(PermissionError):
            self.service.segments.insert_segments(
                [segment],
                user_id=2,
                lineage_store=self.service.lineage,
            )
        from memory.models import LineageInput

        with self.assertRaises(PermissionError):
            self.service.lineage.add(
                [
                    LineageInput(
                        parent_kind="source",
                        parent_id=first.source_id,
                        child_kind="source",
                        child_id=second.source_id,
                        relation=LineageRelation.DERIVED_FROM,
                    )
                ],
                user_id=1,
            )

    def test_lineage_cycle_terminates(self) -> None:
        from memory.models import LineageInput

        ingest = self.service.register_source(_source_input())
        self.service.lineage.add(
            [
                LineageInput(
                    parent_kind="source_version",
                    parent_id=ingest.source_version_id,
                    child_kind="source",
                    child_id=ingest.source_id,
                    relation=LineageRelation.DERIVED_FROM,
                )
            ],
            user_id=1,
        )
        descendants = self.service.lineage.descendants(
            "source",
            ingest.source_id,
            user_id=1,
        )
        self.assertGreaterEqual(len(descendants), 2)

    def test_duplicate_lineage_link_is_idempotent(self) -> None:
        from memory.models import LineageInput

        ingest = self.service.register_source(_source_input())
        link = LineageInput(
            parent_kind="source",
            parent_id=ingest.source_id,
            child_kind="source_version",
            child_id=ingest.source_version_id,
            relation=LineageRelation.DERIVED_FROM,
        )
        self.assertEqual(self.service.lineage.add([link], user_id=1), 0)
        self.assertEqual(self.service.lineage.add([link], user_id=1), 0)


class ConfigTests(unittest.TestCase):
    def test_defaults_disabled(self) -> None:
        from config import get_settings

        settings = get_settings()
        self.assertFalse(settings.memory_ingest_enabled)
        self.assertFalse(settings.memory_worker_enabled)

    def test_validate_memory_config(self) -> None:
        with self.assertRaises(ValueError):
            validate_memory_config(_test_config(worker_concurrency=0))

    def test_validate_memory_config_stage_dependencies(self) -> None:
        with self.assertRaises(ValueError):
            validate_memory_config(
                _test_config(worker_enabled=False, extraction_enabled=True)
            )
        with self.assertRaises(ValueError):
            validate_memory_config(
                _test_config(
                    worker_enabled=True,
                    verification_enabled=False,
                    resolution_enabled=True,
                )
            )
        with self.assertRaises(ValueError):
            validate_memory_config(
                _test_config(
                    worker_enabled=True,
                    verification_enabled=True,
                    resolution_enabled=False,
                    graph_enabled=True,
                )
            )
        validate_memory_config(
            _test_config(
                worker_enabled=True,
                verification_enabled=True,
                resolution_enabled=True,
                graph_enabled=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
