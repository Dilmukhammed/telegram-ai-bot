from __future__ import annotations

import asyncio
import unittest

from tools.context import RunContext
from tools.index import HybridToolIndex
from tools.registry import ToolRegistry
from tools.runtime import ToolHandlerTimeoutError, ToolRuntime
from tools.schema import ToolSpec


class ToolHandlerTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_timeout_raises(self) -> None:
        async def slow(_arguments: dict) -> dict:
            await asyncio.sleep(2)
            return {"ok": True}

        spec = ToolSpec(
            name="echo.slow",
            description="slow",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=slow,
            handler_timeout_seconds=0.05,
            checker_enabled=False,
        )
        registry = ToolRegistry()
        registry.register(spec)
        index = HybridToolIndex(registry, embedding_provider=None)
        runtime = ToolRuntime(registry, index)
        with self.assertRaises(ToolHandlerTimeoutError):
            await runtime.use_tool("echo.slow", {}, RunContext(user_id=1))


if __name__ == "__main__":
    unittest.main()
