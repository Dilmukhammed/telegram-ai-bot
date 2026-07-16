import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot import model_runtime


class ModelRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "runtime_model.json"
        model_runtime._override_model = None
        model_runtime._last_listed = []
        model_runtime._loaded = False
        self._path_patch = patch.object(model_runtime, "_runtime_path", return_value=self.path)
        self._path_patch.start()

    def tearDown(self) -> None:
        self._path_patch.stop()
        self._tmpdir.cleanup()
        model_runtime._override_model = None
        model_runtime._last_listed = []
        model_runtime._loaded = False

    def test_default_then_override_persists(self) -> None:
        self.assertEqual(model_runtime.active_agent_model("env-model"), "env-model")
        model_runtime.set_agent_model("ag/gemini-3.5-flash-low")
        self.assertEqual(
            model_runtime.active_agent_model("env-model"),
            "ag/gemini-3.5-flash-low",
        )
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["model"], "ag/gemini-3.5-flash-low")

        model_runtime._override_model = None
        model_runtime._loaded = False
        self.assertEqual(
            model_runtime.active_agent_model("env-model"),
            "ag/gemini-3.5-flash-low",
        )

    def test_reset_and_index_selection(self) -> None:
        model_runtime.remember_listed_models(["a", "b", "c"])
        self.assertEqual(model_runtime.resolve_model_arg("2", default="env"), "b")
        self.assertEqual(model_runtime.resolve_model_arg("reset", default="env"), "env")
        self.assertIsNone(model_runtime.current_override())
        self.assertFalse(self.path.exists())

    def test_reasoning_gate(self) -> None:
        self.assertFalse(model_runtime.should_send_reasoning_effort("ag/gemini-3.5-flash-low"))
        self.assertFalse(model_runtime.should_send_reasoning_effort("mistral/codestral-latest"))
        self.assertTrue(
            model_runtime.should_send_reasoning_effort("accounts/fireworks/models/glm-5p2")
        )

    def test_callback_parsing_and_labels(self) -> None:
        self.assertEqual(model_runtime.parse_model_callback("mdl:i:1"), ("set", 1))
        self.assertEqual(model_runtime.parse_model_callback("mdl:reset"), ("reset", None))
        self.assertEqual(model_runtime.parse_model_callback("mdl:refresh"), ("refresh", None))
        self.assertEqual(
            model_runtime.model_button_label("ag/gemini-3.5-flash-low", active=False),
            "gemini-3.5-flash-low",
        )
        self.assertTrue(
            model_runtime.model_button_label("ag/claude-sonnet-4-6", active=True).startswith("✓ ")
        )

    def test_keyboard_when_aiogram_available(self) -> None:
        try:
            import aiogram  # noqa: F401
        except ImportError:
            self.skipTest("aiogram not installed locally")
        models = ["ag/gemini-3.5-flash-low", "ag/claude-sonnet-4-6", "mistral/codestral-latest"]
        kb = model_runtime.build_model_keyboard(models, active="ag/claude-sonnet-4-6")
        self.assertEqual(len(kb.inline_keyboard), 4)
        self.assertTrue(kb.inline_keyboard[1][0].text.startswith("✓ "))
        self.assertEqual(kb.inline_keyboard[0][0].callback_data, "mdl:i:0")


class LLMClientRuntimeModelTests(unittest.TestCase):
    def test_agent_uses_runtime_override(self) -> None:
        from config import get_settings
        from llm import LLMClient

        with patch.dict("os.environ", {"REASONING_EFFORT": "high"}, clear=False):
            settings = get_settings()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime_model.json"
            with patch.object(model_runtime, "_runtime_path", return_value=path):
                model_runtime._override_model = None
                model_runtime._loaded = True
                model_runtime.set_agent_model("ag/claude-sonnet-4-6")
                client = LLMClient(settings)
                kwargs = client._completion_kwargs(messages=[])
                self.assertEqual(kwargs["model"], "ag/claude-sonnet-4-6")
                if settings.reasoning_effort:
                    self.assertEqual(kwargs["reasoning_effort"], settings.reasoning_effort)
                model_runtime.clear_agent_model()


if __name__ == "__main__":
    unittest.main()
