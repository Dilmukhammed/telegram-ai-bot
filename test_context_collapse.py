import json
import unittest
from types import SimpleNamespace

from agent.context_collapse import (
    SearchContextCollapser,
    collapse_search_tools_exchange,
    find_search_tools_exchange,
    is_search_tools_result,
    is_successful_use_tool_result,
    turn_had_successful_use_tool,
)


def _tool_call(name: str, call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments="{}"),
    )


def _search_result() -> str:
    return json.dumps(
        {
            "mode": "rank",
            "query": "match schedule",
            "count": 1,
            "tools": [{"name": "exa.web_search", "description": "search"}],
        }
    )


def _use_result(ok: bool = True) -> str:
    return json.dumps(
        {
            "tool_name": "exa.web_search",
            "ok": ok,
            "cached": False,
            "result": {"hits": []},
        }
    )


class ContextCollapseTests(unittest.IsolatedAsyncioTestCase):
    def test_is_search_tools_result(self) -> None:
        self.assertTrue(is_search_tools_result(_search_result()))
        self.assertFalse(is_search_tools_result(_use_result()))
        self.assertFalse(is_search_tools_result(json.dumps({"ok": False, "error": "bad"})))

    def test_is_successful_use_tool_result(self) -> None:
        self.assertTrue(is_successful_use_tool_result(_use_result()))
        self.assertFalse(is_successful_use_tool_result(_use_result(ok=False)))
        self.assertFalse(is_successful_use_tool_result(_search_result()))

    def test_find_and_collapse_search_exchange(self) -> None:
        messages = [
            {"role": "user", "content": "when is the match"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_search",
                        "type": "function",
                        "function": {"name": "search_tools", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_search",
                "content": _search_result(),
            },
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_use",
                        "type": "function",
                        "function": {"name": "use_tool", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_use",
                "content": _use_result(),
            },
        ]

        self.assertEqual(find_search_tools_exchange(messages), (1, 2))
        self.assertTrue(collapse_search_tools_exchange(messages))
        self.assertIsNone(find_search_tools_exchange(messages))
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["tool_calls"][0]["function"]["name"], "use_tool")

    def test_collapser_defers_until_final_turn(self) -> None:
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "s1",
                        "function": {"name": "search_tools", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "s1", "content": _search_result()},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "u1", "function": {"name": "use_tool", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "u1", "content": _use_result()},
        ]
        collapser = SearchContextCollapser()

        collapser.on_tool_turn(
            messages,
            [_tool_call("use_tool", "u1")],
            [_use_result()],
        )
        self.assertTrue(collapser.pending)
        self.assertIsNotNone(find_search_tools_exchange(messages))

        self.assertTrue(collapser.collapse_if_pending(messages))
        self.assertFalse(collapser.pending)
        self.assertIsNone(find_search_tools_exchange(messages))

    def test_collapser_keeps_search_after_failed_use(self) -> None:
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "s1",
                        "function": {"name": "search_tools", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "s1", "content": _search_result()},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "u1", "function": {"name": "use_tool", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "u1", "content": _use_result(ok=False)},
        ]
        collapser = SearchContextCollapser()
        collapser.on_tool_turn(
            messages,
            [_tool_call("use_tool", "u1")],
            [_use_result(ok=False)],
        )

        self.assertFalse(collapser.pending)
        self.assertIsNotNone(find_search_tools_exchange(messages))

    def test_collapser_replaces_search_on_new_search(self) -> None:
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "s1",
                        "function": {"name": "search_tools", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "s1", "content": _search_result()},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "u1", "function": {"name": "use_tool", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "u1", "content": _use_result()},
        ]
        collapser = SearchContextCollapser()
        collapser.on_tool_turn(
            messages,
            [_tool_call("use_tool", "u1")],
            [_use_result()],
        )
        self.assertTrue(collapser.pending)
        self.assertEqual(collapser.tracked_search_exchange, (1, 2))

        messages.extend(
            [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "s2",
                            "function": {"name": "search_tools", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "s2", "content": _search_result()},
            ]
        )
        collapser.on_tool_turn(
            messages,
            [_tool_call("search_tools", "s2")],
            [_search_result()],
        )
        self.assertFalse(collapser.pending)
        self.assertEqual(find_search_tools_exchange(messages), (3, 4))
        self.assertEqual(len(messages), 5)

    def test_collapser_keeps_search_for_second_use_in_next_turn(self) -> None:
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "s1",
                        "function": {"name": "search_tools", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "s1", "content": _search_result()},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "u1", "function": {"name": "use_tool", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "u1", "content": _use_result()},
        ]
        collapser = SearchContextCollapser()
        collapser.on_tool_turn(
            messages,
            [_tool_call("use_tool", "u1")],
            [_use_result()],
        )
        self.assertTrue(collapser.pending)
        self.assertIsNotNone(find_search_tools_exchange(messages))

        messages.extend(
            [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {"id": "u2", "function": {"name": "use_tool", "arguments": "{}"}}
                    ],
                },
                {"role": "tool", "tool_call_id": "u2", "content": _use_result()},
            ]
        )
        collapser.on_tool_turn(
            messages,
            [_tool_call("use_tool", "u2")],
            [_use_result()],
        )
        self.assertTrue(collapser.pending)
        self.assertIsNotNone(find_search_tools_exchange(messages))

        self.assertTrue(collapser.collapse_if_pending(messages))
        self.assertFalse(collapser.pending)
        self.assertIsNone(find_search_tools_exchange(messages))
        self.assertEqual(len(messages), 5)

    def test_turn_had_successful_use_tool(self) -> None:
        calls = [_tool_call("use_tool", "u1")]
        self.assertTrue(turn_had_successful_use_tool(calls, [_use_result()]))
        self.assertFalse(turn_had_successful_use_tool(calls, [_use_result(ok=False)]))
        self.assertFalse(
            turn_had_successful_use_tool(
                [_tool_call("search_tools", "s1")],
                [_search_result()],
            )
        )


if __name__ == "__main__":
    unittest.main()
