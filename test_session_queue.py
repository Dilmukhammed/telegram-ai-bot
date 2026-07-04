import asyncio
import os
import unittest
from dataclasses import dataclass
from unittest.mock import patch


@dataclass
class DummyItem:
    value: int


class SessionQueueManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_burst_collects_rapid_messages(self) -> None:
        from bot.session_queue import SessionQueueManager

        queue: SessionQueueManager[DummyItem] = SessionQueueManager(max_pending=10)
        batches: list[list[int]] = []

        async def process_batch(items: list[DummyItem]) -> None:
            batches.append([item.value for item in items])
            await asyncio.sleep(0.05)

        with patch.dict(os.environ, {"MESSAGE_BURST_QUIET_MS": "50", "MESSAGE_BURST_MAX_WAIT_MS": "300"}):
            for value in (1, 2, 3, 4, 5):
                await queue.submit(1, DummyItem(value), process_batch, lambda: asyncio.sleep(0))

        await asyncio.sleep(0.4)
        self.assertEqual(batches, [[1, 2, 3, 4, 5]])

    async def test_merges_pending_after_current_job(self) -> None:
        from bot.session_queue import SessionQueueManager

        queue: SessionQueueManager[DummyItem] = SessionQueueManager(max_pending=10)
        batches: list[list[int]] = []
        busy_notes: list[int] = []
        release = asyncio.Event()

        async def process_batch(items: list[DummyItem]) -> None:
            values = [item.value for item in items]
            batches.append(values)
            if values == [1]:
                await release.wait()
            else:
                await asyncio.sleep(0.05)

        async def on_busy() -> None:
            busy_notes.append(1)

        with patch.dict(os.environ, {"MESSAGE_BURST_QUIET_MS": "20", "MESSAGE_BURST_MAX_WAIT_MS": "100"}):
            await queue.submit(1, DummyItem(1), process_batch, on_busy)
            await asyncio.sleep(0.05)

            for value in (2, 3, 4, 5, 6):
                await queue.submit(1, DummyItem(value), process_batch, on_busy)

            release.set()

        self.assertEqual(busy_notes, [1, 1, 1, 1, 1])
        await asyncio.sleep(0.3)

        self.assertEqual(batches, [[1], [2, 3, 4, 5, 6]])

    async def test_reset_clears_pending_without_running_them(self) -> None:
        from bot.session_queue import SessionQueueManager

        queue: SessionQueueManager[DummyItem] = SessionQueueManager(max_pending=5)
        started = asyncio.Event()
        release = asyncio.Event()
        batches: list[list[int]] = []

        async def process_batch(items: list[DummyItem]) -> None:
            if len(items) == 1 and items[0].value == 1:
                started.set()
                await release.wait()
            batches.append([item.value for item in items])

        with patch.dict(os.environ, {"MESSAGE_BURST_QUIET_MS": "20", "MESSAGE_BURST_MAX_WAIT_MS": "100"}):
            await queue.submit(7, DummyItem(1), process_batch, lambda: asyncio.sleep(0))
            await started.wait()

            await queue.submit(7, DummyItem(2), process_batch, lambda: asyncio.sleep(0))
            queue.reset(7)
            release.set()

        await asyncio.sleep(0.2)
        self.assertEqual(batches, [[1]])


class MergeChatRequestsTests(unittest.TestCase):
    def test_single_request_unchanged(self) -> None:
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        from bot.chat_request import ChatRequest, merge_chat_requests

        message = MagicMock()
        message.date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        request = ChatRequest(message=message, user_text="hello", image_data_urls=["img"])

        merged = merge_chat_requests([request])
        self.assertEqual(merged[0], message)
        self.assertEqual(merged[1], "hello")
        self.assertEqual(merged[2], ["img"])

    def test_multiple_texts_joined(self) -> None:
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        from bot.chat_request import ChatRequest, merge_chat_requests

        def make_message(value: int):
            message = MagicMock()
            message.date = datetime(2026, 1, value, tzinfo=timezone.utc)
            return message

        requests = [
            ChatRequest(message=make_message(1), user_text="one"),
            ChatRequest(message=make_message(2), user_text="two"),
            ChatRequest(message=make_message(3), user_text="three"),
        ]

        message, text, images, _ = merge_chat_requests(requests)
        self.assertIs(message, requests[-1].message)
        self.assertEqual(text, "one\n\ntwo\n\nthree")
        self.assertIsNone(images)

    def test_telegram_split_joined_without_gap(self) -> None:
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        from bot.chat_request import ChatRequest, merge_chat_requests

        def make_message(value: int):
            message = MagicMock()
            message.date = datetime(2026, 1, value, tzinfo=timezone.utc)
            return message

        part_a = "a" * 4096
        part_b = "b" * 500
        requests = [
            ChatRequest(message=make_message(1), user_text=part_a),
            ChatRequest(message=make_message(2), user_text=part_b),
        ]

        _, text, _, _ = merge_chat_requests(requests)
        self.assertEqual(text, part_a + part_b)


if __name__ == "__main__":
    unittest.main()
