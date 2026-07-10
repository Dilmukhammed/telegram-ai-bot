from __future__ import annotations

from typing import Any

from bot.chat_store.models import ChatMessage


def parse_turn_spec(raw: Any) -> list[int]:
    if raw is None:
        raise ValueError("turns is required")

    if isinstance(raw, bool):
        raise ValueError("turns must be an integer or array of integers")

    if isinstance(raw, int):
        if raw < 1:
            raise ValueError("turn numbers must be >= 1")
        return [raw]

    if isinstance(raw, list):
        if not raw:
            raise ValueError("turns cannot be empty")
        values = [int(item) for item in raw]
        if any(value < 1 for value in values):
            raise ValueError("turn numbers must be >= 1")
        if len(values) == 1:
            return values
        if len(values) == 2:
            start, end = values
            if end < start:
                raise ValueError("turn range end must be >= start")
            return list(range(start, end + 1))
        return values

    raise ValueError("turns must be an integer or array of integers")


def group_messages_by_turn(messages: list[ChatMessage]) -> dict[int, list[ChatMessage]]:
    turns: dict[int, list[ChatMessage]] = {}
    turn = 0
    for message in sorted(messages, key=lambda item: item.seq):
        if message.role == "user":
            turn += 1
        if turn == 0:
            continue
        turns.setdefault(turn, []).append(message)
    return turns
