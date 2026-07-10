import os
import unittest
from unittest.mock import patch

from bot.chat_index.chunking import tokenize
from bot.chat_index.search import (
    reset_chat_search_embedding_provider,
    search_chat_chunks,
)
from bot.chat_index.sync import index_session_messages
from bot.chat_store import ChatStore, reset_chat_store


class ChatSearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "TOOL_EMBEDDING_PROVIDER": "keyword",
                "CHAT_SEARCH_TOP_K": "5",
                "CHAT_SEARCH_MAX_PER_SESSION": "5",
            },
            clear=False,
        )
        self._env.start()
        self.store = ChatStore(":memory:")
        reset_chat_store(self.store)
        reset_chat_search_embedding_provider()

    def tearDown(self) -> None:
        reset_chat_search_embedding_provider()
        self._env.stop()

    def _append_turn(self, session_id: str, user_id: int, user: str, assistant: str) -> None:
        self.store.append_messages(
            session_id,
            user_id,
            [
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            ],
        )

    def test_unicode_tokenizer_handles_cyrillic_and_identifiers(self) -> None:
        tokens = tokenize("Любимый цвет MEMEVAL_COLOR_Cobalt99")
        self.assertIn("любимый", tokens)
        self.assertIn("цвет", tokens)
        self.assertIn("memeval_color_cobalt99", tokens)
        self.assertIn("cobalt99", tokens)

    async def test_russian_query_finds_russian_memory(self) -> None:
        user_id = 123456
        session = self.store.get_or_create_active_session(user_id)
        self._append_turn(
            session.session_id,
            user_id,
            "Мой любимый город — Самарканд.",
            "Запомнил: любимый город Самарканд.",
        )
        self._append_turn(
            session.session_id,
            user_id,
            "Расскажи о погоде.",
            "Сегодня солнечно.",
        )
        index_session_messages(self.store, session.session_id)

        hits = await search_chat_chunks(user_id, "какой мой любимый город", top_k=5)

        self.assertTrue(hits)
        self.assertIn("Самарканд", hits[0]["turn_context"])
        self.assertEqual(hits[0]["turn_number"], 1)

    async def test_results_are_diverse_by_turn_and_include_context(self) -> None:
        user_id = 123456
        session = self.store.get_or_create_active_session(user_id)
        for index in range(1, 4):
            self._append_turn(
                session.session_id,
                user_id,
                f"Проект Небула, заметка {index}.",
                f"Ответ по проекту Небула, часть {index}.",
            )
        index_session_messages(self.store, session.session_id)

        hits = await search_chat_chunks(user_id, "проект Небула", top_k=3)

        self.assertEqual(len(hits), 3)
        self.assertEqual(len({hit["turn_number"] for hit in hits}), 3)
        self.assertTrue(all("user:" in (hit["turn_context"] or "") for hit in hits))
        self.assertTrue(all("assistant:" in (hit["turn_context"] or "") for hit in hits))


