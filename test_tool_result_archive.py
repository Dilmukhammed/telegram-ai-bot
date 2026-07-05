import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from config import get_settings
from llm import LLMClient
from tools.context import RunContext, reset_run_context, set_run_context
from tools.tool_results.archive import (
    archived_content_json,
    build_archived_tool_content,
    is_archived_tool_content,
    should_archive_tool_content,
)
from tools.tool_results.collapser import ToolResultCollapser
from tools.tool_results.store import StoredToolResult, ToolResultStore, reset_tool_result_store


async def _fake_summarize(_llm, _settings, store, *, ref, **_kwargs) -> None:
    store.update_summary(
        ref,
        summary="Summary text.",
        summarize_status="ok",
        summarize_attempts=1,
    )


class ToolResultArchiveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_tool_result_store(ToolResultStore(":memory:"))

    def test_should_archive_above_threshold(self) -> None:
        short = json.dumps({"tool_name": "echo.test", "ok": True, "result": {"x": 1}})
        self.assertFalse(should_archive_tool_content(short, min_chars=150))
        long = short + (" " * 200)
        self.assertTrue(should_archive_tool_content(long, min_chars=150))

    def test_archived_content_shape(self) -> None:
        record = StoredToolResult(
            ref="tr_test",
            display_ref=7,
            user_id=1,
            run_id="run1",
            tool_name="exa.web_search",
            turn=0,
            args_json="{}",
            payload_json='{"tool_name":"exa.web_search","ok":true}',
            char_count=100,
            summary="Found lyrics about sadness.",
            summarize_status="ok",
            summarize_attempts=1,
            ok=True,
            cached=False,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),
        )
        payload = build_archived_tool_content(record)
        self.assertEqual(
            payload,
            {
                "archived": True,
                "ref": 7,
                "tool_name": "exa.web_search",
                "ok": True,
                "summary": "Found lyrics about sadness.",
            },
        )
        self.assertTrue(is_archived_tool_content(archived_content_json(record)))

    def test_store_insert_and_get(self) -> None:
        store = ToolResultStore(":memory:")
        ref = store.insert(
            user_id=7,
            run_id="abc",
            tool_name="exa.web_search",
            turn=2,
            args_json='{"query":"x"}',
            payload_json='{"ok": true}',
            ok=True,
            cached=False,
        )
        record = store.get(ref, user_id=7)
        assert record is not None
        self.assertEqual(record.tool_name, "exa.web_search")
        self.assertEqual(record.display_ref, 1)
        self.assertIsNone(record.summary)

    def test_store_display_ref_sequential_per_user(self) -> None:
        store = ToolResultStore(":memory:")
        ref1 = store.insert(
            user_id=1,
            run_id="r",
            tool_name="echo.test",
            turn=0,
            args_json="{}",
            payload_json='{"ok": true}',
            ok=True,
            cached=False,
        )
        ref2 = store.insert(
            user_id=1,
            run_id="r",
            tool_name="echo.test",
            turn=1,
            args_json="{}",
            payload_json='{"ok": true}',
            ok=True,
            cached=False,
        )
        ref3 = store.insert(
            user_id=2,
            run_id="r",
            tool_name="echo.test",
            turn=0,
            args_json="{}",
            payload_json='{"ok": true}',
            ok=True,
            cached=False,
        )
        self.assertEqual(store.get(ref1, user_id=1).display_ref, 1)  # type: ignore[union-attr]
        self.assertEqual(store.get(ref2, user_id=1).display_ref, 2)  # type: ignore[union-attr]
        self.assertEqual(store.get(ref3, user_id=2).display_ref, 1)  # type: ignore[union-attr]
        self.assertEqual(store.get(2, user_id=1).ref, ref2)  # type: ignore[union-attr]
        self.assertEqual(store.get(ref1, user_id=1).ref, ref1)  # type: ignore[union-attr]

    @patch("tools.tool_results.summarize_queue.summarize_tool_result", side_effect=_fake_summarize)
    async def test_collapser_replaces_after_stale_steps(self, _mock: AsyncMock) -> None:
        settings = get_settings()
        llm = LLMClient(settings)
        store = ToolResultStore(":memory:")
        collapser = ToolResultCollapser(
            settings=settings,
            llm=llm,
            user_id=42,
            run_id="run1",
            store=store,
        )
        full = json.dumps(
            {
                "tool_name": "exa.web_search",
                "ok": True,
                "result": {"query": "test", "results": [{"title": "A"}]},
            }
        ) + ("x" * 200)
        collapser.register_tool_message(
            tool_call_id="call1",
            turn=0,
            content=full,
            tool_name="exa.web_search",
            args_json='{"query":"test"}',
        )
        if collapser.entries[0].summarize_task:
            await collapser.entries[0].summarize_task

        messages = [{"role": "tool", "tool_call_id": "call1", "content": full}]
        self.assertEqual(await collapser.collapse_stale(messages, current_turn=9), 0)
        self.assertEqual(await collapser.collapse_stale(messages, current_turn=10), 1)
        self.assertTrue(is_archived_tool_content(messages[0]["content"]))

    @patch("tools.tool_results.summarize_queue.summarize_tool_result")
    async def test_recall_get_collapses_with_existing_summary(self, mock_summarize: AsyncMock) -> None:
        settings = get_settings()
        llm = LLMClient(settings)
        store = ToolResultStore(":memory:")
        collapser = ToolResultCollapser(
            settings=settings,
            llm=llm,
            user_id=42,
            run_id="run1",
            store=store,
        )
        target_ref = store.insert(
            user_id=42,
            run_id="run0",
            tool_name="yandex.music.users_likes_tracks",
            turn=0,
            args_json="{}",
            payload_json='{"tool_name":"yandex.music.users_likes_tracks","ok":true,"result":{"tracks":[]}}',
            ok=True,
            cached=False,
        )
        store.update_summary(
            target_ref,
            summary="117 liked tracks.",
            summarize_status="ok",
            summarize_attempts=1,
        )
        target = store.get(target_ref, user_id=42)
        assert target is not None

        full_get = json.dumps(
            {
                "tool_name": "tool_results.get",
                "ok": True,
                "cached": False,
                "result": {
                    "ok": True,
                    "ref": target.display_ref,
                    "tool_name": target.tool_name,
                    "created_at": target.created_at.isoformat(),
                    "result": {
                        **json.loads(target.payload_json),
                        "padding": "x" * 200,
                    },
                },
            }
        )

        collapser.register_tool_message(
            tool_call_id="call_get",
            turn=0,
            content=full_get,
            tool_name="tool_results.get",
            args_json='{"ref": 1}',
        )
        mock_summarize.assert_not_called()

        messages = [{"role": "tool", "tool_call_id": "call_get", "content": full_get}]
        self.assertEqual(await collapser.collapse_all(messages), 1)
        payload = json.loads(messages[0]["content"])
        self.assertTrue(payload["archived"])
        self.assertEqual(payload["ref"], target.display_ref)
        self.assertEqual(payload["summary"], "117 liked tracks.")
        self.assertEqual(payload["tool_name"], "yandex.music.users_likes_tracks")

    async def test_recall_get_queues_summarize_when_target_unavailable(self) -> None:
        settings = get_settings()
        llm = LLMClient(settings)
        store = ToolResultStore(":memory:")
        collapser = ToolResultCollapser(
            settings=settings,
            llm=llm,
            user_id=42,
            run_id="run1",
            store=store,
        )
        target_ref = store.insert(
            user_id=42,
            run_id="run0",
            tool_name="exa.web_search",
            turn=0,
            args_json="{}",
            payload_json='{"tool_name":"exa.web_search","ok":true,"result":{"hits":[]}}',
            ok=True,
            cached=False,
        )
        from tools.tool_results.summarize import SUMMARIZE_STATUS_UNAVAILABLE, SUMMARY_UNAVAILABLE, apply_summary_unavailable

        apply_summary_unavailable(store, target_ref, summarize_attempts=3)
        target = store.get(target_ref, user_id=42)
        assert target is not None

        full_get = json.dumps(
            {
                "tool_name": "tool_results.get",
                "ok": True,
                "result": {
                    "ok": True,
                    "ref": target.display_ref,
                    "tool_name": target.tool_name,
                    "result": {"hits": [], "padding": "y" * 200},
                },
            }
        )

        with patch("tools.tool_results.summarize_queue.summarize_tool_result") as mock_summarize:
            async def _ok(_llm, _settings, _store, *, ref, **_kwargs) -> None:
                _store.update_summary(
                    ref,
                    summary="Fresh summary from retry.",
                    summarize_status="ok",
                    summarize_attempts=1,
                )

            mock_summarize.side_effect = _ok
            collapser.register_tool_message(
                tool_call_id="call_get2",
                turn=0,
                content=full_get,
                tool_name="tool_results.get",
                args_json='{"ref": 1}',
            )
            self.assertEqual(len(collapser.entries), 1)
            assert collapser.entries[0].summarize_task is not None
            messages = [{"role": "tool", "tool_call_id": "call_get2", "content": full_get}]
            self.assertEqual(await collapser.collapse_all(messages), 1)
            mock_summarize.assert_called_once()

        payload = json.loads(messages[0]["content"])
        self.assertEqual(payload["summary"], "Fresh summary from retry.")

    async def test_tool_results_get_handler(self) -> None:
        from tools.builtins.tool_results_get import _tool_results_get_handler

        store = ToolResultStore(":memory:")
        reset_tool_result_store(store)
        ref = store.insert(
            user_id=99,
            run_id="r1",
            tool_name="exa.web_search",
            turn=0,
            args_json="{}",
            payload_json='{"tool_name":"exa.web_search","ok":true,"result":{"hits":1}}',
            ok=True,
            cached=False,
        )
        store.update_summary(ref, summary="One hit.", summarize_status="ok", summarize_attempts=1)
        token = set_run_context(RunContext(user_id=99))
        try:
            record = store.get(ref, user_id=99)
            assert record is not None
            full = await _tool_results_get_handler({"ref": record.display_ref, "mode": "full"})
            summary = await _tool_results_get_handler({"ref": str(record.display_ref), "mode": "summary"})
            legacy = await _tool_results_get_handler({"ref": ref, "mode": "full"})
        finally:
            reset_run_context(token)
        self.assertTrue(full["ok"])
        self.assertEqual(full["ref"], record.display_ref)
        self.assertEqual(full["result"]["result"]["hits"], 1)
        self.assertEqual(summary["summary"], "One hit.")
        self.assertTrue(legacy["ok"])
        self.assertNotIn("char_count", full)


    def test_expired_ref_not_found(self) -> None:
        store = ToolResultStore(":memory:")
        ref = store.insert(
            user_id=1,
            run_id="r",
            tool_name="echo.test",
            turn=0,
            args_json="{}",
            payload_json='{"ok": true}',
            ok=True,
            cached=False,
        )
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        with store._connect() as conn:
            conn.execute(
                "UPDATE tool_results SET expires_at = ? WHERE ref = ?",
                (past.isoformat(), ref),
            )
            conn.commit()
        self.assertIsNone(store.get(ref, user_id=1))

    def test_purge_expired(self) -> None:
        store = ToolResultStore(":memory:")
        ref = store.insert(
            user_id=1,
            run_id="r",
            tool_name="echo.test",
            turn=0,
            args_json="{}",
            payload_json='{"ok": true}',
            ok=True,
            cached=False,
        )
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        with store._connect() as conn:
            conn.execute(
                "UPDATE tool_results SET expires_at = ? WHERE ref = ?",
                (past.isoformat(), ref),
            )
            conn.commit()
        deleted = store.purge_expired(now=datetime.now(timezone.utc))
        self.assertEqual(deleted, 1)
        self.assertIsNone(store.get(ref, user_id=1))
        self.assertEqual(store.purge_expired(now=datetime.now(timezone.utc)), 0)

    def test_enforce_user_row_caps(self) -> None:
        store = ToolResultStore(":memory:")
        refs = []
        for index in range(5):
            refs.append(
                store.insert(
                    user_id=9,
                    run_id="r",
                    tool_name="echo.test",
                    turn=index,
                    args_json="{}",
                    payload_json=f'{{"i": {index}}}',
                    ok=True,
                    cached=False,
                )
            )
        deleted = store.enforce_user_row_caps(3)
        self.assertEqual(deleted, 2)
        stats = store.user_archive_stats(9)
        self.assertEqual(stats["row_count"], 3)
        remaining = {store.get(ref, user_id=9).ref for ref in refs[-3:]}  # type: ignore[union-attr]
        self.assertEqual(len(remaining), 3)
        self.assertNotIn(refs[0], remaining)

    def test_maintenance_runs_purge(self) -> None:
        from tools.tool_results.maintenance import run_tool_result_maintenance

        store = ToolResultStore(":memory:")
        reset_tool_result_store(store)
        store.insert(
            user_id=1,
            run_id="r",
            tool_name="echo.test",
            turn=0,
            args_json="{}",
            payload_json='{"ok": true}',
            ok=True,
            cached=False,
        )
        with store._connect() as conn:
            conn.execute(
                "UPDATE tool_results SET expires_at = ?",
                ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),),
            )
            conn.commit()
        with patch("tools.tool_results.maintenance.get_settings") as mock_settings:
            mock_settings.return_value.tool_result_archive_enabled = True
            mock_settings.return_value.tool_result_max_rows_per_user = 0
            deleted = run_tool_result_maintenance()
        self.assertEqual(deleted, 1)


if __name__ == "__main__":
    unittest.main()
