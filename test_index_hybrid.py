import os
import unittest
from unittest.mock import patch

from tools.bootstrap import create_tool_runtime


class HybridIndexTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_embedding_prefers_exa_for_web_query(self) -> None:
        env = {
            "TOOL_EMBEDDING_PROVIDER": "local",
            "LOCAL_EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
        }
        with patch.dict(os.environ, env, clear=False):
            runtime = await create_tool_runtime()
            result = await runtime.search_tools(
                "find current news on the internet",
                top_k=3,
            )
            names = [tool["name"] for tool in result["tools"]]
            self.assertIn("exa.web_search", names)
            self.assertNotIn(names[0], {"echo.test"})


if __name__ == "__main__":
    unittest.main()
