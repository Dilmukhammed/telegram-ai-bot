"""Offline integration tests for chat memory: persist, RAG index, chat tools, tool_results."""

from __future__ import annotations

import json
import os
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from agent.run_trace import RunTrace
from bot.chat_index.sync import index_session_messages, index_session_summary, rebuild_user_index
from bot.chat_service import ChatService
from bot.chat_store import ChatStore, reset_chat_store
from bot.chat_store.summary import summarize_archived_session
from tools.bootstrap import create_tool_runtime
from tools.context import RunContext, reset_run_context, set_run_context
from tools.tool_results.archive import archived_content_json
from tools.tool_results.store import ToolResultStore, reset_tool_result_store

FAKE_USER = 123456
OTHER_USER = 999999
MARKER = "MemoryFlowMarkerX7K9"
SECRET_ID = "SECRET_CAFE_LIST_ID_884422"

_TEST_ENV = {
    "CHAT_DB_PATH": ":memory:",
    "TOOL_RESULT_DB_PATH": ":memory:",
    "TOOL_EMBEDDING_PROVIDER": "keyword",
    "CHAT_SESSION_SUMMARY_ON_ARCHIVE": "1",
    "CHAT_INDEX_ON_STARTUP": "0",
}


def _tool_result_payload(*, secret: str = SECRET_ID) -> dict:
    return {
        "tool_name": "exa.web_search",
        "ok": True,
        "result": {
            "query": f"cafes Tashkent {MARKER}",
            "items": [
                {"name": "Cafe Alpha", "place_id": secret},
                {"name": "Cafe Beta", "place_id": "place_beta_002"},
            ],
        },
    }


def _use_tool_exchange(
    *,
    tool_name: str,
    tool_args: dict,
    tool_content: str,
    call_id: str = "call_mem_1",
) -> list[dict]:
    return [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "use_tool",
                        "arguments": json.dumps(
                            {"tool_name": tool_name, "arguments": tool_args},
                            ensure_ascii=False,
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "content": tool_content,
        },
    ]


class ChatMemoryFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._env_patch = patch.dict(os.environ, _TEST_ENV, clear=False)
        self._env_patch.start()
        self.chat_store = ChatStore(":memory:")
        self.tool_store = ToolResultStore(":memory:")
        reset_chat_store(self.chat_store)
        reset_tool_result_store(self.tool_store)
        self.runtime = await create_tool_runtime()
        self.ctx = RunContext(user_id=FAKE_USER, turn=1, meta_tool="use_tool")
        self._ctx_token = set_run_context(self.ctx)
        self.chat_service = ChatService(MagicMock(), chat_store=self.chat_store)

    async def asyncTearDown(self) -> None:
        reset_run_context(self._ctx_token)
        self._env_patch.stop()

    def _reindex(self, user_id: int = FAKE_USER) -> None:
        rebuild_user_index(self.chat_store, user_id, clear_existing=True)

    def _seed_turn(
        self,
        user_text: str,
        worker_history: list[dict],
        *,
        assistant_reply: str | None = None,
        trace: RunTrace | None = None,
    ) -> str:
        at = datetime.now(timezone.utc)
        self.chat_service.append_turn_messages(
            FAKE_USER,
            [{"role": "user", "content": user_text}, *worker_history],
            user_message_at=at,
        )
        session = self.chat_store.get_active_session(FAKE_USER)
        assert session is not None
        if trace is not None:
            self.chat_store.append_session_trace(
                session.session_id,
                FAKE_USER,
                trace=trace,
                assistant_reply=assistant_reply or user_text,
                source_at=at,
            )
        index_session_messages(self.chat_store, session.session_id)
        return session.session_id

    def _insert_archived_tool_result(
        self,
        *,
        turn: int,
        summary: str,
        payload: dict | None = None,
    ):
        payload = payload or _tool_result_payload()
        ref = self.tool_store.insert(
            user_id=FAKE_USER,
            run_id="mem_test_run",
            tool_name="exa.web_search",
            turn=turn,
            args_json=json.dumps({"query": f"Tashkent cafes {MARKER}"}),
            payload_json=json.dumps(payload, ensure_ascii=False),
            ok=True,
            cached=False,
        )
        self.tool_store.update_summary(
            ref,
            summary=summary,
            summarize_status="ok",
            summarize_attempts=1,
        )
        record = self.tool_store.get(ref, user_id=FAKE_USER)
        assert record is not None
        return record

    async def _use_chat_tool(self, tool_name: str, arguments: dict, *, user_id: int = FAKE_USER):
        ctx = RunContext(user_id=user_id, turn=1, meta_tool="use_tool")
        envelope = await self.runtime.use_tool(tool_name, arguments, ctx=ctx)
        self.assertTrue(envelope["ok"], msg=envelope)
        return envelope["result"]

    async def test_persist_turns_and_read(self) -> None:
        session_id = self._seed_turn(
            f"Remember {MARKER} for later",
            [{"role": "assistant", "content": f"Saved note about {MARKER}."}],
        )
        self._seed_turn(
            "Second question about weather",
            [{"role": "assistant", "content": "It is sunny today."}],
        )
        self._reindex()

        result = await self._use_chat_tool(
            "chat.turns.read",
            {"session_id": session_id, "turns": [1, 2]},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["turns"]), 2)
        turn1_text = json.dumps(result["turns"][0]["messages"], ensure_ascii=False)
        self.assertIn(MARKER, turn1_text)

    async def test_search_finds_message_chunks(self) -> None:
        session_id = self._seed_turn(
            f"Find cafes in Tashkent {MARKER}",
            [{"role": "assistant", "content": f"Here are cafes matching {MARKER}."}],
        )
        self._reindex()

        hits = await self._use_chat_tool(
            "chat.search",
            {"query": MARKER, "session_id": session_id},
        )
        self.assertTrue(hits["ok"])
        self.assertGreater(hits["count"], 0)
        self.assertTrue(any(MARKER in hit.get("text", "") for hit in hits["hits"]))

    async def test_tool_result_search_and_get(self) -> None:
        record = self._insert_archived_tool_result(
            turn=1,
            summary=f"Found two Tashkent cafes for {MARKER}",
        )
        archived = archived_content_json(record)
        session_id = self._seed_turn(
            f"Search cafes {MARKER}",
            [
                *_use_tool_exchange(
                    tool_name="exa.web_search",
                    tool_args={"query": f"Tashkent cafes {MARKER}"},
                    tool_content=archived,
                ),
                {
                    "role": "assistant",
                    "content": f"Found cafes; archived ref {record.display_ref}.",
                },
            ],
        )
        self._reindex()

        search = await self._use_chat_tool(
            "chat.search",
            {"query": MARKER, "session_id": session_id},
        )
        self.assertTrue(search["ok"])
        tool_refs = {hit["tool_ref"] for hit in search["hits"] if hit.get("tool_ref")}
        self.assertIn(record.display_ref, tool_refs)

        got = await self._use_chat_tool(
            "tool_results.get",
            {"ref": record.display_ref, "mode": "full"},
        )
        self.assertTrue(got["ok"])
        payload_text = json.dumps(got["result"], ensure_ascii=False)
        self.assertIn(SECRET_ID, payload_text)

    async def test_cross_session_tool_ref_survives_archive(self) -> None:
        record = self._insert_archived_tool_result(
            turn=1,
            summary=f"Cross-session cafe search {MARKER}",
        )
        archived = archived_content_json(record)
        session1_id = self._seed_turn(
            f"First session cafes {MARKER}",
            [
                *_use_tool_exchange(
                    tool_name="exa.web_search",
                    tool_args={"query": MARKER},
                    tool_content=archived,
                    call_id="call_sess1",
                ),
                {"role": "assistant", "content": "Stored cafe list."},
            ],
            trace=RunTrace(
                user_id=FAKE_USER,
                user_message=f"First session cafes {MARKER}",
                started_at=time.time(),
                final_outcome="success",
                successful_tools=["exa.web_search"],
            ),
        )
        self._reindex()

        archived_session, session2 = self.chat_store.archive_and_create_active(
            FAKE_USER,
            closed_by="new_chat",
        )
        assert archived_session is not None
        self.assertEqual(archived_session.session_id, session1_id)
        self.assertEqual(archived_session.status, "archived")
        self.assertEqual(session2.status, "active")

        self._seed_turn(
            "New session question",
            [{"role": "assistant", "content": "Hello from session two."}],
        )
        self._reindex()

        search = await self._use_chat_tool(
            "chat.search",
            {"query": MARKER},
        )
        self.assertTrue(search["ok"])
        session_ids = {hit["session_id"] for hit in search["hits"]}
        self.assertIn(session1_id, session_ids)

        got = await self._use_chat_tool(
            "tool_results.get",
            {"ref": record.display_ref, "mode": "full"},
        )
        self.assertTrue(got["ok"])
        self.assertIn(SECRET_ID, json.dumps(got["result"], ensure_ascii=False))

    async def test_user_isolation(self) -> None:
        session_id = self._seed_turn(
            f"Private note {MARKER}",
            [{"role": "assistant", "content": "Private reply."}],
        )
        self._reindex()

        denied = await self._use_chat_tool(
            "chat.turns.read",
            {"session_id": session_id, "turns": 1},
            user_id=OTHER_USER,
        )
        self.assertFalse(denied["ok"])
        self.assertIn("not found", denied["error"].lower())

        denied_search = await self._use_chat_tool(
            "chat.search",
            {"query": MARKER, "session_id": session_id},
            user_id=OTHER_USER,
        )
        self.assertFalse(denied_search["ok"])

    async def test_archive_session_summary_real_llm(self) -> None:
        session_id = self._seed_turn(
            f"Plan a trip to Tashkent {MARKER}",
            [{"role": "assistant", "content": f"Trip plan for {MARKER} is ready."}],
            assistant_reply=f"Trip plan for {MARKER} is ready.",
            trace=RunTrace(
                user_id=FAKE_USER,
                user_message=f"Plan a trip to Tashkent {MARKER}",
                started_at=time.time(),
                final_outcome="success",
                successful_tools=["exa.web_search"],
                progress_summary=f"User asked about Tashkent trip ({MARKER}).",
            ),
        )
        archived, _new_active = self.chat_store.archive_and_create_active(
            FAKE_USER,
            closed_by="new_chat",
        )
        assert archived is not None
        self.assertEqual(archived.session_id, session_id)

        await summarize_archived_session(self.chat_store, session_id)

        session = self.chat_store.get_session_for_user(session_id, FAKE_USER)
        assert session is not None
        self.assertEqual(session.summary_status, "done")
        self.assertIsNotNone(session.summary)
        self.assertGreater(len(session.summary or ""), 40)
        self.assertIsNotNone(session.title)

        index_session_summary(self.chat_store, session_id)
        self._reindex()

        summary_tool = await self._use_chat_tool(
            "chat.session.summary",
            {"session_id": session_id},
        )
        self.assertTrue(summary_tool["ok"])
        self.assertEqual(summary_tool["session"]["summary_status"], "done")
        self.assertGreater(len(summary_tool["session"]["summary"] or ""), 40)

        search = await self._use_chat_tool(
            "chat.search",
            {"query": f"Tashkent trip {MARKER}"},
        )
        self.assertTrue(search["ok"])
        self.assertGreater(search["count"], 0)


if __name__ == "__main__":
    unittest.main()
