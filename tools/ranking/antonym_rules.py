from __future__ import annotations

from tools.ranking.constants import (
    ANTONYM_RULES,
    AntonymRuleSpec,
    NEGATIVE_LIKE_TOKENS,
    POSITIVE_LIKE_TOKENS,
    YANDEX_DISLIKES_PENALTY,
    YANDEX_GENERIC_TRACKS_PENALTY,
    YANDEX_LIKES_BOOST,
    YANDEX_LIKES_ENTITIES,
    YANDEX_LIKES_WRITE_PENALTY,
    YANDEX_LIKES_WRITE_TOKENS,
)

_ENTITY_SINGULAR = {
    "tracks": "tracks",
    "track": "tracks",
    "albums": "albums",
    "album": "albums",
    "artists": "artists",
    "artist": "artists",
    "clips": "clips",
    "clip": "clips",
    "playlists": "playlists",
    "playlist": "playlists",
}


def _detect_yandex_likes_entity(query_tokens: set[str]) -> str:
    for token, entity in _ENTITY_SINGULAR.items():
        if token in query_tokens:
            return entity
    return "tracks"


def _matches_rule(query_tokens: set[str], rule: AntonymRuleSpec) -> bool:
    if not query_tokens & rule.query_tokens:
        return False
    if rule.all_query_tokens and not rule.all_query_tokens.issubset(query_tokens):
        return False
    if rule.any_query_tokens and not (query_tokens & rule.any_query_tokens):
        return False
    if rule.unless_query_tokens and query_tokens & rule.unless_query_tokens:
        return False
    return True


def _apply_rule(query_tokens: set[str], tool_name: str, method: str, rule: AntonymRuleSpec) -> float:
    if not _matches_rule(query_tokens, rule):
        return 0.0

    bonus = 0.0
    if method in rule.boost_methods or tool_name in rule.boost_tool_names:
        bonus += rule.boost_amount
    if method in rule.penalty_methods or tool_name in rule.penalty_tool_names:
        bonus -= rule.penalty_amount
    for substring in rule.penalty_substrings:
        if substring in tool_name:
            bonus -= rule.penalty_amount
    return bonus


def _yandex_likes_bonus(query_tokens: set[str], tool_name: str, method: str) -> float:
    bonus = 0.0
    write_intent = bool(query_tokens & YANDEX_LIKES_WRITE_TOKENS)

    if query_tokens & POSITIVE_LIKE_TOKENS:
        entity = _detect_yandex_likes_entity(query_tokens)
        if "dislikes" in tool_name:
            bonus -= YANDEX_DISLIKES_PENALTY
        if method == f"users_likes_{entity}":
            bonus += YANDEX_LIKES_BOOST
        elif method.startswith("users_likes_") and (
            method.endswith("_add") or method.endswith("_remove")
        ):
            if not write_intent:
                bonus -= YANDEX_LIKES_WRITE_PENALTY
        if method == "tracks" and tool_name.startswith("yandex.music."):
            bonus -= YANDEX_GENERIC_TRACKS_PENALTY

    if query_tokens & NEGATIVE_LIKE_TOKENS:
        entity = _detect_yandex_likes_entity(query_tokens)
        if method == f"users_dislikes_{entity}":
            bonus += YANDEX_LIKES_BOOST
        elif method.startswith("users_likes_"):
            bonus -= YANDEX_LIKES_BOOST
        elif method == "tracks" and tool_name.startswith("yandex.music."):
            bonus -= YANDEX_GENERIC_TRACKS_PENALTY
        elif method.startswith("users_dislikes_") and (
            method.endswith("_add") or method.endswith("_remove")
        ):
            if not write_intent:
                bonus -= YANDEX_LIKES_WRITE_PENALTY

    return bonus


def antonym_action_bonus(query_tokens: set[str], tool_name: str, method: str) -> float:
    bonus = 0.0
    bonus += _yandex_likes_bonus(query_tokens, tool_name, method)
    for rule in ANTONYM_RULES:
        bonus += _apply_rule(query_tokens, tool_name, method, rule)

    if query_tokens & {"geocode", "coordinates", "address"}:
        if method == "geocode" and "reverse" not in query_tokens:
            bonus += 2.5

    return bonus
