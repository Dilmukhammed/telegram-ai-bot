from __future__ import annotations

import unittest

from memory.eval.resolution_expectations import (
    check_hard_gates,
    load_resolution_expectations,
)


class ResolutionExpectationPackTests(unittest.TestCase):
    def test_load_resolution_v1(self) -> None:
        pack = load_resolution_expectations()
        self.assertEqual(pack.pack_id, "resolution_v1")
        self.assertFalse(pack.reviewed)
        required = {
            "root_self_preference",
            "person_name_non_merge",
            "org_alias_critic_accept",
            "org_alias_critic_veto",
            "non_ready_not_consumed",
            "invalidation_clears_assertion",
            "correction_winner_promotes",
            "cessation_ready_negative",
            "polarity_conflict_uncertain",
        }
        self.assertTrue(required.issubset(pack.cases.keys()))
        self.assertEqual(pack.hard_gates["eligible_assertion_recall"], 1.0)
        self.assertEqual(pack.hard_gates["graph_writes"], 0)

    def test_hard_gates_pass_clean_slice(self) -> None:
        pack = load_resolution_expectations()
        failures = check_hard_gates(
            eligible_assertion_recall=1.0,
            non_ready_consumed=0,
            false_person_merge=0,
            cross_user_leakage=0,
            critic_forbidden_merge=0,
            active_belief_without_support=0,
            graph_writes=0,
            gates=pack.hard_gates,
        )
        self.assertEqual(failures, [])

    def test_hard_gates_catch_non_ready_and_merge(self) -> None:
        failures = check_hard_gates(
            eligible_assertion_recall=1.0,
            non_ready_consumed=1,
            false_person_merge=1,
            cross_user_leakage=0,
            critic_forbidden_merge=0,
            active_belief_without_support=0,
            graph_writes=0,
        )
        self.assertEqual(
            set(failures),
            {"non_ready_consumed", "false_person_merge"},
        )

    def test_hard_gates_catch_graph_write(self) -> None:
        failures = check_hard_gates(
            eligible_assertion_recall=1.0,
            non_ready_consumed=0,
            false_person_merge=0,
            cross_user_leakage=0,
            critic_forbidden_merge=0,
            active_belief_without_support=0,
            graph_writes=3,
        )
        self.assertEqual(failures, ["graph_writes"])

    def test_case_expectations_shape(self) -> None:
        pack = load_resolution_expectations()
        root = pack.cases["root_self_preference"]
        self.assertTrue(root.expect_assertion)
        self.assertTrue(root.expect_root_self)
        self.assertFalse(root.expect_person_merge)
        self.assertEqual(root.expect_belief_status, "active")

        non_ready = pack.cases["non_ready_not_consumed"]
        self.assertFalse(non_ready.expect_assertion)
        self.assertFalse(non_ready.non_ready_consumed)

        invalidated = pack.cases["invalidation_clears_assertion"]
        self.assertEqual(invalidated.expect_belief_status, "unsupported")


if __name__ == "__main__":
    unittest.main()
