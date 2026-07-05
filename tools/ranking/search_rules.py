from __future__ import annotations

from tools.ranking.constants import (
    CALENDAR_TOKENS,
    DOMAIN_SEARCH_TOKENS,
    DOMAIN_SEARCH_WINNERS,
    DOMAIN_SEARCH_WINNER_BOOST,
    SEARCH_SIBLING_PENALTY,
    SEARCH_SIBLINGS,
)

SEARCH_INTENT_TOKENS = frozenset({"search", "find", "lookup", "query", "grep"})

# First match wins when multiple domain tokens appear in one query.
DOMAIN_DETECT_ORDER: tuple[str, ...] = (
    "gmail",
    "drive",
    "calendar",
    "tasks",
    "maps",
    "places",
    "nearby",
    "yandex",
    "music",
    "workspace",
    "grep",
    "sheets",
    "spreadsheet",
    "web",
    "internet",
)


def detect_search_domain(query_tokens: set[str]) -> str | None:
    for domain in DOMAIN_DETECT_ORDER:
        if domain in query_tokens:
            return domain
    if query_tokens & CALENDAR_TOKENS:
        return "calendar"
    return None


def search_winners_for_domain(domain: str) -> frozenset[str]:
    return frozenset(DOMAIN_SEARCH_WINNERS.get(domain, ()))


def search_action_bonus(query_tokens: set[str], tool_name: str, method: str) -> float:
    has_search_intent = bool(query_tokens & SEARCH_INTENT_TOKENS)
    bonus = 0.0

    if "search" in query_tokens:
        if method == "search" or method.endswith("_search") or tool_name.endswith(".search"):
            bonus += 3.0
        elif "search" in method:
            bonus += 2.0

        if tool_name == "google.gmail.search_messages" and "gmail" in query_tokens:
            bonus += 4.0
        if tool_name == "google.drive.search_files" and "drive" in query_tokens:
            bonus += 4.0
        if tool_name == "google.calendar.search_events" and query_tokens & CALENDAR_TOKENS:
            bonus += 4.0
        if tool_name == "workspace.grep" and query_tokens & {"workspace", "grep", "pattern", "files"}:
            bonus += 4.0
        if tool_name == "yandex.music.search" and query_tokens & {"music", "yandex", "tracks"}:
            bonus += 3.0
        if tool_name == "google.tasks.search_tasks" and query_tokens & {"tasks", "task"}:
            bonus += 4.0
        if "places" in method and method.endswith("_search") and query_tokens & {"maps", "places", "nearby"}:
            bonus += 3.0
        if tool_name == "exa.web_search" and query_tokens & DOMAIN_SEARCH_TOKENS:
            bonus -= 3.0

    if has_search_intent:
        domain = detect_search_domain(query_tokens)
        if domain is not None:
            winners = search_winners_for_domain(domain)
            if tool_name in winners:
                bonus += DOMAIN_SEARCH_WINNER_BOOST
            elif tool_name in SEARCH_SIBLINGS:
                bonus -= SEARCH_SIBLING_PENALTY
        elif "search" in query_tokens:
            if tool_name == "exa.web_search":
                bonus += 2.0
            elif tool_name in SEARCH_SIBLINGS:
                bonus -= SEARCH_SIBLING_PENALTY

    return bonus