if __name__ == "__main__":
    unittest.main()
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from bot.chat_index.sync import index_session_messages, rebuild_user_index
from bot.chat_index.turns import parse_turn_spec
from bot.chat_store import ChatStore, reset_chat_store
from tools.bootstrap import create_tool_runtime
from tools.context import RunContext


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class ChatSearchToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.store = ChatStore(db_path=":memory:")
        reset_chat_store(self.store)
        self.user_id = 9001
        self.t1 = _utc(2026, 7, 9, 10, 0)

    def tearDown(self) -> None:
        reset_chat_store(None)

    def _seed_session(self) -> str:
        session = self.store.get_or_create_active_session(self.user_id)
        self.store.append_messages(
            session.session_id,
            self.user_id,
            [
                {"role": "user", "content": "find cafes in Tashkent"},
                {"role": "assistant", "content": "Here are three cafes near Amir Timur."},
                {"role": "user", "content": "budget is 5000 UZS"},
                {"role": "assistant", "content": "Noted the budget."},
            ],
            default_source_at=self.t1,
        )
        self.store.update_session_summary_status(
            session.session_id,
            summary="User searched Tashkent cafes and set a budget.",
            summary_status="done",
        )
        rebuild_user_index(self.store, self.user_id)
        return session.session_id

    async def _runtime(self):
        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            return await create_tool_runtime()

    async def test_chat_search_finds_chunk(self) -> None:
        session_id = self._seed_session()
        runtime = await self._runtime()
        payload = await runtime.use_tool(
            "chat.search",
            {"query": "Tashkent cafes", "top_k": 5},
            ctx=RunContext(user_id=self.user_id),
        )
        self.assertTrue(payload["ok"])
        result = payload["result"]
        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["hits"][0]["session_id"], session_id)
        self.assertIn("session_summary", result["hits"][0])

    async def test_chat_search_date_filter(self) -> None:
        self._seed_session()
        runtime = await self._runtime()
        payload = await runtime.use_tool(
            "chat.search",
            {"query": "budget", "date": "2026-07-09"},
            ctx=RunContext(user_id=self.user_id),
        )
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["result"]["count"], 1)

    async def test_chat_turns_read_range_and_list(self) -> None:
        session_id = self._seed_session()
        runtime = await self._runtime()

        ranged = await runtime.use_tool(
            "chat.turns.read",
            {"session_id": session_id, "turns": [1, 2]},
            ctx=RunContext(user_id=self.user_id),
        )
        self.assertTrue(ranged["ok"])
        self.assertEqual(ranged["result"]["count"], 2)
        self.assertEqual(ranged["result"]["turns"][0]["turn"], 1)
        self.assertEqual(ranged["result"]["turns"][0]["messages"][0]["role"], "user")

        single = await runtime.use_tool(
            "chat.turns.read",
            {"session_id": session_id, "turns": 2},
            ctx=RunContext(user_id=self.user_id),
        )
        self.assertTrue(single["ok"])
        self.assertEqual(single["result"]["count"], 1)

    async def test_parse_turn_spec(self) -> None:
        self.assertEqual(parse_turn_spec(3), [3])
        self.assertEqual(parse_turn_spec([2, 4]), [2, 3, 4])
        self.assertEqual(parse_turn_spec([1, 3, 5]), [1, 3, 5])

    async def test_session_summary_still_works(self) -> None:
        session_id = self._seed_session()
        runtime = await self._runtime()
        payload = await runtime.use_tool(
            "chat.session.summary",
            {"session_id": session_id},
            ctx=RunContext(user_id=self.user_id),
        )
        self.assertTrue(payload["ok"])
        self.assertIn("Tashkent", payload["result"]["session"]["summary"])


class ChatIndexSyncTests(unittest.TestCase):
    def test_index_session_messages_creates_chunks(self) -> None:
        store = ChatStore(db_path=":memory:")
        user_id = 77
        session = store.get_or_create_active_session(user_id)
        store.append_messages(
            session.session_id,
            user_id,
            [{"role": "user", "content": "hello indexing"}],
            default_source_at=_utc(2026, 7, 9, 12, 0),
        )
        count = index_session_messages(store, session.session_id)
        self.assertGreaterEqual(count, 1)
        with store._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM chat_search_chunks WHERE session_id = ?",
                (session.session_id,),
            ).fetchone()
        self.assertGreaterEqual(int(row["count"]), 1)

    def test_tool_result_payload_chunks(self) -> None:
        from bot.chat_index.chunking import chunks_for_tool_result

        session = ChatStore(db_path=":memory:").get_or_create_active_session(88)
        chunks = chunks_for_tool_result(
            user_id=88,
            session_id=session.session_id,
            session=session,
            display_ref=7,
            tool_name="exa.web_search",
            summary="Three cafe results",
            payload_json='{"ok": true, "results": [{"title": "Cafe A"}]}',
        )
        types = {chunk["source_type"] for chunk in chunks}
        self.assertIn("tool_result", types)
        self.assertIn("tool_result_payload", types)


if __name__ == "__main__":
    unittest.main()
