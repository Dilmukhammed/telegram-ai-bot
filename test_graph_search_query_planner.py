from __future__ import annotations

import unittest

from scripts.plan_graph_search_queries import EXAMPLE_INPUT, SYNTHETIC_GRAPH, SYSTEM_PROMPT, _markdown_report, execute_plan


class GraphSearchQueryPlannerTests(unittest.TestCase):
    def test_prompt_is_synthetic_and_covers_entities_groups_and_edges(self) -> None:
        self.assertIn("synthetic example only", SYSTEM_PROMPT)
        self.assertIn('"entity_queries"', SYSTEM_PROMPT)
        self.assertIn('"group_queries"', SYSTEM_PROMPT)
        self.assertIn('"edge_queries"', SYSTEM_PROMPT)
        self.assertIn('"write_decision": "abstain"', SYSTEM_PROMPT)

    def test_probe_input_is_only_the_hard_coded_pizza_pair(self) -> None:
        self.assertEqual(EXAMPLE_INPUT["anchor_entity"]["label"], "пицца")
        self.assertEqual(EXAMPLE_INPUT["anchor_edge"]["edge_type"], "likes_eat")
        self.assertNotIn("database", EXAMPLE_INPUT)

    def test_synthetic_executor_searches_entity_group_and_edge_plans(self) -> None:
        result = execute_plan(
            {
                "entity_queries": [{"query": "pizza", "channel": "alias"}],
                "group_queries": [{"query": "Italian dishes"}],
                "edge_queries": [{"edge_types": ["cuisine_of"], "direction": "outgoing", "max_hops": 1}],
                "pair_and_path_queries": [],
            }
        )
        self.assertEqual(result["entity_searches"][0]["hits"][0]["label"], "пицца")
        self.assertEqual(result["fused_entity_candidates"][0]["label"], "пицца")
        self.assertEqual(result["group_searches"][0]["hits"][0]["label"], "Italian dishes")
        self.assertEqual(result["edge_searches"][0]["hits"][0]["target_label"], "Italian Cuisine")

    def test_large_fixture_and_handoff_cover_multiple_domains(self) -> None:
        self.assertGreaterEqual(len(SYNTHETIC_GRAPH["entities"]), 45)
        self.assertGreaterEqual(len(SYNTHETIC_GRAPH["groups"]), 16)
        self.assertGreaterEqual(len(SYNTHETIC_GRAPH["edges"]), 49)
        handoff = _markdown_report(
            {"synthetic_graph": SYNTHETIC_GRAPH, "llm_plan": {}, "search_results": {}}
        )
        self.assertIn("Graph Search Results", handoff)
        self.assertIn("User request", handoff)

    def test_handoff_shows_only_thresholded_top_results_with_scores(self) -> None:
        report = {
            "synthetic_graph": SYNTHETIC_GRAPH,
            "llm_plan": {},
            "search_results": execute_plan(
                {
                    "entity_queries": [{"query": "pizza", "channel": "alias", "reason": "alias check"}],
                    "group_queries": [],
                    "edge_queries": [],
                    "pair_and_path_queries": [],
                }
            ),
        }
        handoff = _markdown_report(report)
        self.assertIn("Searched: entity `pizza` via `alias`", handoff)
        self.assertIn("score **1.0000**", handoff)


if __name__ == "__main__":
    unittest.main()
