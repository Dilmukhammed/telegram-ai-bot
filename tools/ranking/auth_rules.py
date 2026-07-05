from __future__ import annotations

from tools.ranking.constants import OAUTH_INTENT_TOKENS


def auth_action_bonus(query_tokens: set[str], tool_name: str, method: str) -> float:
    if not query_tokens & OAUTH_INTENT_TOKENS:
        return 0.0

    bonus = 0.0
    if method == "status" and ".auth." in tool_name:
        bonus += 3.0
    return bonus
