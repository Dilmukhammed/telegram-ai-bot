from __future__ import annotations

from tools.ranking.antonym_rules import antonym_action_bonus
from tools.ranking.auth_rules import auth_action_bonus
from tools.ranking.io_rules import io_action_bonus
from tools.ranking.list_rules import list_action_bonus
from tools.ranking.music_rules import music_action_bonus
from tools.ranking.search_rules import search_action_bonus

__all__ = ("keyword_action_bonus",)


def _tool_method_name(tool_name: str) -> str:
    return tool_name.rsplit(".", 1)[-1]


def keyword_action_bonus(query_tokens: set[str], tool_name: str) -> float:
    if not query_tokens:
        return 0.0

    method = _tool_method_name(tool_name)
    bonus = 0.0
    bonus += search_action_bonus(query_tokens, tool_name, method)
    bonus += antonym_action_bonus(query_tokens, tool_name, method)
    bonus += list_action_bonus(query_tokens, tool_name, method)
    bonus += auth_action_bonus(query_tokens, tool_name, method)
    bonus += io_action_bonus(query_tokens, tool_name, method)
    bonus += music_action_bonus(query_tokens, tool_name, method)
    return bonus
