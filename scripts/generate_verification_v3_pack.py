"""Generate text_v1_verification_v3 pack (30 PR4 scenario probes, round 3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PACK_DIR = ROOT / "memory" / "eval" / "fixtures" / "text_v1_verification_v3"
CASES_DIR = PACK_DIR / "cases"
EXPECTATIONS_PATH = ROOT / "memory" / "eval" / "fixtures" / "verification_v3.json"
GATE_PATH = ROOT / "memory" / "eval" / "fixtures" / "gates" / "text_v1_verification_v3.json"

TZ = "Asia/Tashkent"
REF = "2026-07-11T16:00:00+05:00"

_ADVERSARIAL_SLICES = {
    "negation",
    "uncertainty_alternative",
    "wrong_speaker_hearsay",
    "correction_followup",
    "goal_task_deadline",
    "temporal_precision",
    "multi_turn",
    "tutoring_group",
    "game_session",
}


def span(text: str, needle: str) -> tuple[int, int]:
    start = text.index(needle)
    return start, start + len(needle)


def _ep(
    *,
    mode: str = "asserted",
    commitment: str = "certain",
    scope: str = "proposition",
    needs_confirmation: bool = False,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "speaker_commitment": commitment,
        "scope": scope,
        "alternatives": [],
        "needs_confirmation": needs_confirmation,
    }


def _ev(event_id: str, text: str, *, relation: str = "supports") -> dict[str, Any]:
    start, end = 0, len(text)
    return {
        "source_event": event_id,
        "relation": relation,
        "exact_quote": text,
        "char_start": start,
        "char_end": end,
    }


def _mention(
    mention_id: str,
    event_id: str,
    mention_type: str,
    surface: str,
    segment_text: str,
    *,
    hint: str | None = None,
) -> dict[str, Any]:
    start, end = span(segment_text, surface)
    return {
        "mention_id": mention_id,
        "source_event": event_id,
        "mention_type": mention_type,
        "surface_text": surface,
        "char_start": start,
        "char_end": end,
        "normalized_hint": hint if hint is not None else surface,
        "pointer": {"source_event": event_id, "char_start": start, "char_end": end},
    }


def _chat(event_id: str, content: str, *, minute: int = 0) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "kind": "chat_message",
        "user_alias": "u1",
        "role": "user",
        "content": content,
        "content_type": "text",
        "occurred_at": f"2026-07-11T10:{minute:02d}:00+05:00",
        "metadata": {},
    }


def _tool(event_id: str, payload: str, *, tool_name: str, minute: int = 1) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "kind": "tool_result",
        "user_alias": "u1",
        "tool_name": tool_name,
        "payload_kind": "result",
        "payload_json": payload,
        "ok": True,
        "cached": False,
        "occurred_at": f"2026-07-11T10:{minute:02d}:00+05:00",
    }


def _sources(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if event["kind"] == "chat_message":
            rows.append(
                {
                    "source_event": event["event_id"],
                    "source_type": "chat_message",
                    "source_ref_alias": event["event_id"],
                    "authority_class": "user_direct_statement",
                    "content_hash_rule": "chat_content_hash",
                    "source_version_count": 1,
                    "pointer": {"source_event": event["event_id"]},
                    "normalization_job_status": "done",
                }
            )
        else:
            rows.append(
                {
                    "source_event": event["event_id"],
                    "source_type": "tool_result",
                    "source_ref_alias": event["event_id"],
                    "authority_class": "tool_api_result",
                    "content_hash_rule": "sha256_raw_payload",
                    "source_version_count": 1,
                    "pointer": {"source_event": event["event_id"]},
                    "normalization_job_status": "done",
                }
            )
    return rows


def _segments(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if event["kind"] == "chat_message":
            rows.append(
                {
                    "source_event": event["event_id"],
                    "segment_type": "chat_text",
                    "ordinal": 0,
                    "text": event["content"],
                    "normalizer_version": "1",
                    "pointer": {"source_event": event["event_id"]},
                }
            )
        else:
            rows.append(
                {
                    "source_event": event["event_id"],
                    "segment_type": "tool_payload",
                    "ordinal": 0,
                    "text": event["payload_json"],
                    "normalizer_version": "1",
                    "pointer": {"source_event": event["event_id"]},
                }
            )
    return rows


def _fixture(
    *,
    fixture_id: str,
    title: str,
    language: str,
    slice_tags: list[str],
    events: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    mentions: list[dict[str, Any]] | None = None,
    expect_abstention: bool = False,
    forbidden_candidates: list[dict[str, Any]] | None = None,
    user_id: int = 3300,
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "fixture_id": fixture_id,
        "title": title,
        "tier": "smoke",
        "language": language,
        "criticality": "critical",
        "slice_tags": slice_tags,
        "reference_time": REF,
        "timezone": TZ,
        "users": [
            {
                "user_alias": "u1",
                "user_id": user_id,
                "display_name": "Synthetic User",
                "metadata": {"synthetic": True},
            }
        ],
        "events": events,
        "expected": {
            "sources": _sources(events),
            "segments": _segments(events),
            "mentions": mentions or [],
            "candidates": candidates,
            "forbidden_candidates": forbidden_candidates or [],
            "expect_abstention": expect_abstention,
            "forbidden_sources": (
                [{"source_type": "tool_summary"}]
                if any(event["kind"] == "tool_result" for event in events)
                else []
            ),
            "forbidden_segments": (
                [{"segment_type": "tool_summary"}]
                if any(event["kind"] == "tool_result" for event in events)
                else []
            ),
        },
        "review": {
            "status": "draft",
            "reviewed_by": None,
            "reviewed_at": None,
            "notes": ["PR4 verification v3 scenario probe."],
        },
    }


def _cand(
    schema_name: str,
    kind: str,
    arguments: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    *,
    ref: str = "c1",
    polarity: str = "positive",
    epistemic: dict[str, Any] | None = None,
    temporal: dict[str, Any] | None = None,
    status: str = "proposed",
) -> dict[str, Any]:
    return {
        "candidate_ref": ref,
        "kind": kind,
        "schema_name": schema_name,
        "schema_version": "1",
        "arguments": arguments,
        "attributes": {},
        "polarity": polarity,
        "epistemic": epistemic or _ep(),
        "temporal": temporal,
        "status": status,
        "evidence": evidence,
    }


def _verification_expectation(fixture: dict[str, Any]) -> dict[str, Any]:
    if fixture["expected"].get("expect_abstention"):
        return {"outcomes": [], "forbid_unexpected_advancement": True}
    candidates = fixture["expected"]["candidates"]
    if not candidates:
        return {"outcomes": [], "forbid_unexpected_advancement": True}
    tags = set(fixture["slice_tags"])
    adversarial = bool(tags & _ADVERSARIAL_SLICES) and "exact_tool_result" not in tags
    return {
        "outcomes": [
            {
                "candidate_ref": str(candidate["candidate_ref"]),
                "status": "ready_for_resolution",
                "verdict": "supported",
                "adversarial": adversarial,
            }
            for candidate in candidates
        ],
        "forbid_unexpected_advancement": True,
    }


def build_fixtures() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    # --- tutoring / groups (231-240) ---
    t = "Создал группу Математика-1 для учеников."
    items.append(
        _fixture(
            fixture_id="verify4_ru_group_231",
            title="Create tutoring group",
            language="ru",
            slice_tags=["tutoring_group", "direct_attribute_relation"],
            user_id=3301,
            events=[_chat("m1", t)],
            mentions=[_mention("math1", "m1", "organization", "Математика-1", t)],
            candidates=[
                _cand(
                    "teaches_group",
                    "relation",
                    [
                        {"role": "person", "literal": "self"},
                        {"role": "group", "mention_ref": "math1"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Иван учится в группе Математика-1 по книге Моро."
    items.append(
        _fixture(
            fixture_id="verify4_ru_student_232",
            title="Student group and textbook",
            language="ru",
            slice_tags=["tutoring_group", "multi_turn"],
            user_id=3302,
            events=[_chat("m1", t)],
            mentions=[
                _mention("ivan", "m1", "person", "Иван", t),
                _mention("math1", "m1", "organization", "Математика-1", t),
                _mention("moro", "m1", "concept", "Моро", t, hint="Моро"),
            ],
            candidates=[
                _cand(
                    "studies_in",
                    "relation",
                    [
                        {"role": "person", "mention_ref": "ivan"},
                        {"role": "group", "mention_ref": "math1"},
                    ],
                    [_ev("m1", t)],
                ),
                _cand(
                    "uses_textbook",
                    "preference",
                    [
                        {"role": "subject", "mention_ref": "ivan"},
                        {"role": "value", "mention_ref": "moro"},
                    ],
                    [_ev("m1", t)],
                    ref="c2",
                ),
            ],
        )
    )

    t = "Maria has lessons on Tuesday and Thursday at 6pm."
    items.append(
        _fixture(
            fixture_id="verify4_en_schedule_233",
            title="Student lesson schedule",
            language="en",
            slice_tags=["tutoring_group", "goal_task_deadline", "temporal_precision"],
            user_id=3303,
            events=[_chat("m1", t)],
            mentions=[_mention("maria", "m1", "person", "Maria", t)],
            candidates=[
                _cand(
                    "lesson_schedule",
                    "event",
                    [
                        {"role": "person", "mention_ref": "maria"},
                        {"role": "pattern", "literal": "Tuesday and Thursday 6pm"},
                    ],
                    [_ev("m1", t)],
                    temporal={
                        "original_text": "Tuesday and Thursday at 6pm",
                        "valid_from": None,
                        "valid_to": None,
                        "event_time": None,
                        "precision": "minute",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    m1, m2 = "Группа Математика-1 уже есть.", "Добавь Алису в Математика-1."
    items.append(
        _fixture(
            fixture_id="verify4_ru_group_add_234",
            title="Add student to existing group",
            language="ru",
            slice_tags=["tutoring_group", "multi_turn", "correction_followup"],
            user_id=3304,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            mentions=[
                _mention("math1", "m1", "organization", "Математика-1", m1),
                _mention("alisa", "m2", "person", "Алису", m2, hint="Алиса"),
                _mention("math1b", "m2", "organization", "Математика-1", m2),
            ],
            candidates=[
                _cand(
                    "adds_to_group",
                    "event",
                    [
                        {"role": "person", "mention_ref": "alisa"},
                        {"role": "group", "mention_ref": "math1b"},
                    ],
                    [_ev("m1", m1), _ev("m2", m2, relation="supports")],
                )
            ],
        )
    )

    t = "Я репетитор по математике."
    items.append(
        _fixture(
            fixture_id="verify4_ru_tutor_235",
            title="Tutor subject",
            language="ru",
            slice_tags=["tutoring_group", "direct_attribute_relation"],
            user_id=3305,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "occupation",
                    "entity_attribute",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "value", "literal": "репетитор по математике"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "We use Algebra II with the English B1 group."
    items.append(
        _fixture(
            fixture_id="verify4_en_textbook_236",
            title="Group textbook",
            language="en",
            slice_tags=["tutoring_group", "preference_constraint"],
            user_id=3306,
            events=[_chat("m1", t)],
            mentions=[_mention("engb1", "m1", "organization", "English B1", t)],
            candidates=[
                _cand(
                    "uses_textbook",
                    "preference",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "value", "literal": "Algebra II"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Урок с Петром в среду в 19:00."
    items.append(
        _fixture(
            fixture_id="verify4_ru_lesson_237",
            title="Single lesson appointment",
            language="ru",
            slice_tags=["tutoring_group", "goal_task_deadline", "temporal_precision"],
            user_id=3307,
            events=[_chat("m1", t)],
            mentions=[_mention("petr", "m1", "person", "Петром", t, hint="Пётр")],
            candidates=[
                _cand(
                    "lesson_event",
                    "event",
                    [
                        {"role": "person", "mention_ref": "petr"},
                        {"role": "time", "literal": "среда 19:00"},
                    ],
                    [_ev("m1", t)],
                    temporal={
                        "original_text": "в среду в 19:00",
                        "valid_from": None,
                        "valid_to": None,
                        "event_time": "2026-07-16T19:00:00+05:00",
                        "precision": "minute",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    t = "Оля — сестра Ивана из Математика-1."
    items.append(
        _fixture(
            fixture_id="verify4_ru_sibling_class_238",
            title="Sibling in same class",
            language="ru",
            slice_tags=["tutoring_group", "direct_attribute_relation"],
            user_id=3308,
            events=[_chat("m1", t)],
            mentions=[
                _mention("olya", "m1", "person", "Оля", t),
                _mention("ivan", "m1", "person", "Ивана", t, hint="Иван"),
                _mention("math1", "m1", "organization", "Математика-1", t),
            ],
            candidates=[
                _cand(
                    "sibling_of",
                    "relation",
                    [
                        {"role": "person", "mention_ref": "olya"},
                        {"role": "related_to", "mention_ref": "ivan"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "I prefer short homework tasks for beginners."
    items.append(
        _fixture(
            fixture_id="verify4_en_tutor_pref_239",
            title="Tutor teaching preference",
            language="en",
            slice_tags=["tutoring_group", "preference_constraint"],
            user_id=3309,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "prefers",
                    "preference",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "value", "literal": "short homework tasks"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Расписание группы лежит в Google Sheets, ссылку скину позже."
    items.append(
        _fixture(
            fixture_id="verify4_ru_material_ref_240",
            title="Schedule material reference",
            language="ru",
            slice_tags=["tutoring_group", "goal_task_deadline"],
            user_id=3310,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "material_location",
                    "task",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "location", "literal": "Google Sheets"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    # --- game sessions (241-248) ---
    t = "I'm playing Baldur's Gate 3, help with quests."
    items.append(
        _fixture(
            fixture_id="verify4_en_game_241",
            title="Active game session",
            language="en",
            slice_tags=["game_session", "goal_task_deadline"],
            user_id=3311,
            events=[_chat("m1", t)],
            mentions=[_mention("bg3", "m1", "concept", "Baldur's Gate 3", t)],
            candidates=[
                _cand(
                    "plays_game",
                    "goal",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "game", "mention_ref": "bg3"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Сейчас я в Акте 2, в Shadow-cursed Lands."
    items.append(
        _fixture(
            fixture_id="verify4_ru_game_zone_242",
            title="In-game location",
            language="ru",
            slice_tags=["game_session", "direct_attribute_relation"],
            user_id=3312,
            events=[_chat("m1", t)],
            mentions=[_mention("scl", "m1", "place", "Shadow-cursed Lands", t)],
            candidates=[
                _cand(
                    "game_location",
                    "state",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "place", "mention_ref": "scl"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "I picked up the Nectar of Victory in Grymforge."
    items.append(
        _fixture(
            fixture_id="verify4_en_game_item_243",
            title="In-game item pickup",
            language="en",
            slice_tags=["game_session", "direct_attribute_relation"],
            user_id=3313,
            events=[_chat("m1", t)],
            mentions=[_mention("grym", "m1", "place", "Grymforge", t)],
            candidates=[
                _cand(
                    "acquired_item",
                    "event",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "item", "literal": "Nectar of Victory"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Мой персонаж 12 уровня."
    items.append(
        _fixture(
            fixture_id="verify4_ru_game_level_244",
            title="Character level",
            language="ru",
            slice_tags=["game_session", "direct_attribute_relation"],
            user_id=3314,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "character_level",
                    "entity_attribute",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "value", "literal": "12"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Running a dex/int Eldritch Knight build."
    items.append(
        _fixture(
            fixture_id="verify4_en_game_build_245",
            title="Character build",
            language="en",
            slice_tags=["game_session", "preference_constraint"],
            user_id=3315,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "character_build",
                    "preference",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "value", "literal": "dex/int Eldritch Knight"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Победил Grym в подземелье."
    items.append(
        _fixture(
            fixture_id="verify4_ru_game_boss_246",
            title="Boss defeated",
            language="ru",
            slice_tags=["game_session", "goal_task_deadline"],
            user_id=3316,
            events=[_chat("m1", t)],
            mentions=[_mention("grym", "m1", "person", "Grym", t)],
            candidates=[
                _cand(
                    "defeated",
                    "event",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "target", "mention_ref": "grym"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "I might respec into a pure wizard later."
    items.append(
        _fixture(
            fixture_id="verify4_en_game_uncertain_247",
            title="Possible build change",
            language="en",
            slice_tags=["game_session", "uncertainty_alternative", "hard_negative"],
            user_id=3317,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "build_change",
                    "goal",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "wizard"}],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(commitment="possible", needs_confirmation=True),
                    status="needs_confirmation",
                )
            ],
        )
    )

    t = "Нужно найти Nightsong для квеста Aylin."
    items.append(
        _fixture(
            fixture_id="verify4_ru_game_quest_248",
            title="Active quest goal",
            language="ru",
            slice_tags=["game_session", "goal_task_deadline"],
            user_id=3318,
            events=[_chat("m1", t)],
            mentions=[_mention("aylin", "m1", "person", "Aylin", t)],
            candidates=[
                _cand(
                    "quest_goal",
                    "goal",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "object", "literal": "Nightsong"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    # --- PR4 core probes (249-260) ---
    t = "Я больше не пью кофе по вечерам."
    items.append(
        _fixture(
            fixture_id="verify4_ru_negation_249",
            title="Evening coffee negation",
            language="ru",
            slice_tags=["negation", "preference_constraint", "hard_negative"],
            user_id=3319,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "drinks_coffee",
                    "preference",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "value", "literal": "coffee evenings"},
                    ],
                    [_ev("m1", t)],
                    polarity="negative",
                    temporal={
                        "original_text": "больше не",
                        "valid_from": None,
                        "valid_to": "2026-07-11T10:00:00+05:00",
                        "event_time": None,
                        "precision": "second",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    t = "I no longer teach on Sundays."
    items.append(
        _fixture(
            fixture_id="verify4_en_negation_250",
            title="Sunday teaching negation",
            language="en",
            slice_tags=["negation", "tutoring_group", "hard_negative"],
            user_id=3320,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "teaches_on",
                    "event",
                    [{"role": "subject", "literal": "self"}, {"role": "day", "literal": "Sunday"}],
                    [_ev("m1", t)],
                    polarity="negative",
                )
            ],
        )
    )

    t = "Родитель сказал, что Маша болеет."
    items.append(
        _fixture(
            fixture_id="verify4_ru_hearsay_251",
            title="Reported student illness",
            language="ru",
            slice_tags=["wrong_speaker_hearsay", "tutoring_group", "hard_negative"],
            user_id=3321,
            events=[_chat("m1", t)],
            mentions=[
                _mention("parent", "m1", "person", "Родитель", t),
                _mention("masha", "m1", "person", "Маша", t),
            ],
            candidates=[
                _cand(
                    "health_state",
                    "state",
                    [
                        {"role": "subject", "mention_ref": "masha"},
                        {"role": "value", "literal": "ill"},
                    ],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(mode="reported", commitment="possible", needs_confirmation=True),
                    status="needs_confirmation",
                )
            ],
        )
    )

    t = 'Anna said, "I love geometry."'
    items.append(
        _fixture(
            fixture_id="verify4_en_quote_252",
            title="Quoted student preference",
            language="en",
            slice_tags=["wrong_speaker_hearsay", "tutoring_group"],
            user_id=3322,
            events=[_chat("m1", t)],
            mentions=[_mention("anna", "m1", "person", "Anna", t)],
            candidates=[
                _cand(
                    "likes_subject",
                    "preference",
                    [
                        {"role": "subject", "mention_ref": "anna"},
                        {"role": "value", "literal": "geometry"},
                    ],
                    [_ev("m1", t)],
                    epistemic=_ep(mode="quoted"),
                )
            ],
        )
    )

    m1, m2 = "Иван учится по Моро.", "Исправление: теперь по Виленкину."
    items.append(
        _fixture(
            fixture_id="verify4_ru_book_corr_253",
            title="Textbook correction",
            language="ru",
            slice_tags=["correction_followup", "tutoring_group", "multi_turn"],
            user_id=3323,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            mentions=[
                _mention("ivan", "m1", "person", "Иван", m1),
                _mention("moro", "m1", "concept", "Моро", m1),
                _mention("vilen", "m2", "concept", "Виленкину", m2, hint="Виленкин"),
            ],
            candidates=[
                _cand(
                    "corrects_textbook",
                    "correction",
                    [
                        {"role": "subject", "mention_ref": "ivan"},
                        {"role": "old", "mention_ref": "moro"},
                        {"role": "new", "mention_ref": "vilen"},
                    ],
                    [_ev("m1", m1), _ev("m2", m2, relation="corrects")],
                )
            ],
        )
    )

    m1, m2 = "Lesson in room 3.", "Correction: room 5 now."
    items.append(
        _fixture(
            fixture_id="verify4_en_room_corr_254",
            title="Lesson room correction",
            language="en",
            slice_tags=["correction_followup", "tutoring_group", "multi_turn"],
            user_id=3324,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            candidates=[
                _cand(
                    "corrects_selection",
                    "correction",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "old", "literal": "room 3"},
                        {"role": "new", "literal": "room 5"},
                    ],
                    [_ev("m1", m1), _ev("m2", m2, relation="corrects")],
                )
            ],
        )
    )

    t = "Возможно, перенесу урок Ивана на пятницу."
    items.append(
        _fixture(
            fixture_id="verify4_ru_lesson_uncertain_255",
            title="Possible lesson reschedule",
            language="ru",
            slice_tags=["tutoring_group", "uncertainty_alternative", "hard_negative"],
            user_id=3325,
            events=[_chat("m1", t)],
            mentions=[_mention("ivan", "m1", "person", "Ивана", t, hint="Иван")],
            candidates=[
                _cand(
                    "reschedule_lesson",
                    "goal",
                    [
                        {"role": "person", "mention_ref": "ivan"},
                        {"role": "day", "literal": "пятница"},
                    ],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(commitment="possible", needs_confirmation=True),
                    status="needs_confirmation",
                )
            ],
        )
    )

    payload = json.dumps(
        {"title": "Math-1 lesson", "start": "2026-07-16T18:00:00+05:00", "room": "5"},
        ensure_ascii=False,
    )
    items.append(
        _fixture(
            fixture_id="verify4_en_tool_lesson_256",
            title="Lesson calendar tool result",
            language="en",
            slice_tags=["exact_tool_result", "tutoring_group", "multi_turn"],
            user_id=3326,
            events=[
                _chat("m1", "Show tomorrow's Math-1 lesson.", minute=0),
                _tool("t1", payload, tool_name="google.calendar.events.get", minute=1),
            ],
            candidates=[
                _cand(
                    "calendar_event",
                    "event",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "title", "literal": "Math-1 lesson"},
                    ],
                    [_ev("t1", payload)],
                    epistemic=_ep(mode="retrieved"),
                )
            ],
        )
    )

    t = "Кто учится в Математика-1?"
    items.append(
        _fixture(
            fixture_id="verify4_ru_question_257",
            title="Group roster question abstain",
            language="ru",
            slice_tags=["irrelevant_abstention", "hard_negative"],
            user_id=3327,
            events=[_chat("m1", t)],
            candidates=[],
            expect_abstention=True,
            forbidden_candidates=[{"kind": "relation", "schema_name": "studies_in"}],
        )
    )

    t = "Export the student schedule to PDF."
    items.append(
        _fixture(
            fixture_id="verify4_en_command_258",
            title="Export command abstain",
            language="en",
            slice_tags=["irrelevant_abstention", "hard_negative"],
            user_id=3328,
            events=[_chat("m1", t)],
            candidates=[],
            expect_abstention=True,
        )
    )

    t = "Ставлю только письменные домашние задания."
    items.append(
        _fixture(
            fixture_id="verify4_ru_homework_pref_259",
            title="Homework style preference",
            language="ru",
            slice_tags=["tutoring_group", "preference_constraint"],
            user_id=3329,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "prefers",
                    "preference",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "value", "literal": "письменные домашние задания"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    m1, m2 = "Need a quiet classroom.", "I prefer groups of up to four students."
    items.append(
        _fixture(
            fixture_id="verify4_en_class_pref_260",
            title="Class size preference follow-up",
            language="en",
            slice_tags=["tutoring_group", "multi_turn", "preference_constraint"],
            user_id=3330,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            candidates=[
                _cand(
                    "class_size_preference",
                    "preference",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "value", "literal": "up to four students"},
                    ],
                    [_ev("m2", m2)],
                )
            ],
        )
    )

    if len(items) != 30:
        raise RuntimeError(f"expected 30 fixtures, got {len(items)}")
    return items


def _gate_template(pack_hash: str) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "gate_id": "text_v1_verification_v3",
        "gate_version": "1",
        "pack_id": "text_v1_verification_v3",
        "pack_version": "1",
        "pack_hash": pack_hash,
        "subject_type": "all",
        "gates": [
            {"metric": "fixture_schema_validity", "comparison": "gte", "threshold": 1.0, "active": True},
            {"metric": "corpus_coverage", "comparison": "gte", "threshold": 1.0, "active": False},
            {"metric": "release_fixtures_reviewed", "comparison": "gte", "threshold": 1.0, "active": False},
            {"metric": "matching_metrics_golden", "comparison": "gte", "threshold": 1.0, "active": False},
            {"metric": "deterministic_replay", "comparison": "gte", "threshold": 1.0, "active": False},
            {
                "metric": "mention_precision",
                "comparison": "gte",
                "threshold": 0.80,
                "active": True,
                "subjects": ["extraction"],
            },
            {
                "metric": "candidate_precision",
                "comparison": "gte",
                "threshold": 0.80,
                "active": True,
                "subjects": ["extraction"],
            },
            {
                "metric": "candidate_recall",
                "comparison": "gte",
                "threshold": 0.70,
                "active": True,
                "subjects": ["extraction"],
            },
            {
                "metric": "unsupported_candidate_rate",
                "comparison": "lte",
                "threshold": 0.10,
                "active": True,
                "subjects": ["extraction"],
            },
            {
                "metric": "verification_fixtures_reviewed",
                "comparison": "gte",
                "threshold": 1.0,
                "active": False,
                "subjects": ["verification"],
            },
            {
                "metric": "verification_precision",
                "comparison": "gte",
                "threshold": 0.85,
                "active": True,
                "subjects": ["verification"],
            },
            {
                "metric": "verification_recall",
                "comparison": "gte",
                "threshold": 0.80,
                "active": True,
                "subjects": ["verification"],
            },
            {
                "metric": "verifier_false_accept_rate",
                "comparison": "lte",
                "threshold": 0.05,
                "active": True,
                "subjects": ["verification"],
            },
            {
                "metric": "verifier_false_reject_rate",
                "comparison": "lte",
                "threshold": 0.10,
                "active": True,
                "subjects": ["verification"],
            },
            {
                "metric": "forbidden_advancement_count",
                "comparison": "lte",
                "threshold": 0,
                "active": True,
                "subjects": ["verification"],
            },
            {
                "metric": "ready_for_resolution_precision",
                "comparison": "gte",
                "threshold": 0.90,
                "active": True,
                "subjects": ["verification"],
            },
            {
                "metric": "verification_scope_accuracy",
                "comparison": "gte",
                "threshold": 0.85,
                "active": True,
                "subjects": ["verification"],
            },
            {
                "metric": "verification_job_completion",
                "comparison": "gte",
                "threshold": 1.0,
                "active": True,
                "subjects": ["verification"],
            },
        ],
        "hard_zero_failure_codes": [
            "fixture_invalid",
            "forbidden_advancement",
            "pointer_owner_mismatch",
            "pointer_dereference_failed",
        ],
        "minimum_slice_counts": {"total": 30, "tier:smoke": 30},
    }


def refresh_pack_metadata() -> None:
    fixtures = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(CASES_DIR.glob("verify4_*.json"))
    ]
    ru = sum(1 for item in fixtures if item["language"] == "ru")
    en = sum(1 for item in fixtures if item["language"] == "en")
    multi = sum(1 for item in fixtures if len(item["events"]) > 1)
    multi_tag = sum(1 for item in fixtures if "multi_turn" in item["slice_tags"])
    hard = sum(1 for item in fixtures if "hard_negative" in item["slice_tags"])
    tutoring = sum(1 for item in fixtures if "tutoring_group" in item["slice_tags"])
    game = sum(1 for item in fixtures if "game_session" in item["slice_tags"])

    manifest = {
        "schema_version": "1",
        "pack_id": "text_v1_verification_v3",
        "pack_version": "1",
        "fixtures": [f"cases/{item['fixture_id']}.json" for item in fixtures],
        "coverage": {
            "fixture_count": len(fixtures),
            "smoke_count": len(fixtures),
            "language_minimums": {"ru": ru, "en": en, "mixed": 0},
            "slice_minimums": {
                "tutoring_group": tutoring,
                "game_session": game,
                "correction_followup": 2,
                "negation": 2,
                "uncertainty_alternative": 1,
                "wrong_speaker_hearsay": 2,
                "exact_tool_result": 1,
                "goal_task_deadline": 6,
                "preference_constraint": 4,
                "hard_negative": hard,
                "multi_turn": multi_tag,
                "irrelevant_abstention": 2,
            },
            "smoke_slice_minimums": {
                "tutoring_group": 5,
                "game_session": 3,
                "multi_turn": 1,
                "exact_tool_result": 1,
            },
            "multi_turn_minimum": multi,
            "hard_negative_minimum": hard,
            "require_reviewed": False,
        },
    }
    manifest_path = PACK_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    from memory.eval.loader import load_pack

    pack = load_pack(PACK_DIR)
    manifest["pack_hash"] = pack.pack_hash
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    expectations = {
        "schema_version": "1",
        "pack_id": "verification_v3",
        "base_pack_id": "text_v1_verification_v3",
        "review": {
            "status": "draft",
            "reviewed_by": None,
            "reviewed_at": None,
            "notes": [
                "PR4 verification v3 scenario pack (tutoring + game + core probes).",
                "Run extraction calibration before treating verification expectations as final.",
            ],
        },
        "cases": {item["fixture_id"]: _verification_expectation(item) for item in fixtures},
    }
    EXPECTATIONS_PATH.write_text(
        json.dumps(expectations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    GATE_PATH.write_text(
        json.dumps(_gate_template(pack.pack_hash), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"pack_hash={pack.pack_hash}")


def main() -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    fixtures = build_fixtures()
    for item in fixtures:
        path = CASES_DIR / f"{item['fixture_id']}.json"
        path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    refresh_pack_metadata()
    print(f"Wrote {len(fixtures)} fixtures to {PACK_DIR}")
    print(f"expectations={EXPECTATIONS_PATH}")
    print(f"gate_config={GATE_PATH}")


if __name__ == "__main__":
    main()
