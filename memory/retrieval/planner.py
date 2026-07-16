from __future__ import annotations

import re
from typing import Sequence

from memory.retrieval.schemas import (
    ALL_CHANNELS,
    CHANNEL_CHAT,
    CHANNEL_DOCUMENT,
    CHANNEL_ENTITY,
    CHANNEL_GOAL,
    CHANNEL_GRAPH,
    CHANNEL_LEXICAL,
    CHANNEL_TEMPORAL,
    CHANNEL_TOOL,
    CHANNEL_VECTOR,
    QueryPlan,
)


_MEMORY_CUES = re.compile(
    r"("
    r"remember|recall|forgot|forget|prefer|preference|\blikes?\b|\bdislike|"
    r"works?\s+at|lives?\s+in|my\s+\w+|who\s+is|what\s+do\s+i|"
    r"when\s+did|did\s+i|have\s+i|remind|about\s+me|"
    r"помн\w*|забыл\w*|предпочит\w*|нрав\w*|работа\w*|живу|кто\s+так|"
    r"что\s+я|когда\s+я|обо\s+мне|люби\w*|не\s+люби"
    r")",
    re.IGNORECASE,
)

_TEMPORAL_CUES = re.compile(
    r"\b(yesterday|today|last\s+week|last\s+month|in\s+\d{4}|before|after|"
    r"вчера|сегодня|раньше|сейчас|в\s+\d{4})\b",
    re.IGNORECASE,
)

_GOAL_CUES = re.compile(
    r"\b(goal|task|todo|deadline|план|задач|цель|дедлайн)\b",
    re.IGNORECASE,
)

_TOOL_CUES = re.compile(
    r"\b(tool_ref|tool result|api result|результат\s+инструмента)\b",
    re.IGNORECASE,
)

_ENTITY_TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё][\w\-']{1,40}", re.UNICODE)


def plan_query(
    query: str,
    *,
    known_entity_labels: Sequence[str] = (),
) -> QueryPlan:
    text = (query or "").strip()
    lowered = text.casefold()
    entities = _extract_entities(text, known_entity_labels)
    reason_codes: list[str] = []
    channels: list[str] = []

    memory_needed = bool(text) and (
        bool(_MEMORY_CUES.search(text))
        or bool(entities)
        or bool(_GOAL_CUES.search(text))
        or bool(_TEMPORAL_CUES.search(text))
        or _looks_personal(lowered)
    )
    if not text:
        memory_needed = False
        reason_codes.append("empty_query")
    elif memory_needed:
        reason_codes.append("memory_cues_or_entities")
    else:
        reason_codes.append("no_memory_signal")

    intent = "none"
    if memory_needed:
        if _GOAL_CUES.search(text):
            intent = "goal_or_task"
        elif _TEMPORAL_CUES.search(text):
            intent = "temporal_fact"
        elif entities:
            intent = "entity_fact"
        else:
            intent = "personal_fact"

    if memory_needed:
        channels.extend(
            [
                CHANNEL_ENTITY,
                CHANNEL_LEXICAL,
                CHANNEL_VECTOR,
                CHANNEL_GRAPH,
                CHANNEL_CHAT,
            ]
        )
        if _TEMPORAL_CUES.search(text) or intent == "temporal_fact":
            channels.append(CHANNEL_TEMPORAL)
            reason_codes.append("temporal_channel")
        if _GOAL_CUES.search(text) or intent == "goal_or_task":
            channels.append(CHANNEL_GOAL)
            reason_codes.append("goal_channel")
        if _TOOL_CUES.search(text) or "tool_ref" in lowered:
            channels.append(CHANNEL_TOOL)
            reason_codes.append("tool_channel")
        # Always schedule document channel so telemetry records the PR9/10 skip.
        channels.append(CHANNEL_DOCUMENT)
    else:
        channels.append(CHANNEL_CHAT)
        channels.append(CHANNEL_DOCUMENT)

    ordered = tuple(dict.fromkeys(ch for ch in channels if ch in ALL_CHANNELS))

    time_range = None
    if _TEMPORAL_CUES.search(text):
        time_range = {"cue": True, "raw": text[:120]}

    subqueries = (
        tuple(dict.fromkeys([text] + [f"entity:{label}" for label in entities[:5]]))
        if text
        else ()
    )

    return QueryPlan(
        memory_needed=memory_needed,
        intent=intent,
        entities=tuple(entities[:12]),
        time_range=time_range,
        required_exactness="supported_fact" if memory_needed else "none",
        channels=ordered,
        subqueries=subqueries,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def _extract_entities(text: str, known: Sequence[str]) -> list[str]:
    found: list[str] = []
    lowered_known = [(label, label.casefold()) for label in known if label]
    for label, key in lowered_known:
        if key and key in text.casefold():
            found.append(label)
    stop = {
        "the",
        "and",
        "for",
        "you",
        "что",
        "как",
        "это",
        "мне",
        "мой",
        "моя",
    }
    for token in _ENTITY_TOKEN.findall(text):
        if len(token) < 3 or token.casefold() in stop:
            continue
        if token[0].isupper() or any(ord(ch) > 127 for ch in token):
            if token not in found:
                found.append(token)
    return found


def _looks_personal(lowered: str) -> bool:
    markers = (
        " i ",
        " my ",
        " me ",
        "я ",
        " мой",
        " моя",
        " мне",
        " у меня",
    )
    padded = f" {lowered} "
    return any(marker in padded for marker in markers)
