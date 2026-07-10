import unittest

from thorough.output import extract_plan_yaml, plan_yaml_valid, planner_response_text


class FakeMessage:
    def __init__(self, *, content: str = "", reasoning_content: str = "") -> None:
        self.content = content
        self.reasoning_content = reasoning_content


class ThoroughOutputTests(unittest.TestCase):
    def test_planner_response_ignores_reasoning(self) -> None:
        msg = FakeMessage(content="phase_plan:\n  planner_id: unit", reasoning_content="hidden")
        self.assertEqual(planner_response_text(msg), "phase_plan:\n  planner_id: unit")

    def test_planner_response_empty_without_content(self) -> None:
        msg = FakeMessage(reasoning_content="only thinking")
        self.assertEqual(planner_response_text(msg), "")

    def test_extract_from_fenced_yaml(self) -> None:
        raw = "Thinking...\n```yaml\nphase_plan:\n  planner_id: unit\n```"
        self.assertEqual(extract_plan_yaml(raw), "phase_plan:\n  planner_id: unit")

    def test_extract_skips_thinking_preamble(self) -> None:
        raw = (
            "The user wants a sheet.\n\n"
            "phase_plan:\n"
            "  planner_id: surface\n"
            "  phase_count: 1\n"
        )
        self.assertTrue(extract_plan_yaml(raw).startswith("phase_plan:"))

    def test_extract_returns_empty_without_root(self) -> None:
        self.assertEqual(extract_plan_yaml("Only thinking, no yaml."), "")

    def test_plan_yaml_valid(self) -> None:
        self.assertTrue(plan_yaml_valid("phase_plan:\n  x: 1", root="phase_plan"))
        self.assertFalse(plan_yaml_valid("thinking...", root="phase_plan"))


if __name__ == "__main__":
    unittest.main()
