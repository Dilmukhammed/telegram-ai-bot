from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone

from bot.chat_store.store import ChatStore
from bot.memory_chat_adapter import (
    ChatEvidenceAdapter,
    notify_chat_ingested,
    set_text_ingest_sink,
)
from memory.config import MemoryConfig
from memory.ids import make_source_id, make_source_version_id
from memory.ingestion.builders import (
    chat_content_hash,
    chat_source_input,
    tool_content_hash,
    tool_source_input,
)
from memory.ingestion.chunking import chunk_text
from memory.ingestion.models import ChatEvidenceRecord, ToolCursor, ToolEvidenceRecord
from memory.ingestion.runtime import TextIngestionRuntime
from memory.service import MemoryService
from tools.tool_results.memory_adapter import ToolEvidenceAdapter, ToolMemoryLifecycleObserver
from tools.tool_results.store import ToolResultStore, reset_tool_result_store


def _ingest_config(db_path: str) -> MemoryConfig:
    return MemoryConfig(
        ingest_enabled=True,
        db_path=db_path,
        worker_enabled=False,
        worker_concurrency=1,
        worker_poll_seconds=0.1,
        job_lease_seconds=30,
        job_max_attempts=3,
        job_retry_base_seconds=0.1,
        job_retry_max_seconds=1.0,
        job_claim_batch_size=5,
        ingest_queue_maxsize=10,
        ingest_scan_interval_seconds=60.0,
        ingest_scan_batch_size=50,
        ingest_failure_max_attempts=3,
        ingest_retry_base_seconds=0.1,
        ingest_retry_max_seconds=1.0,
        text_segment_chars=20,
        text_segment_overlap=5,
        tool_reconcile_batch_size=20,
        ingest_shutdown_grace_seconds=1.0,
    )


def _chat_record(
    *,
    message_id: int = 1,
    user_id: int = 7,
    role: str = "user",
    content: str = "hello",
    content_type: str = "text",
) -> ChatEvidenceRecord:
    now = datetime.now(timezone.utc)
    return ChatEvidenceRecord(
        message_id=message_id,
        session_id="sess1",
        user_id=user_id,
        seq=1,
        role=role,
        content=content,
        content_type=content_type,
        tool_call_id=None,
        tool_name=None,
        source_at=now,
        created_at=now,
        metadata={},
    )


def _tool_record(
    *,
    ref: str = "tr_abc",
    user_id: int = 7,
    payload_json: str = '{"ok":true}',
    payload_kind: str = "result",
) -> ToolEvidenceRecord:
    now = datetime.now(timezone.utc)
    return ToolEvidenceRecord(
        ref=ref,
        display_ref=1,
        user_id=user_id,
        run_id="run1",
        tool_name="echo.test",
        turn=0,
        payload_kind=payload_kind,
        payload_json=payload_json,
        args_json="{}",
        ok=True,
        cached=False,
        created_at=now,
        expires_at=now,
    )


class IdentityTests(unittest.TestCase):
    def test_chat_source_ids_stable(self) -> None:
        record = _chat_record()
        first = chat_source_input(record)
        second = chat_source_input(record)
        self.assertEqual(first.source_ref, second.source_ref)
        self.assertEqual(first.content_hash, second.content_hash)
        source_id = make_source_id(
            user_id=record.user_id,
            source_type="chat_message",
            source_ref=first.source_ref,
        )
        version_id = make_source_version_id(
            source_id=source_id,
            content_hash=first.content_hash,
        )
        self.assertTrue(source_id.startswith("msrc_"))
        self.assertTrue(version_id.startswith("msv_"))

    def test_tool_hash_uses_raw_payload_bytes(self) -> None:
        record = _tool_record(payload_json='{"a":1}')
        self.assertEqual(tool_content_hash(record), tool_content_hash(record))
        changed = _tool_record(payload_json='{"a":2}')
        self.assertNotEqual(tool_content_hash(record), tool_content_hash(changed))

    def test_authority_classes_distinct(self) -> None:
        result = tool_source_input(_tool_record(payload_kind="result"))
        args = tool_source_input(_tool_record(payload_kind="arguments"))
        legacy = tool_source_input(_tool_record(payload_kind="unknown_legacy"))
        self.assertEqual(result.authority_class, "tool_api_result")
        self.assertEqual(args.authority_class, "assistant_tool_arguments")
        self.assertEqual(legacy.authority_class, "legacy_tool_archive_unknown")


class ChunkingTests(unittest.TestCase):
    def test_chunk_boundaries_deterministic(self) -> None:
        text = "abcdefghijklmnopqrstuvwxyz"
        chunks = chunk_text(text, chunk_size=10, overlap=2)
        self.assertEqual(chunks[0].char_start, 0)
        self.assertEqual(chunks[0].text, text[0:10])
        self.assertEqual(chunks[-1].char_end, len(text))
        again = chunk_text(text, chunk_size=10, overlap=2)
        self.assertEqual(
            [(c.char_start, c.char_end, c.text) for c in chunks],
            [(c.char_start, c.char_end, c.text) for c in again],
        )


class ToolStoreReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_tool_result_store(ToolResultStore(":memory:"))
        self.store = ToolResultStore(":memory:")

    def test_scan_head_and_read_after(self) -> None:
        ref1 = self.store.insert(
            user_id=1,
            run_id=None,
            tool_name="a",
            turn=0,
            args_json=None,
            payload_json='{"one":1}',
            ok=True,
            cached=False,
            payload_kind="result",
        )
        ref2 = self.store.insert(
            user_id=1,
            run_id=None,
            tool_name="b",
            turn=1,
            args_json=None,
            payload_json='{"two":2}',
            ok=True,
            cached=False,
            payload_kind="arguments",
        )
        head = self.store.scan_head()
        self.assertIn(head.ref, {ref1, ref2})
        rows = self.store.read_after(ToolCursor(created_at="", ref=""), limit=10)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.ref for row in rows}, {ref1, ref2})


class IngestionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.chat_db = os.path.join(self._tmp.name, "chat.sqlite")
        self.tool_db = os.path.join(self._tmp.name, "tool_results.sqlite")
        self.memory_db = os.path.join(self._tmp.name, "memory.sqlite")

        self.chat_store = ChatStore(self.chat_db)
        reset_tool_result_store(ToolResultStore(self.tool_db))
        self.tool_store = ToolResultStore(self.tool_db)

        self.memory = MemoryService(
            db_path=self.memory_db,
            config=_ingest_config(self.memory_db),
        )
        self.runtime = TextIngestionRuntime(
            service=self.memory,
            config=_ingest_config(self.memory_db),
            chat_reader=ChatEvidenceAdapter(self.chat_store),
            tool_reader=ToolEvidenceAdapter(self.tool_store),
        )

    async def asyncTearDown(self) -> None:
        await self.runtime.stop(grace_seconds=0.5)
        reset_tool_result_store(None)

    async def test_first_enable_baseline_skips_historical_chat(self) -> None:
        session = self.chat_store.get_or_create_active_session(7)
        self.chat_store.append_messages(
            session.session_id,
            7,
            [{"role": "user", "content": "old"}],
        )
        await self.runtime.start()
        with self.memory.db.connection() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM memory_sources").fetchone()["c"]
        self.assertEqual(int(count), 0)
        try:
            session = self.chat_store.get_or_create_active_session(7)
            ids = self.chat_store.append_messages(
                session.session_id,
                7,
                [{"role": "user", "content": "new"}],
            )
            self.runtime.sink.notify_chat_messages(user_id=7, message_ids=ids)
            await asyncio.sleep(0.3)
            with self.memory.db.connection() as conn:
                count = conn.execute("SELECT COUNT(*) AS c FROM memory_sources").fetchone()["c"]
            self.assertEqual(int(count), 1)
        finally:
            await self.runtime.stop(grace_seconds=0.5)

    async def test_tool_delete_invalidates_source(self) -> None:
        await self.runtime.start()
        try:
            ref = self.tool_store.insert(
                user_id=9,
                run_id="r",
                tool_name="echo.test",
                turn=0,
                args_json=None,
                payload_json='{"ok":true}',
                ok=True,
                cached=False,
                payload_kind="result",
            )
            self.runtime.sink.notify_tool_inserted(user_id=9, ref=ref)
            await asyncio.sleep(0.3)
            source_ref = f"tool_result_ref:9:{ref}"
            source_id = make_source_id(user_id=9, source_type="tool_result", source_ref=source_ref)
            source = self.memory.sources.get_source(source_id, user_id=9)
            self.assertIsNotNone(source)

            self.runtime.sink.notify_tool_deleted(user_id=9, ref=ref)
            await asyncio.sleep(0.3)
            source = self.memory.sources.get_source(source_id, user_id=9)
            self.assertIsNotNone(source)
            self.assertEqual(source.status.value, "invalidated")
        finally:
            await self.runtime.stop(grace_seconds=0.5)

    async def test_observer_exception_does_not_fail_insert(self) -> None:
        class BrokenObserver:
            def inserted(self, *, user_id: int, ref: str) -> None:
                raise RuntimeError("boom")

            def deleted(self, *, user_id: int, ref: str, reason: str) -> None:
                raise RuntimeError("boom")

        self.tool_store.set_lifecycle_observer(BrokenObserver())
        ref = self.tool_store.insert(
            user_id=3,
            run_id=None,
            tool_name="echo.test",
            turn=0,
            args_json=None,
            payload_json='{"ok":true}',
            ok=True,
            cached=False,
        )
        self.assertTrue(ref.startswith("tr_"))


class NotifyHookTests(unittest.TestCase):
    def test_notify_noop_without_sink(self) -> None:
        set_text_ingest_sink(None)
        notify_chat_ingested(user_id=1, message_ids=[1, 2])


if __name__ == "__main__":
    unittest.main()
