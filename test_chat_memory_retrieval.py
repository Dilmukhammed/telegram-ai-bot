import unittest

from eval_chat_memory_retrieval import RETRIEVAL_BENCHMARK, evaluate_provider, summarize


class ChatMemoryRetrievalEvalTests(unittest.IsolatedAsyncioTestCase):
    async def test_keyword_retrieval_has_full_recall_at_five(self) -> None:
        results = await evaluate_provider("keyword", top_k=5)
        metrics = summarize(results)

        self.assertEqual(metrics["total"], len(RETRIEVAL_BENCHMARK))
        self.assertGreaterEqual(metrics["recall_at_3_pct"], 90.0, metrics)
        self.assertGreaterEqual(metrics["recall_at_5_pct"], 100.0, metrics)
        self.assertGreaterEqual(metrics["session_recall_pct"], 100.0, metrics)
        self.assertGreaterEqual(metrics["tool_ref_recall_pct"], 100.0, metrics)


if __name__ == "__main__":
    unittest.main()
