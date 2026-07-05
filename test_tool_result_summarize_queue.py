import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from config import get_settings
from llm import LLMClient
from tools.tool_results.collapser import ToolResultCollapser
from tools.tool_results.summarize import (
    SUMMARIZE_STATUS_UNAVAILABLE,
    SUMMARY_UNAVAILABLE,
    apply_summary_unavailable,
    summarize_tool_result,
)
from tools.tool_results.summarize_queue import SummarizeQueue, reset_summarize_queue
from tools.tool_results.store import ToolResultStore, reset_tool_result_store


class SummarizeFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_tool_result_store(ToolResultStore(":memory:"))
        reset_summarize_queue()

    async def test_summarize_failure_sets_unavailable(self) -> None:
        store = ToolResultStore(":memory:")
        ref = store.insert(
            user_id=1,
            run_id="r",
            tool_name="exa.web_search",
            turn=0,
            args_json="{}",
            payload_json='{"tool_name":"exa.web_search","ok":true,"result":{"hits":[]}}',
            ok=True,
            cached=False,
        )
        settings = get_settings()
        llm = LLMClient(settings)
        with patch.object(llm, "chat_without_reasoning", new=AsyncMock(return_value="short")):
            await summarize_tool_result(
                llm,
                settings,
                store,
                ref=ref,
                tool_name="exa.web_search",
                args_json="{}",
                payload_json='{"tool_name":"exa.web_search","ok":true}',
            )
        record = store.get(ref, user_id=1)
        assert record is not None
        self.assertEqual(record.summarize_status, SUMMARIZE_STATUS_UNAVAILABLE)
        self.assertEqual(record.summary, SUMMARY_UNAVAILABLE)

    @patch("tools.tool_results.summarize_queue.summarize_tool_result")
    async def test_collapser_collapses_on_unavailable(self, mock_summarize: AsyncMock) -> None:
        async def _fail(_llm, _settings, store, *, ref, **_kwargs) -> None:
            apply_summary_unavailable(store, ref, summarize_attempts=3)

        mock_summarize.side_effect = _fail

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
        full = json.dumps({"tool_name": "google.drive.list_files", "ok": True, "result": {"x": 1}})
        full += "x" * 200
        collapser.register_tool_message(
            tool_call_id="call1",
            turn=0,
            content=full,
            tool_name="google.drive.list_files",
            args_json="{}",
        )
        if collapser.entries[0].summarize_task:
            await collapser.entries[0].summarize_task

        messages = [{"role": "tool", "tool_call_id": "call1", "content": full}]
        self.assertEqual(await collapser.collapse_all(messages), 1)
        payload = json.loads(messages[0]["content"])
        self.assertTrue(payload["archived"])
        self.assertEqual(payload["summary"], SUMMARY_UNAVAILABLE)

    async def test_summarize_queue_limits_concurrency(self) -> None:
        settings = get_settings()
        queue = SummarizeQueue(max_concurrent=3)
        store = ToolResultStore(":memory:")
        llm = LLMClient(settings)
        active = 0
        peak = 0
        lock = asyncio.Lock()

        async def slow_summarize(_llm, _settings, _store, *, ref, **_kwargs) -> None:
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1
            apply_summary_unavailable(_store, ref, summarize_attempts=0)

        with patch("tools.tool_results.summarize_queue.summarize_tool_result", side_effect=slow_summarize):
            tasks = []
            for index in range(6):
                ref = store.insert(
                    user_id=1,
                    run_id="r",
                    tool_name="exa.web_search",
                    turn=index,
                    args_json="{}",
                    payload_json='{"ok": true}',
                    ok=True,
                    cached=False,
                )
                tasks.append(
                    queue.submit(
                        llm,
                        settings,
                        store,
                        ref=ref,
                        tool_name="exa.web_search",
                        args_json="{}",
                        payload_json='{"ok": true}',
                    )
                )
            await asyncio.gather(*tasks)

        self.assertLessEqual(peak, 3)


if __name__ == "__main__":
    unittest.main()
