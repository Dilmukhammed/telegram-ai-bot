import json
import unittest

from agent.history_persist import extract_worker_history_for_persist
from bot.history_persist import trim_history_to_turns, trim_history_to_turns


def _search_exchange(assistant_idx: int = 1) -> list[dict]:
    return [
        {"role": "user", "content": "find route"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "s1",
                    "type": "function",
                    "function": {"name": "search_tools", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "s1",
            "content": json.dumps({"count": 1, "tools": [{"name": "google.maps.directions"}]}),
        },
    ]


def _use_exchange() -> list[dict]:
    return [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "u1",
                    "type": "function",
                    "function": {
                        "name": "use_tool",
                        "arguments": json.dumps(
                            {
                                "tool_name": "google.maps.maps_link",
                                "arguments": {"origin": "A", "destination": "B"},
                            }
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "u1",
            "content": json.dumps(
                {
                    "tool_name": "google.maps.maps_link",
                    "ok": True,
                    "result": {"url": "https://maps.google.com/?dir=A|B"},
                }
            ),
        },
    ]


class HistoryPersistTests(unittest.TestCase):
    def test_extract_keeps_use_tool_and_drops_search_tools(self) -> None:
        messages = [
            {"role": "system", "content": "sys"},
            *_search_exchange(),
            *_use_exchange(),
        ]
        worker = extract_worker_history_for_persist(
            messages,
            worker_start_index=2,
            display_reply="Вот маршрут.",
        )
        roles = [message["role"] for message in worker]
        self.assertEqual(roles, ["assistant", "tool", "assistant"])
        self.assertEqual(worker[-1]["content"], "Вот маршрут.")
        self.assertIn("google.maps.maps_link", worker[1]["content"])

    def test_extract_strips_multiple_search_rounds(self) -> None:
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "big task"},
            *_search_exchange(),
            *_use_exchange(),
            *_search_exchange(assistant_idx=5),
            *_use_exchange(),
        ]
        worker = extract_worker_history_for_persist(
            messages,
            worker_start_index=2,
            display_reply="Done.",
        )
        self.assertEqual(sum(1 for message in worker if message.get("role") == "tool"), 2)
        self.assertFalse(any("search_tools" in str(message) for message in worker))

    def test_trim_history_by_user_turns(self) -> None:
        history = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "two"},
            {"role": "assistant", "tool_calls": [{"id": "u1", "function": {"name": "use_tool"}}]},
            {"role": "tool", "tool_call_id": "u1", "content": "{}"},
            {"role": "assistant", "content": "a2"},
        ]
        trimmed = trim_history_to_turns(history, 1)
        self.assertEqual(trimmed[0]["content"], "two")
        self.assertEqual(len(trimmed), 4)


if __name__ == "__main__":
    unittest.main()
