from __future__ import annotations

from tools.ranking.constants import (
    CALENDAR_TOKENS,
    LIST_INTENT_RULES,
    LIST_ONLY_NOISE_METHODS,
    ListIntentRuleSpec,
    OAUTH_INTENT_TOKENS,
)


def _matches_list_rule(query_tokens: set[str], rule: ListIntentRuleSpec) -> bool:
    if not rule.required_tokens.issubset(query_tokens):
        return False
    if rule.all_tokens and not rule.all_tokens.issubset(query_tokens):
        return False
    if rule.any_tokens and not (query_tokens & rule.any_tokens):
        return False
    if rule.unless_tokens and (query_tokens & rule.unless_tokens):
        return False
    return True


def _apply_list_rule(query_tokens: set[str], tool_name: str, method: str, rule: ListIntentRuleSpec) -> float:
    if not _matches_list_rule(query_tokens, rule):
        return 0.0

    bonus = 0.0
    if method in rule.boost_methods or tool_name in rule.boost_tool_names:
        bonus += rule.boost_amount
    if method in rule.penalty_methods or tool_name in rule.penalty_tool_names:
        bonus -= rule.penalty_amount
    for prefix in rule.penalty_prefixes:
        if tool_name.startswith(prefix):
            bonus -= rule.penalty_amount
    for substring in rule.penalty_method_substrings:
        if substring in method and method != "users_playlists_list":
            bonus -= rule.penalty_amount
    return bonus


def _bare_list_bonus(query_tokens: set[str], tool_name: str, method: str) -> float:
    if query_tokens != {"list"}:
        return 0.0

    bonus = 0.0
    if method in LIST_ONLY_NOISE_METHODS:
        bonus -= 4.0
    if tool_name == "skills.list":
        bonus += 3.0
    return bonus


def list_action_bonus(query_tokens: set[str], tool_name: str, method: str) -> float:
    bonus = 0.0

    if "list" in query_tokens or "lists" in query_tokens:
        for rule in LIST_INTENT_RULES:
            bonus += _apply_list_rule(query_tokens, tool_name, method, rule)
        bonus += _bare_list_bonus(query_tokens, tool_name, method)

    if query_tokens & CALENDAR_TOKENS:
        if method == "list_today" and "today" in query_tokens:
            bonus += 4.0
        if method == "list_upcoming" and "upcoming" in query_tokens:
            bonus += 4.0
        if (
            method == "list_events"
            and "list" in query_tokens
            and "today" not in query_tokens
            and "upcoming" not in query_tokens
            and "create" not in query_tokens
        ):
            bonus += 2.0
        if method in {"create_event", "quick_add_event"} and query_tokens & {"create", "new"}:
            bonus += 4.0
        if method in {"freebusy", "find_free_slots"} and query_tokens & {"free", "busy", "availability"}:
            bonus += 4.0
        if ".auth." in tool_name and not query_tokens & OAUTH_INTENT_TOKENS:
            bonus -= 3.0

    if query_tokens & {"inbox", "unread"} and "list" not in query_tokens:
        if method in {"list_inbox", "list_unread"}:
            bonus += 3.0
        if method == "send_message" and "send" not in query_tokens:
            bonus -= 3.0

    return bonus
