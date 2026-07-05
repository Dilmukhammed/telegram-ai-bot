import json
import unittest
from types import SimpleNamespace

from agent.context_collapse import (
    SearchContextCollapser,
    collapse_all_search_tools,
    collapse_duplicate_use_tool_calls,
    collapse_search_tools_exchange,
    find_all_use_tool_exchanges,
    find_search_tools_exchange,
    is_search_tools_result,
    is_successful_use_tool_result,
    strip_remaining_search_tools_artifacts,
    turn_had_any_successful_use_tool,
    turn_had_successful_use_tool,
    use_tool_call_identity,
)
from agent.history_persist import strip_all_search_tools


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

    def test_collapser_collapse_all_searches_on_successful_use(self) -> None:
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
                    {
                        "id": "s2",
                        "function": {"name": "search_tools", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "s2", "content": _search_result()},
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
        self.assertIsNone(find_search_tools_exchange(messages))
        self.assertEqual(len(messages), 3)

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

        self.assertIsNotNone(find_search_tools_exchange(messages))

    def test_collapser_keeps_later_search_until_next_successful_use(self) -> None:
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
        self.assertIsNone(find_search_tools_exchange(messages))
        self.assertEqual(len(messages), 3)

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
        self.assertEqual(find_search_tools_exchange(messages), (3, 4))
        self.assertEqual(len(messages), 5)

    def test_collapser_collapse_all_on_any_success_in_mixed_use_turn(self) -> None:
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
        ]
        collapser = SearchContextCollapser()
        collapser.on_tool_turn(
            messages,
            [
                _tool_call("use_tool", "u1"),
                _tool_call("use_tool", "u2"),
            ],
            [_use_result(ok=False), _use_result()],
        )
        self.assertIsNone(find_search_tools_exchange(messages))

    def test_turn_had_any_successful_use_tool(self) -> None:
        calls = [_tool_call("use_tool", "u1"), _tool_call("use_tool", "u2")]
        self.assertTrue(
            turn_had_any_successful_use_tool(
                calls,
                [_use_result(ok=False), _use_result()],
            )
        )
        self.assertFalse(
            turn_had_any_successful_use_tool(
                calls,
                [_use_result(ok=False), _use_result(ok=False)],
            )
        )

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
        self.assertIsNone(find_search_tools_exchange(messages))

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
        self.assertIsNone(find_search_tools_exchange(messages))
        self.assertEqual(len(messages), 5)

    def test_collapse_all_search_tools_helper(self) -> None:
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "s1", "function": {"name": "search_tools", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "s1", "content": _search_result()},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "s2", "function": {"name": "search_tools", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "s2", "content": _search_result()},
        ]
        removed = collapse_all_search_tools(messages)
        self.assertEqual(removed, 2)
        self.assertEqual(len(messages), 1)

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

    def test_duplicate_use_tool_collapses_earlier_exchange(self) -> None:
        args = json.dumps(
            {
                "tool_name": "yandex.music.playlist",
                "arguments": {"user_id": "1", "kind": "3"},
            }
        )
        result = json.dumps(
            {
                "tool_name": "yandex.music.playlist",
                "ok": True,
                "result": {"title": "Liked"},
            }
        )

        def exchange(call_id: str) -> list[dict]:
            return [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": "use_tool", "arguments": args},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result,
                },
            ]

        messages = [*exchange("c1"), *exchange("c2")]
        self.assertEqual(len(find_all_use_tool_exchanges(messages)), 2)
        collapsed = collapse_duplicate_use_tool_calls(messages)
        self.assertEqual(collapsed, 1)
        self.assertEqual(len(messages), 3)
        self.assertIn("Collapsed duplicate tool call", messages[0]["content"])
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[2]["role"], "tool")

    def test_duplicate_identity_ignores_reason(self) -> None:
        call_a = {
            "id": "a",
            "function": {
                "name": "use_tool",
                "arguments": json.dumps(
                    {
                        "tool_name": "yandex.music.tracks",
                        "arguments": {"track_ids": "1,2", "reason": "first"},
                    }
                ),
            },
        }
        call_b = {
            "id": "b",
            "function": {
                "name": "use_tool",
                "arguments": json.dumps(
                    {
                        "tool_name": "yandex.music.tracks",
                        "arguments": {"track_ids": "1,2", "reason": "second"},
                    }
                ),
            },
        }
        self.assertEqual(use_tool_call_identity(call_a), use_tool_call_identity(call_b))

    def test_strip_orphan_search_tools_result(self) -> None:
        messages = [
            {"role": "user", "content": "retry yandex"},
            {
                "role": "tool",
                "tool_call_id": "call_search_orphan",
                "content": _search_result(),
            },
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_use",
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
        removed = strip_remaining_search_tools_artifacts(messages)
        self.assertEqual(removed, 1)
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["tool_calls"][0]["function"]["name"], "use_tool")

    def test_strip_all_search_tools_removes_orphan(self) -> None:
        messages = [
            {"role": "user", "content": "retry"},
            {
                "role": "tool",
                "tool_call_id": "call_search_orphan",
                "content": _search_result(),
            },
            {"role": "assistant", "content": "done"},
        ]
        cleaned = strip_all_search_tools(messages)
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0]["role"], "user")
        self.assertEqual(cleaned[1]["content"], "done")


if __name__ == "__main__":
    unittest.main()
