"""Live Agent eval for chat memory — smoke gate on pack tier."""

from __future__ import annotations

import os
import unittest

from eval_chat_memory import format_report, run_eval
from eval_memory_corpus.schema import DEFAULT_PACK_PATH, load_pack


class ChatMemoryEvalTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_memory_recall_smoke_pass_rate(self) -> None:
        pack = load_pack(DEFAULT_PACK_PATH)
        smoke_n = len(pack.cases_for_tier("smoke"))
        results, summary = await run_eval(
            with_judge=True,
            source="pack",
            tier="smoke",
        )
        report = format_report(results, summary)
        print("\n" + report)

        self.assertEqual(summary["total"], smoke_n)
        min_pass = float(os.getenv("CHAT_MEMORY_EVAL_MIN_PASS_PCT", "80"))
        self.assertGreaterEqual(
            float(summary["overall_pass_pct"]),
            min_pass,
            msg=report,
        )


if __name__ == "__main__":
    unittest.main()
