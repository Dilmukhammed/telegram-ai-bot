from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from memory.extraction.schemas import CandidateDraft, ExtractionResult, Temporal


_WEEKDAYS: tuple[tuple[tuple[str, ...], int], ...] = (
    (("monday", "понедельник", "понедельника"), 0),
    (("tuesday", "вторник", "вторника"), 1),
    (("wednesday", "среда", "среду", "среды"), 2),
    (("thursday", "четверг", "четверга"), 3),
    (("friday", "пятница", "пятницу", "пятницы"), 4),
    (("saturday", "суббота", "субботу", "субботы"), 5),
    (("sunday", "воскресенье", "воскресенья"), 6),
)

_RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def normalize_text_temporal(
    result: ExtractionResult,
    *,
    segment_text: str,
    occurred_at: str | None,
    timezone: str,
) -> ExtractionResult:
    if not result.candidates:
        return result
    local = (
        datetime.fromisoformat(occurred_at).astimezone(ZoneInfo(timezone))
        if occurred_at is not None
        else None
    )
    candidates = tuple(
        _normalize_candidate(candidate, segment_text=segment_text, local=local, timezone=timezone)
        for candidate in result.candidates
    )
    return result if candidates == result.candidates else replace(result, candidates=candidates)


def _normalize_candidate(
    candidate: CandidateDraft,
    *,
    segment_text: str,
    local: datetime | None,
    timezone: str,
) -> CandidateDraft:
    folded = segment_text.casefold()

    if candidate.kind == "preference" and (
        "on weekends" in folded or "по выходным" in folded
    ):
        return replace(candidate, temporal=None)
    if ("похоже" in folded or "seems" in folded or "appears" in folded) and (
        candidate.temporal is not None
        and candidate.temporal.original_text.casefold() in {"уже", "already"}
    ):
        candidate = replace(candidate, temporal=None)
    if candidate.epistemic.mode.value == "retrieved" and candidate.temporal is not None:
        return candidate
    if local is None:
        return candidate

    if candidate.kind == "correction":
        marker = _first_marker(segment_text, ("moved", "переехал", "переехала", "теперь"))
        if marker is not None:
            return replace(
                candidate,
                temporal=_temporal(
                    marker,
                    timezone,
                    valid_from=_iso(local),
                    precision="second",
                ),
            )

    marker = _first_marker(segment_text, ("no longer", "больше не"))
    if marker is not None:
        return replace(
            candidate,
            temporal=_temporal(
                marker,
                timezone,
                valid_from=_iso(local) if candidate.polarity.value == "negative" else None,
                valid_to=None if candidate.polarity.value == "negative" else _iso(local),
                precision="second",
            ),
        )

    spring = re.search(r"\bnext\s+spring\b", segment_text, re.IGNORECASE)
    if spring is not None:
        year = local.year + 1
        start = local.replace(year=year, month=3, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = local.replace(year=year, month=5, day=31, hour=23, minute=59, second=59, microsecond=0)
        return replace(
            candidate,
            temporal=_temporal(
                spring.group(0),
                timezone,
                valid_from=_iso(start),
                valid_to=_iso(end),
                precision="season",
            ),
        )

    month_end = re.search(
        r"до\s+конца\s+(" + "|".join(_RU_MONTHS) + r")",
        segment_text,
        re.IGNORECASE,
    )
    if month_end is not None:
        month = _RU_MONTHS[month_end.group(1).casefold()]
        year = local.year if month >= local.month else local.year + 1
        day = monthrange(year, month)[1]
        end = local.replace(
            year=year,
            month=month,
            day=day,
            hour=23,
            minute=59,
            second=59,
            microsecond=0,
        )
        return replace(
            candidate,
            temporal=_temporal(
                month_end.group(0),
                timezone,
                valid_to=_iso(end),
                precision="month",
            ),
        )

    tomorrow = re.search(r"\b(tomorrow|завтра)\b", segment_text, re.IGNORECASE)
    if tomorrow is not None:
        hour, minute = _extract_time(segment_text)
        target = (local + timedelta(days=1)).replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        return replace(
            candidate,
            temporal=_temporal(
                tomorrow.group(0),
                timezone,
                event_time=_iso(target),
                precision="day",
            ),
        )

    weekday = _find_weekday(segment_text)
    if weekday is not None:
        marker_text, target_weekday = weekday
        hour, minute = _extract_time(segment_text)
        delta = (target_weekday - local.weekday()) % 7
        target = (local + timedelta(days=delta)).replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        deadline = bool(re.search(r"\bby\b|\bдо\b", folded))
        original = f"by {marker_text}" if deadline and "by" in folded else marker_text
        if marker_text.casefold() in {
            "пятница",
            "пятницу",
            "пятницы",
            "понедельник",
            "понедельника",
            "вторник",
            "вторника",
            "среда",
            "среду",
            "среды",
            "четверг",
            "четверга",
            "суббота",
            "субботу",
            "субботы",
            "воскресенье",
            "воскресенья",
        }:
            prefix = segment_text[max(0, segment_text.casefold().find(marker_text.casefold()) - 2) :]
            if prefix.casefold().startswith("в "):
                original = prefix[: 2 + len(marker_text)]
        return replace(
            candidate,
            temporal=_temporal(
                original,
                timezone,
                valid_to=_iso(target) if deadline else None,
                event_time=None if deadline else _iso(target),
                precision="day",
            ),
        )

    today = _first_marker(segment_text, ("today", "сегодня"))
    if today is not None:
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        end = local.replace(hour=23, minute=59, second=59, microsecond=0)
        return replace(
            candidate,
            temporal=_temporal(
                today,
                timezone,
                valid_from=_iso(start),
                valid_to=_iso(end),
                precision="day",
            ),
        )

    now = _first_marker(segment_text, ("now", "теперь"))
    if now is not None:
        return replace(
            candidate,
            temporal=_temporal(
                now,
                timezone,
                valid_from=_iso(local),
                precision="second",
            ),
        )
    fallback_patterns = (
        (r"\bnext\s+week\b", "second"),
        (r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})\b", "second"),
        (r"\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b", "second"),
        (r"\b(?:в\s+)?(?:январе|феврале|марте|апреле|мае|июне|июле|августе|сентябре|октябре|ноябре|декабре)\b", "month"),
        (r"\b(?:осенью|зимой|весной|летом)\b", "season"),
    )
    for pattern, precision in fallback_patterns:
        marker = re.search(pattern, segment_text, re.IGNORECASE)
        if marker is not None:
            return replace(
                candidate,
                temporal=_temporal(marker.group(0), timezone, precision=precision),
            )
    return candidate


def _extract_time(text: str) -> tuple[int, int]:
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?\b", text, re.IGNORECASE)
    if match is None:
        return 0, 0
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").upper()
    if meridiem == "PM" and hour < 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    return hour, minute


def _find_weekday(text: str) -> tuple[str, int] | None:
    for names, weekday in _WEEKDAYS:
        for name in names:
            match = re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE)
            if match is not None:
                return match.group(0), weekday
    return None


def _first_marker(text: str, markers: tuple[str, ...]) -> str | None:
    folded = text.casefold()
    for marker in markers:
        start = folded.find(marker.casefold())
        if start >= 0:
            return text[start : start + len(marker)]
    return None


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _temporal(
    original_text: str,
    timezone: str,
    *,
    valid_from: str | None = None,
    valid_to: str | None = None,
    event_time: str | None = None,
    precision: str,
) -> Temporal:
    return Temporal(
        original_text=original_text,
        valid_from=valid_from,
        valid_to=valid_to,
        event_time=event_time,
        precision=precision,
        timezone=timezone,
    )
