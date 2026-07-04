from __future__ import annotations

from typing import Any


def trim_history_to_turns(messages: list[dict[str, Any]], max_turns: int) -> list[dict[str, Any]]:
    if max_turns <= 0:
        return []

    user_indices = [index for index, message in enumerate(messages) if message.get("role") == "user"]
    if len(user_indices) <= max_turns:
        return messages

    keep_from = user_indices[-max_turns]
    return messages[keep_from:]
