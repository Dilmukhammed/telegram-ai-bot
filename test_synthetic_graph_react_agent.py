from __future__ import annotations

import asyncio
import unittest

from scripts.run_synthetic_graph_react_agent import AgentResponseError, MAX_ACTIONS, Tools, _decode_action, markdown_report, run_agent


class SyntheticGraphReactAgentTests(unittest.TestCase):
    def test_tools_are_bounded_and_can_traverse_multiple_hops(self) -> None:
        tools = Tools()
        found = tools.search_entities(query="pizza")
        self.assertLessEqual(len(found["hits"]), 10)
        self.assertEqual(found["hits"][0]["entity_id"], "e_pizza")

        paths = tools.traverse_graph(entity_id="e_pizza", max_hops=9, limit=99)
        self.assertLessEqual(len(paths["paths"]), 10)
        self.assertTrue(all(path["hops"] <= 3 for path in paths["paths"]))
        self.assertTrue(any(path["target_id"] == "e_italian" for path in paths["paths"]))

    def test_offline_react_trace_is_read_only_and_reported(self) -> None:
        report = asyncio.run(run_agent(offline_demo=True))
        self.assertLessEqual(len(report["trace"]), MAX_ACTIONS)
        self.assertFalse(report["write_performed"])
        self.assertEqual(report["final"]["decision"], "abstain")
        self.assertEqual(report["final"]["rejected_candidates"][0]["target_id"], "g_italian")
        self.assertIsNone(report["agent_report"]["error"])
        self.assertIn("get_neighbors", markdown_report(report))
        self.assertIn("Agent conclusion", markdown_report(report))

    def test_action_decoder_handles_wrapped_json_and_rejects_empty_response(self) -> None:
        self.assertEqual(_decode_action("~~~json\n{\"kind\":\"final\"}\n~~~")["kind"], "final")
        with self.assertRaises(AgentResponseError):
            _decode_action("")


if __name__ == "__main__":
    unittest.main()
