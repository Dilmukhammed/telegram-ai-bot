from __future__ import annotations

import time
import unittest
from unittest.mock import AsyncMock, patch

from tools.builtins.agent_wait import AGENT_WAIT_TOOL, _MAX_SECONDS


class AgentWaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_short(self) -> None:
        started = time.monotonic()
        result = await AGENT_WAIT_TOOL.handler({"seconds": 0.6, "reason": "unit"})
        elapsed = time.monotonic() - started
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(elapsed, 0.55)
        self.assertEqual(result["reason"], "unit")

    async def test_caps_max_without_long_sleep(self) -> None:
        with patch("tools.builtins.agent_wait.asyncio.sleep", new_callable=AsyncMock) as sleep:
            capped = await AGENT_WAIT_TOOL.handler({"seconds": 9999})
        self.assertEqual(capped["waited_seconds"], _MAX_SECONDS)
        sleep.assert_awaited_once_with(_MAX_SECONDS)

    def test_registered_name(self) -> None:
        self.assertEqual(AGENT_WAIT_TOOL.name, "agent.wait")
        self.assertFalse(AGENT_WAIT_TOOL.checker_enabled)


if __name__ == "__main__":
    unittest.main()
