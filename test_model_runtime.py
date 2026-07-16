import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bot import model_runtime


class ModelRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "runtime_models.json"
        model_runtime._overrides = {}
        model_runtime._last_listed_by_provider = {}
        model_runtime._loaded = False
        self._path_patch = patch.object(model_runtime, "_runtime_path", return_value=self.path)
        self._legacy_patch = patch.object(
            model_runtime,
            "_legacy_path",
            return_value=Path(self._tmpdir.name) / "runtime_model.json",
        )
        self._path_patch.start()
        self._legacy_patch.start()

    def tearDown(self) -> None:
        self._path_patch.stop()
        self._legacy_patch.stop()
        self._tmpdir.cleanup()
        model_runtime._overrides = {}
        model_runtime._last_listed_by_provider = {}
        model_runtime._loaded = False

    def test_default_then_override_persists(self) -> None:
        self.assertEqual(model_runtime.active_agent_model("env-model"), "env-model")
        model_runtime.set_agent_model("ag/gemini-3.5-flash-low")
        self.assertEqual(
            model_runtime.active_agent_model("env-model"),
            "ag/gemini-3.5-flash-low",
        )
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["roles"]["agent"]["model"], "ag/gemini-3.5-flash-low")

        model_runtime._overrides = {}
        model_runtime._loaded = False
        self.assertEqual(
            model_runtime.active_agent_model("env-model"),
            "ag/gemini-3.5-flash-low",
        )

    def test_reset_and_index_selection(self) -> None:
        model_runtime.remember_listed_models(["a", "b", "c"], provider="9router")
        self.assertEqual(
            model_runtime.resolve_model_arg(
                "2", role="agent", default="env", provider="9router"
            ),
            "b",
        )
        self.assertEqual(
            model_runtime.resolve_model_arg(
                "reset", role="agent", default="env", provider="9router"
            ),
            "env",
        )
        self.assertIsNone(model_runtime.current_override())
        self.assertFalse(self.path.exists())

    def test_summarize_and_checker_roles(self) -> None:
        model_runtime.set_role_model("summarize", "accounts/fireworks/models/deepseek-v4-flash")
        model_runtime.set_role_provider("agent", "fireworks")
        settings = SimpleNamespace(
            openai_base_url="http://127.0.0.1:20128/v1",
            openai_api_key="k9",
            openai_model="ag/gemini",
            summarize_base_url="https://api.fireworks.ai/inference/v1",
            summarize_api_key="kf",
            summarize_model="accounts/fireworks/models/old",
            checker_base_url="https://api.fireworks.ai/inference/v1",
            checker_api_key="kf",
            checker_model="accounts/fireworks/models/checker-env",
            fireworks_base_url="https://api.fireworks.ai/inference/v1",
            fireworks_api_key="kf",
            ninerouter_base_url="http://127.0.0.1:20128/v1",
            ninerouter_api_key="k9",
        )
        agent = model_runtime.resolve_endpoint(settings, "agent")
        self.assertEqual(agent.provider, "fireworks")
        self.assertEqual(agent.base_url, "https://api.fireworks.ai/inference/v1")
        summarize = model_runtime.resolve_endpoint(settings, "summarize")
        self.assertEqual(summarize.model, "accounts/fireworks/models/deepseek-v4-flash")
        checker = model_runtime.resolve_endpoint(settings, "checker")
        self.assertEqual(checker.model, summarize.model)
        self.assertTrue(checker.source.startswith("follow-summarize"))

    def test_reasoning_gate(self) -> None:
        self.assertFalse(model_runtime.should_send_reasoning_effort("ag/gemini-3.5-flash-low"))
        self.assertFalse(model_runtime.should_send_reasoning_effort("mistral/codestral-latest"))
        self.assertTrue(
            model_runtime.should_send_reasoning_effort("accounts/fireworks/models/glm-5p2")
        )

    def test_callback_parsing_and_labels(self) -> None:
        self.assertEqual(
            model_runtime.parse_model_callback("mdl:a:i:1"),
            {"role": "agent", "action": "set", "index": 1},
        )
        self.assertEqual(
            model_runtime.parse_model_callback("mdl:s:reset"),
            {"role": "summarize", "action": "reset"},
        )
        self.assertEqual(
            model_runtime.parse_model_callback("mdl:c:p:fw"),
            {"role": "checker", "action": "provider", "provider": "fireworks"},
        )
        self.assertEqual(
            model_runtime.model_button_label("ag/gemini-3.5-flash-low", active=False),
            "gemini-3.5-flash-low",
        )
        self.assertEqual(
            model_runtime.model_button_label(
                "accounts/fireworks/models/glm-5p2", active=False
            ),
            "glm-5p2",
        )

    def test_keyboard_when_aiogram_available(self) -> None:
        try:
            import aiogram  # noqa: F401
        except ImportError:
            self.skipTest("aiogram not installed locally")
        models = ["ag/gemini-3.5-flash-low", "ag/claude-sonnet-4-6", "mistral/codestral-latest"]
        kb = model_runtime.build_model_keyboard(
            models,
            active="ag/claude-sonnet-4-6",
            role="agent",
            provider="9router",
        )
        # role row + provider row + 3 models + controls
        self.assertEqual(len(kb.inline_keyboard), 6)
        self.assertTrue(kb.inline_keyboard[2 + 1][0].text.startswith("✓ "))
        self.assertEqual(kb.inline_keyboard[2][0].callback_data, "mdl:a:i:0")

    def test_legacy_runtime_model_migrates(self) -> None:
        legacy = Path(self._tmpdir.name) / "runtime_model.json"
        legacy.write_text(json.dumps({"model": "legacy-model"}), encoding="utf-8")
        model_runtime._loaded = False
        self.assertEqual(model_runtime.active_agent_model("env"), "legacy-model")
        self.assertTrue(self.path.is_file())


class LLMClientRuntimeModelTests(unittest.TestCase):
    def test_agent_uses_runtime_override(self) -> None:
        from config import get_settings
        from llm import LLMClient

        with patch.dict("os.environ", {"REASONING_EFFORT": "high"}, clear=False):
            settings = get_settings()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime_models.json"
            with patch.object(model_runtime, "_runtime_path", return_value=path), patch.object(
                model_runtime,
                "_legacy_path",
                return_value=Path(tmp) / "missing.json",
            ):
                model_runtime._overrides = {}
                model_runtime._loaded = True
                model_runtime.set_agent_model("ag/claude-sonnet-4-6")
                client = LLMClient(settings)
                kwargs = client._completion_kwargs(messages=[])
                self.assertEqual(kwargs["model"], "ag/claude-sonnet-4-6")
                # ag/* must not get reasoning_effort
                self.assertNotIn("reasoning_effort", kwargs)
                model_runtime.clear_agent_model()


if __name__ == "__main__":
    unittest.main()
