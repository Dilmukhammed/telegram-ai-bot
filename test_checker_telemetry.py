import json
import unittest
from dataclasses import replace

from agent.checker_telemetry import CheckerTelemetry
from agent.run_trace import ToolStep
from agent.tool_checker import checker_skip_reason, should_run_tool_checker
from agent.tool_checker_evidence import EvidenceResolver, format_bundle_for_debug
from config import get_settings
from tools.builtins.exa_search import EXA_WEB_SEARCH
from tools.verification import CheckerRuntimeContext, EvidenceSnippet, VerificationQuestion


class CheckerTelemetryTests(unittest.TestCase):
    def test_record_review_and_summary(self) -> None:
        telemetry = CheckerTelemetry()
        telemetry.record_review(
            user_id=1,
            tool_name="exa.web_search",
            overall="pass",
            rule_based_only=False,
        )
        telemetry.record_review(
            user_id=1,
            tool_name="exa.web_search",
            overall="fail",
            rule_based_only=True,
        )
        telemetry.record_skip(tool_name="google.calendar.create_event", reason="cached")
        telemetry.record_error(tool_name="google.gmail.send_message")

        summary = telemetry.summary()
        self.assertEqual(summary["total_reviews"], 2)
        self.assertEqual(summary["by_overall"]["pass"], 1)
        self.assertEqual(summary["by_overall"]["fail"], 1)
        self.assertEqual(summary["skips"]["cached"], 1)
        self.assertEqual(summary["errors"]["google.gmail.send_message"], 1)
        self.assertEqual(summary["by_tool"][0]["tool_name"], "exa.web_search")
        self.assertEqual(summary["by_tool"][0]["pass_rate"], 50.0)
        self.assertEqual(summary["by_tool"][0]["fail_rate"], 50.0)

    def test_format_report_empty(self) -> None:
        telemetry = CheckerTelemetry()
        self.assertIn("Пока нет tool checker reviews", telemetry.format_report())

    def test_format_report_with_data(self) -> None:
        telemetry = CheckerTelemetry()
        telemetry.record_review(
            user_id=1,
            tool_name="exa.web_search",
            overall="pass",
            rule_based_only=False,
        )
        report = telemetry.format_report()
        self.assertIn("Checker stats", report)
        self.assertIn("exa.web_search", report)
        self.assertIn("pass", report)


class CheckerSkipReasonTests(unittest.TestCase):
    def test_cached_skip_when_configured(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_skip_cached=True,
            checker_tools_allowlist="exa.*",
        )
        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="exa.web_search",
            arguments_raw={},
            arguments_normalized={"query": "news"},
            result_ok=True,
            result_cached=True,
            result_json=json.dumps({"ok": True, "cached": True, "result": {}}),
        )
        self.assertEqual(
            checker_skip_reason(spec=EXA_WEB_SEARCH, step=step, settings=settings),
            "cached",
        )
        self.assertFalse(
            should_run_tool_checker(spec=EXA_WEB_SEARCH, step=step, settings=settings)
        )

    def test_runs_when_not_cached(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_skip_cached=True,
            checker_tools_allowlist="exa.*",
        )
        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="exa.web_search",
            arguments_raw={},
            arguments_normalized={"query": "news"},
            result_ok=True,
            result_cached=False,
            result_json=json.dumps({"ok": True, "result": {}}),
        )
        self.assertIsNone(
            checker_skip_reason(spec=EXA_WEB_SEARCH, step=step, settings=settings)
        )


class CheckerDebugBundleTests(unittest.TestCase):
    def test_format_bundle_for_debug_includes_questions(self) -> None:
        resolver = EvidenceResolver()
        step = ToolStep(
            turn=2,
            meta_tool="use_tool",
            target_tool="exa.web_search",
            arguments_raw={},
            arguments_normalized={"query": "bitcoin price today"},
            result_ok=True,
            result_json=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "query": "bitcoin price today",
                        "count": 1,
                        "results": [{"title": "BTC", "published_date": "2026-07-08"}],
                    },
                }
            ),
        )
        bundle = resolver.resolve_bundle(
            questions=(
                VerificationQuestion(
                    id="query_timeframe",
                    text="timeframe?",
                    evidence=(),
                ),
            ),
            current_step=step,
            prior_steps=(),
            runtime=CheckerRuntimeContext(bot_timezone="UTC", user_message="btc today"),
            user_message="btc today",
            live_snippets={
                "unused": EvidenceSnippet(
                    label="unused",
                    kind="live_fetch",
                    turn=None,
                    tool_name=None,
                    content='{"exists": true}',
                )
            },
        )
        payload = json.loads(format_bundle_for_debug(bundle, live_snippets={"unused": EvidenceSnippet(
            label="unused",
            kind="live_fetch",
            turn=None,
            tool_name=None,
            content='{"exists": true}',
        )}))
        self.assertEqual(payload["tool_name"], "exa.web_search")
        self.assertEqual(payload["questions"][0]["id"], "query_timeframe")
        self.assertIn("unused", payload["live_snippets"])


if __name__ == "__main__":
    unittest.main()
