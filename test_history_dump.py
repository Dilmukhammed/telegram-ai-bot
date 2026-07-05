import unittest

from bot.history_dump import analyze_history, build_history_dump_payload


class HistoryDumpTests(unittest.TestCase):
    def test_analyze_history_flags_large_tool(self) -> None:
        history = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "x" * 25_000},
        ]
        summary = analyze_history(history)
        self.assertEqual(summary["messages"], 2)
        self.assertGreater(summary["chars_total"], 25_000)
        self.assertEqual(summary["largest_messages"][0]["flags"], ["tool_result", "large_tool_result"])

    def test_build_payload_includes_skill_marker(self) -> None:
        class _Agent:
            def _build_messages(self, _user_message: str, history=None, **_kwargs):
                return [{"role": "system", "content": "sys"}, *(history or [])]

        from config import get_settings

        history = [{"role": "user", "content": "[Skill loaded: yandex.music]\n\n# playbook"}]
        payload = build_history_dump_payload(
            user_id=1,
            history=history,
            agent=_Agent(),  # type: ignore[arg-type]
            settings=get_settings(),
            prompt_tokens=123,
        )
        self.assertEqual(payload["prompt_tokens"], 123)
        self.assertIn("skill_loaded", payload["summary"]["largest_messages"][0]["flags"])


if __name__ == "__main__":
    unittest.main()
