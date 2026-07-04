import json
import unittest
from unittest.mock import AsyncMock, patch

from agent.run_trace import RunTrace, RunTraceCollector
from agent.supervisor import (
    AgentSupervisor,
    fallback_stop_decision,
    format_supervisor_coaching,
    format_supervisor_stop,
    parse_supervisor_response,
)
from config import get_settings


class SupervisorParseTests(unittest.TestCase):
    def test_parse_continue_decision(self) -> None:
        decision = parse_supervisor_response(
            json.dumps(
                {
                    "decision": "CONTINUE",
                    "confidence": 0.9,
                    "remaining_steps": ["google.maps.travel_time", "google.calendar.create_event"],
                    "hints": ["use text_query not query"],
                    "do_not": ["search_tools again"],
                    "bonus_turns": 12,
                }
            ),
            default_bonus_turns=10,
        )
        self.assertEqual(decision.decision, "CONTINUE")
        self.assertEqual(decision.bonus_turns, 12)
        self.assertEqual(len(decision.remaining_steps), 2)

    def test_parse_stop_decision(self) -> None:
        decision = parse_supervisor_response(
            '{"decision":"STOP_GRACEFUL","user_reply_brief":"Tell user to create event manually"}',
            default_bonus_turns=10,
        )
        self.assertEqual(decision.decision, "STOP_GRACEFUL")
        self.assertIn("manually", decision.user_reply_brief)

    def test_parse_invalid_json_fallback(self) -> None:
        with self.assertRaises(ValueError):
            parse_supervisor_response("not json", default_bonus_turns=10)

    def test_parse_json_fence(self) -> None:
        decision = parse_supervisor_response(
            '```json\n{"decision":"STOP_GRACEFUL","user_reply_brief":"done"}\n```',
            default_bonus_turns=10,
        )
        self.assertEqual(decision.decision, "STOP_GRACEFUL")


class SupervisorFormatTests(unittest.TestCase):
    def test_coaching_message_shape(self) -> None:
        decision = parse_supervisor_response(
            json.dumps(
                {
                    "decision": "CONTINUE",
                    "remaining_steps": ["google.calendar.create_event"],
                    "hints": ["Use end time after travel time"],
                    "do_not": ["Do not repeat list_events"],
                }
            ),
            default_bonus_turns=10,
        )
        text = format_supervisor_coaching(decision, 10)
        self.assertIn("Supervisor review (continue)", text)
        self.assertIn("create_event", text)
        self.assertIn("10 more turns", text)
        self.assertNotIn("Stop calling tools", text)

    def test_stop_message_shape(self) -> None:
        text = format_supervisor_stop(
            fallback_stop_decision(reason="parse failed"),
        )
        self.assertIn("Supervisor review (stop)", text)
        self.assertNotIn("Stop calling tools", text)


class AgentSupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_parses_model_json(self) -> None:
        trace = RunTraceCollector(user_id=1, user_message="schedule coffee", worker_turns_budget=30).finish(
            "cap_hit"
        )
        settings = get_settings()
        supervisor = AgentSupervisor(AsyncMock(), settings)
        supervisor._llm = AsyncMock()
        supervisor._llm.chat = AsyncMock(
            return_value=json.dumps(
                {
                    "decision": "CONTINUE",
                    "remaining_steps": ["google.calendar.create_event"],
                    "hints": [],
                    "do_not": [],
                    "bonus_turns": 10,
                }
            )
        )

        decision = await supervisor.review(trace)
        self.assertEqual(decision.decision, "CONTINUE")
        supervisor._llm.chat.assert_awaited_once()

    async def test_review_invalid_json_fallback(self) -> None:
        trace = RunTrace(user_id=1, user_message="x", started_at=0.0, worker_turns_budget=30)
        settings = get_settings()
        supervisor = AgentSupervisor(AsyncMock(), settings)
        supervisor._llm = AsyncMock()
        supervisor._llm.chat = AsyncMock(return_value="sorry, not json")

        decision = await supervisor.review(trace)
        self.assertEqual(decision.decision, "STOP_GRACEFUL")


class AgentSupervisorLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_cap_hit_continue_grants_bonus_turns(self) -> None:
        from agent.loop import Agent
        from tools.bootstrap import create_tool_runtime

        settings = get_settings()
        with patch.dict(
            "os.environ",
            {
                "AGENT_SUPERVISOR_ENABLED": "1",
                "AGENT_MAX_TOOL_TURNS": "1",
                "AGENT_SUPERVISOR_BONUS_TURNS": "2",
                "AGENT_SUPERVISOR_MAX_CYCLES": "1",
                "TOOL_EMBEDDING_PROVIDER": "keyword",
            },
            clear=False,
        ):
            settings = get_settings()
            runtime = await create_tool_runtime()
            agent = Agent(settings, runtime)

            tool_call = type(
                "ToolCall",
                (),
                {
                    "id": "call_1",
                    "function": type(
                        "Fn",
                        (),
                        {
                            "name": "search_tools",
                            "arguments": json.dumps({"mode": "catalog", "tags": ["echo"]}),
                        },
                    )(),
                },
            )()

            first_message = type(
                "Msg",
                (),
                {"content": None, "tool_calls": [tool_call], "model_dump": lambda self, exclude_none=True: {"role": "assistant", "tool_calls": []}},
            )()
            final_message = type("Msg", (), {"content": "Done", "tool_calls": [], "model_dump": lambda self, exclude_none=True: {"role": "assistant", "content": "Done"}})()

            call_count = {"n": 0}

            async def fake_chat_with_tools(*args, **kwargs):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return type("Resp", (), {"choices": [type("Choice", (), {"message": first_message})()]})()
                return type("Resp", (), {"choices": [type("Choice", (), {"message": final_message})()]})()

            agent._llm.chat_with_tools = fake_chat_with_tools
            agent._llm.chat = AsyncMock(return_value="Should not finalize early")

            continue_decision = parse_supervisor_response(
                json.dumps({"decision": "CONTINUE", "remaining_steps": ["echo.test"], "bonus_turns": 2}),
                default_bonus_turns=2,
            )
            agent._supervisor.review = AsyncMock(return_value=continue_decision)

            statuses: list[str] = []

            async def on_status(text: str) -> None:
                statuses.append(text)

            result = await agent.run("test", on_status=on_status, user_id=1)
            self.assertEqual(result.reply, "Done")
            self.assertIn("Проверяю шаги агента…", statuses)
            self.assertIn("Продолжаю выполнение…", statuses)
            agent._supervisor.review.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
