import os
import unittest
from unittest.mock import patch

from eval_tool_search import _eval_runtime, _summarize
from eval_tool_search_benchmark import TOOL_SEARCH_BENCHMARK
from tools.bootstrap import create_tool_runtime


class ToolSearchEvalTests(unittest.IsolatedAsyncioTestCase):
    async def test_keyword_baseline_has_reasonable_coverage(self) -> None:
        """Fast offline smoke: keyword-only search should hit many obvious cases."""
        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            runtime = await create_tool_runtime()
        results = await _eval_runtime(runtime, top_k=5)
        summary = _summarize(results)
        self.assertGreaterEqual(summary["hit_at_5_pct"], 40.0, summary)
        self.assertGreaterEqual(summary["total"], len(TOOL_SEARCH_BENCHMARK))


if __name__ == "__main__":
    unittest.main()
