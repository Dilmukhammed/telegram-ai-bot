"""Generate text_v1_calibration_r2 pack (40 gold fixtures, round-2 probes)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PACK_DIR = ROOT / "memory" / "eval" / "fixtures" / "text_v1_calibration_r2"
CASES_DIR = PACK_DIR / "cases"

TZ = "Asia/Tashkent"
REF = "2026-07-10T12:00:00+05:00"


def span(text: str, needle: str) -> tuple[int, int]:
    start = text.index(needle)
    return start, start + len(needle)


def _ep(
    *,
    mode: str = "asserted",
    commitment: str = "certain",
    scope: str = "proposition",
    needs_confirmation: bool = False,
    alternatives: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "speaker_commitment": commitment,
        "scope": scope,
        "alternatives": alternatives or [],
        "needs_confirmation": needs_confirmation,
    }


def _ev(event_id: str, text: str, *, relation: str = "supports") -> dict[str, Any]:
    return {
        "source_event": event_id,
        "relation": relation,
        "exact_quote": text,
        "char_start": 0,
        "char_end": len(text),
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


def _chat(
    event_id: str,
    content: str,
    *,
    role: str = "user",
    minute: int = 0,
    user_alias: str = "u1",
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "kind": "chat_message",
        "user_alias": user_alias,
        "role": role,
        "content": content,
        "content_type": "text",
        "occurred_at": f"2026-07-10T09:{minute:02d}:00+05:00",
        "metadata": {},
    }


def _tool(
    event_id: str,
    payload: str,
    *,
    tool_name: str,
    minute: int = 1,
    user_alias: str = "u1",
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "kind": "tool_result",
        "user_alias": user_alias,
        "tool_name": tool_name,
        "payload_kind": "result",
        "payload_json": payload,
        "ok": True,
        "cached": False,
        "occurred_at": f"2026-07-10T09:{minute:02d}:00+05:00",
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
                    "authority_class": (
                        "assistant_generated"
                        if event.get("role") == "assistant"
                        else "user_direct_statement"
                    ),
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
    user_id: int = 3100,
    tier: str = "smoke",
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "fixture_id": fixture_id,
        "title": title,
        "tier": tier,
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
            "notes": ["Round-2 calibration probe."],
        },
    }


def _cand(
    schema_name: str,
    kind: str,
    arguments: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    *,
    polarity: str = "positive",
    epistemic: dict[str, Any] | None = None,
    temporal: dict[str, Any] | None = None,
    status: str = "proposed",
) -> dict[str, Any]:
    return {
        "candidate_ref": "c1",
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


def build_fixtures() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    # --- single-turn basics (1-10) ---
    t = "Я предпочитаю зелёный чай."
    items.append(
        _fixture(
            fixture_id="calib2_ru_pref_101",
            title="Green tea preference",
            language="ru",
            slice_tags=["preference_constraint"],
            user_id=3101,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "prefers",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "зелёный чай"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "I prefer oat milk in coffee."
    items.append(
        _fixture(
            fixture_id="calib2_en_pref_102",
            title="Oat milk preference",
            language="en",
            slice_tags=["preference_constraint"],
            user_id=3102,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "prefers",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "oat milk"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Я архитектор."
    items.append(
        _fixture(
            fixture_id="calib2_ru_occupation_103",
            title="Direct occupation",
            language="ru",
            slice_tags=["direct_attribute_relation"],
            user_id=3103,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "occupation",
                    "entity_attribute",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "архитектор"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "I live in Prague."
    items.append(
        _fixture(
            fixture_id="calib2_en_lives_104",
            title="Residence relation",
            language="en",
            slice_tags=["direct_attribute_relation"],
            user_id=3104,
            events=[_chat("m1", t)],
            mentions=[_mention("prague", "m1", "place", "Prague", t)],
            candidates=[
                _cand(
                    "lives_in",
                    "relation",
                    [
                        {"role": "person", "literal": "self"},
                        {"role": "place", "mention_ref": "prague"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Хочу выучить японский."
    items.append(
        _fixture(
            fixture_id="calib2_ru_goal_105",
            title="Learn language goal",
            language="ru",
            slice_tags=["goal_task_deadline"],
            user_id=3105,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "learn_skill",
                    "goal",
                    [{"role": "subject", "literal": "self"}, {"role": "skill", "literal": "японский"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "I need to renew my passport next month."
    items.append(
        _fixture(
            fixture_id="calib2_en_task_106",
            title="Passport renewal task",
            language="en",
            slice_tags=["goal_task_deadline"],
            user_id=3106,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "renew_passport",
                    "task",
                    [{"role": "subject", "literal": "self"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Я болею."
    items.append(
        _fixture(
            fixture_id="calib2_ru_health_107",
            title="Illness state",
            language="ru",
            slice_tags=["direct_attribute_relation"],
            user_id=3107,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "health_state",
                    "state",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "ill"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "I avoid gluten."
    items.append(
        _fixture(
            fixture_id="calib2_en_diet_108",
            title="Gluten constraint",
            language="en",
            slice_tags=["preference_constraint"],
            user_id=3108,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "dietary_constraint",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "excluded", "literal": "gluten"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Я живу в Москве?"
    items.append(
        _fixture(
            fixture_id="calib2_ru_question_109",
            title="Residence question abstain",
            language="ru",
            slice_tags=["irrelevant_abstention", "hard_negative"],
            user_id=3109,
            events=[_chat("m1", t)],
            candidates=[],
            expect_abstention=True,
            forbidden_candidates=[{"kind": "relation", "schema_name": "lives_in"}],
        )
    )

    t = "What is my occupation?"
    items.append(
        _fixture(
            fixture_id="calib2_en_question_110",
            title="Occupation question abstain",
            language="en",
            slice_tags=["irrelevant_abstention", "hard_negative"],
            user_id=3110,
            events=[_chat("m1", t)],
            candidates=[],
            expect_abstention=True,
            forbidden_candidates=[{"kind": "entity_attribute", "schema_name": "occupation"}],
        )
    )

    # --- uncertainty / modality (11-20) ---
    t = "Возможно, мне нравится джаз."
    items.append(
        _fixture(
            fixture_id="calib2_ru_uncertain_111",
            title="Possible music taste",
            language="ru",
            slice_tags=["uncertainty_alternative", "hard_negative"],
            user_id=3111,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "likes_music",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "джаз"}],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(commitment="possible", needs_confirmation=True),
                    status="needs_confirmation",
                )
            ],
        )
    )

    t = "I'm not sure I like spicy food."
    items.append(
        _fixture(
            fixture_id="calib2_en_uncertain_112",
            title="Uncertain food preference",
            language="en",
            slice_tags=["uncertainty_alternative", "hard_negative"],
            user_id=3112,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "likes",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "spicy food"}],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(commitment="uncertain", needs_confirmation=True),
                    status="needs_confirmation",
                )
            ],
        )
    )

    t = "I no longer work at Stripe."
    items.append(
        _fixture(
            fixture_id="calib2_en_negation_113",
            title="No longer employed",
            language="en",
            slice_tags=["negation", "direct_attribute_relation", "hard_negative"],
            user_id=3113,
            events=[_chat("m1", t)],
            mentions=[_mention("stripe", "m1", "organization", "Stripe", t)],
            candidates=[
                _cand(
                    "works_at",
                    "relation",
                    [
                        {"role": "person", "literal": "self"},
                        {"role": "organization", "mention_ref": "stripe"},
                    ],
                    [_ev("m1", t)],
                    polarity="negative",
                    temporal={
                        "original_text": "no longer",
                        "valid_from": None,
                        "valid_to": "2026-07-10T09:00:00+05:00",
                        "event_time": None,
                        "precision": "second",
                        "timezone": TZ,
                    },
                )
            ],
            forbidden_candidates=[
                {"kind": "relation", "schema_name": "works_at", "polarity": "positive"}
            ],
        )
    )

    t = 'Mila said, "I love classical music."'
    items.append(
        _fixture(
            fixture_id="calib2_en_quote_114",
            title="Quoted music preference",
            language="en",
            slice_tags=["wrong_speaker_hearsay"],
            user_id=3114,
            events=[_chat("m1", t)],
            mentions=[_mention("mila", "m1", "person", "Mila", t)],
            candidates=[
                _cand(
                    "likes_music",
                    "preference",
                    [
                        {"role": "subject", "mention_ref": "mila"},
                        {"role": "value", "literal": "classical music"},
                    ],
                    [_ev("m1", t)],
                    epistemic=_ep(mode="quoted"),
                )
            ],
        )
    )

    t = "Коллега говорит, что Иван уволился."
    items.append(
        _fixture(
            fixture_id="calib2_ru_hearsay_115",
            title="Reported job loss",
            language="ru",
            slice_tags=["wrong_speaker_hearsay", "uncertainty_alternative", "hard_negative"],
            user_id=3115,
            events=[_chat("m1", t)],
            mentions=[
                _mention("colleague", "m1", "person", "Коллега", t),
                _mention("ivan", "m1", "person", "Иван", t),
            ],
            candidates=[
                _cand(
                    "left_job",
                    "event",
                    [{"role": "person", "mention_ref": "ivan"}],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(mode="reported", commitment="possible", needs_confirmation=True),
                    status="needs_confirmation",
                )
            ],
        )
    )

    t = "I seem to be getting sick."
    items.append(
        _fixture(
            fixture_id="calib2_en_inferred_116",
            title="Inferred illness",
            language="en",
            slice_tags=["uncertainty_alternative", "hard_negative"],
            user_id=3116,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "health_state",
                    "state",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "ill"}],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(mode="inferred", commitment="probable", needs_confirmation=True),
                    status="needs_confirmation",
                )
            ],
        )
    )

    t = "Покажи мой календарь на завтра."
    items.append(
        _fixture(
            fixture_id="calib2_ru_command_117",
            title="Calendar command abstain",
            language="ru",
            slice_tags=["irrelevant_abstention", "hard_negative"],
            user_id=3117,
            events=[_chat("m1", t)],
            candidates=[],
            expect_abstention=True,
        )
    )

    t = "Oh great, I just love waking up at 4am."
    items.append(
        _fixture(
            fixture_id="calib2_en_sarcasm_118",
            title="Sarcasm abstain",
            language="en",
            slice_tags=["irrelevant_abstention", "hard_negative"],
            user_id=3118,
            events=[_chat("m1", t)],
            candidates=[],
            expect_abstention=True,
        )
    )

    t = "У меня аллергия на арахис."
    items.append(
        _fixture(
            fixture_id="calib2_ru_allergy_119",
            title="Peanut allergy",
            language="ru",
            slice_tags=["preference_constraint", "direct_attribute_relation"],
            user_id=3119,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "allergic_to",
                    "entity_attribute",
                    [{"role": "subject", "literal": "self"}, {"role": "allergen", "literal": "арахис"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "My hotel budget is $300 per night."
    items.append(
        _fixture(
            fixture_id="calib2_en_budget_120",
            title="Hotel budget limit",
            language="en",
            slice_tags=["preference_constraint"],
            user_id=3120,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "budget_limit",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "amount", "literal": "$300"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    # --- multi-turn moderate (21-32) ---
    m1, m2 = "Я веган.", "Исправление: я больше не веган."
    items.append(
        _fixture(
            fixture_id="calib2_ru_diet_corr_121",
            title="Diet correction",
            language="ru",
            slice_tags=["correction_followup", "multi_turn", "hard_negative"],
            user_id=3121,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            candidates=[
                _cand(
                    "corrects_diet",
                    "correction",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "old", "literal": "vegan"},
                        {"role": "new", "literal": "non_vegan"},
                    ],
                    [_ev("m1", m1), _ev("m2", m2, relation="corrects")],
                    temporal={
                        "original_text": "больше не",
                        "valid_from": "2026-07-10T09:01:00+05:00",
                        "valid_to": None,
                        "event_time": None,
                        "precision": "second",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    m1, m2 = "I'm a nurse.", "Correction: I'm a doctor now."
    items.append(
        _fixture(
            fixture_id="calib2_en_job_corr_122",
            title="Occupation correction",
            language="en",
            slice_tags=["correction_followup", "multi_turn", "hard_negative"],
            user_id=3122,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            candidates=[
                _cand(
                    "corrects_occupation",
                    "correction",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "old", "literal": "nurse"},
                        {"role": "new", "literal": "doctor"},
                    ],
                    [_ev("m1", m1), _ev("m2", m2, relation="corrects")],
                    temporal={
                        "original_text": "now",
                        "valid_from": "2026-07-10T09:01:00+05:00",
                        "valid_to": None,
                        "event_time": None,
                        "precision": "second",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    m1, m2 = "Познакомься с Анной.", "Она моя сестра."
    items.append(
        _fixture(
            fixture_id="calib2_ru_sibling_123",
            title="Pronoun sibling relation",
            language="ru",
            slice_tags=["correction_followup", "multi_turn", "direct_attribute_relation"],
            user_id=3123,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            mentions=[
                _mention("anna", "m1", "person", "Анной", m1, hint="Анна"),
                _mention("she", "m2", "person", "Она", m2),
            ],
            candidates=[
                _cand(
                    "sibling_of",
                    "relation",
                    [
                        {"role": "person", "mention_ref": "she"},
                        {"role": "related_to", "literal": "self"},
                    ],
                    [_ev("m2", m2)],
                )
            ],
        )
    )

    m1, m2 = "Tom works at Helix Labs.", "He's my manager."
    items.append(
        _fixture(
            fixture_id="calib2_en_manager_124",
            title="Manager follow-up",
            language="en",
            slice_tags=["correction_followup", "multi_turn", "direct_attribute_relation"],
            user_id=3124,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            mentions=[
                _mention("tom", "m1", "person", "Tom", m1),
                _mention("helix", "m1", "organization", "Helix Labs", m1),
                _mention("he", "m2", "person", "He", m2),
            ],
            candidates=[
                _cand(
                    "manager_of",
                    "relation",
                    [
                        {"role": "manager", "mention_ref": "he"},
                        {"role": "report", "literal": "self"},
                    ],
                    [_ev("m2", m2)],
                )
            ],
        )
    )

    m1, m2 = "Летом думаю о переезде.", "Возможно, перееду в Астану."
    items.append(
        _fixture(
            fixture_id="calib2_ru_relocate_125",
            title="Possible relocation two-turn",
            language="ru",
            slice_tags=["uncertainty_alternative", "multi_turn", "hard_negative"],
            user_id=3125,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            mentions=[_mention("astana", "m2", "place", "Астану", m2, hint="Астана")],
            candidates=[
                _cand(
                    "moves_to",
                    "event",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "place", "mention_ref": "astana"},
                    ],
                    [_ev("m2", m2)],
                    polarity="unknown",
                    epistemic=_ep(commitment="possible", needs_confirmation=True),
                    status="needs_confirmation",
                )
            ],
        )
    )

    m1, m2 = "I live in Rome.", "No, I now live in Milan."
    items.append(
        _fixture(
            fixture_id="calib2_en_residence_126",
            title="Residence correction",
            language="en",
            slice_tags=["correction_followup", "multi_turn", "direct_attribute_relation"],
            user_id=3126,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            mentions=[
                _mention("rome", "m1", "place", "Rome", m1),
                _mention("milan", "m2", "place", "Milan", m2),
            ],
            candidates=[
                _cand(
                    "corrects_residence",
                    "correction",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "old", "mention_ref": "rome"},
                        {"role": "new", "mention_ref": "milan"},
                    ],
                    [_ev("m1", m1), _ev("m2", m2, relation="corrects")],
                    temporal={
                        "original_text": "now",
                        "valid_from": "2026-07-10T09:01:00+05:00",
                        "valid_to": None,
                        "event_time": None,
                        "precision": "second",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    t = "Поеду либо в Барселону, либо в Валенсию."
    items.append(
        _fixture(
            fixture_id="calib2_ru_dest_127",
            title="Destination alternatives",
            language="ru",
            slice_tags=["uncertainty_alternative", "preference_constraint"],
            user_id=3127,
            events=[_chat("m1", t)],
            mentions=[
                _mention("bcn", "m1", "place", "Барселону", t, hint="Барселона"),
                _mention("vlc", "m1", "place", "Валенсию", t, hint="Валенсия"),
            ],
            candidates=[
                _cand(
                    "destination_choice",
                    "preference",
                    [{"role": "subject", "literal": "self"}],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(
                        commitment="uncertain",
                        needs_confirmation=True,
                        alternatives=["Барселона", "Валенсия"],
                    ),
                    status="needs_confirmation",
                )
            ],
        )
    )

    t = "I prefer quiet hotels."
    items.append(
        _fixture(
            fixture_id="calib2_en_hotel_128",
            title="Quiet hotel constraint",
            language="en",
            slice_tags=["preference_constraint"],
            user_id=3128,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "hotel_constraint",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "quiet"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Нужно сдать отчёт в понедельник."
    items.append(
        _fixture(
            fixture_id="calib2_ru_deadline_129",
            title="Report deadline",
            language="ru",
            slice_tags=["goal_task_deadline", "temporal_precision"],
            user_id=3129,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "submit_report",
                    "task",
                    [{"role": "subject", "literal": "self"}, {"role": "object", "literal": "отчёт"}],
                    [_ev("m1", t)],
                    temporal={
                        "original_text": "в понедельник",
                        "valid_from": None,
                        "valid_to": "2026-07-13T23:59:59+05:00",
                        "event_time": None,
                        "precision": "day",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    t = "I'm training to run a marathon."
    items.append(
        _fixture(
            fixture_id="calib2_en_marathon_130",
            title="Marathon goal",
            language="en",
            slice_tags=["goal_task_deadline"],
            user_id=3130,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "run_marathon",
                    "goal",
                    [{"role": "subject", "literal": "self"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    payload = (
        '{"event":"Стоматолог","date":"2026-07-14","time":"11:00","status":"confirmed"}'
    )
    items.append(
        _fixture(
            fixture_id="calib2_ru_calendar_131",
            title="Calendar tool result",
            language="ru",
            slice_tags=["exact_tool_result", "goal_task_deadline", "temporal_precision", "multi_turn"],
            user_id=3131,
            events=[
                _chat("m1", "Покажи запись к стоматологу.", minute=0),
                _tool("t1", payload, tool_name="google.calendar.events.get", minute=1),
            ],
            candidates=[
                _cand(
                    "calendar_event",
                    "event",
                    [{"role": "subject", "literal": "self"}, {"role": "title", "literal": "Стоматолог"}],
                    [_ev("t1", payload)],
                    epistemic=_ep(mode="retrieved"),
                    temporal={
                        "original_text": "2026-07-14 11:00",
                        "valid_from": None,
                        "valid_to": None,
                        "event_time": "2026-07-14T11:00:00+05:00",
                        "precision": "minute",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    payload = '{"task_id":"task_42","title":"Pay rent","status":"needsAction"}'
    items.append(
        _fixture(
            fixture_id="calib2_en_task_tool_132",
            title="Tasks tool result",
            language="en",
            slice_tags=["exact_tool_result", "goal_task_deadline", "multi_turn"],
            user_id=3132,
            events=[
                _chat("m1", "Show my rent task.", minute=0),
                _tool("t1", payload, tool_name="google.tasks.get", minute=1),
            ],
            candidates=[
                _cand(
                    "open_task",
                    "task",
                    [{"role": "subject", "literal": "self"}, {"role": "title", "literal": "Pay rent"}],
                    [_ev("t1", payload)],
                    epistemic=_ep(mode="retrieved"),
                )
            ],
        )
    )

    # --- mixed / composite (33-40) ---
    t = "I prefer window seats on flights."
    items.append(
        _fixture(
            fixture_id="calib2_en_seat_133",
            title="Window seat preference",
            language="en",
            slice_tags=["preference_constraint"],
            user_id=3133,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "seat_constraint",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "window"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Анна работает в Microsoft."
    items.append(
        _fixture(
            fixture_id="calib2_ru_works_134",
            title="Employment relation",
            language="ru",
            slice_tags=["direct_attribute_relation"],
            user_id=3134,
            events=[_chat("m1", t)],
            mentions=[
                _mention("anna", "m1", "person", "Анна", t),
                _mention("ms", "m1", "organization", "Microsoft", t),
            ],
            candidates=[
                _cand(
                    "works_at",
                    "relation",
                    [
                        {"role": "person", "mention_ref": "anna"},
                        {"role": "organization", "mention_ref": "ms"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Я не уверен, что Петр работает в Яндексе."
    items.append(
        _fixture(
            fixture_id="calib2_ru_uncertain_work_135",
            title="Uncertain employment",
            language="ru",
            slice_tags=["uncertainty_alternative", "hard_negative"],
            user_id=3135,
            events=[_chat("m1", t)],
            mentions=[
                _mention("petr", "m1", "person", "Петр", t),
                _mention("yandex", "m1", "organization", "Яндексе", t, hint="Яндекс"),
            ],
            candidates=[
                _cand(
                    "works_at",
                    "relation",
                    [
                        {"role": "person", "mention_ref": "petr"},
                        {"role": "organization", "mention_ref": "yandex"},
                    ],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(commitment="uncertain", needs_confirmation=True),
                    status="needs_confirmation",
                )
            ],
        )
    )

    t = "У меня есть дети."
    items.append(
        _fixture(
            fixture_id="calib2_ru_children_136",
            title="Has children attribute",
            language="ru",
            slice_tags=["direct_attribute_relation"],
            user_id=3136,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "has_children",
                    "entity_attribute",
                    [{"role": "subject", "literal": "self"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "I own a car."
    items.append(
        _fixture(
            fixture_id="calib2_en_car_137",
            title="Owns car attribute",
            language="en",
            slice_tags=["direct_attribute_relation"],
            user_id=3137,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "owns_car",
                    "entity_attribute",
                    [{"role": "subject", "literal": "self"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Я люблю классическую музыку."
    items.append(
        _fixture(
            fixture_id="calib2_ru_music_138",
            title="Music preference",
            language="ru",
            slice_tags=["preference_constraint"],
            user_id=3138,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "likes_music",
                    "preference",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "value", "literal": "классическая музыка"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "I like flying."
    items.append(
        _fixture(
            fixture_id="calib2_en_flying_139",
            title="Likes flying",
            language="en",
            slice_tags=["preference_constraint"],
            user_id=3139,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "likes_flying",
                    "preference",
                    [{"role": "subject", "literal": "self"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    m1, m2 = "Я живу в Самарканде.", "Нет, теперь я живу в Бухаре."
    items.append(
        _fixture(
            fixture_id="calib2_ru_residence_corr_140",
            title="Residence correction UZ",
            language="ru",
            slice_tags=["correction_followup", "multi_turn", "direct_attribute_relation"],
            user_id=3140,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            mentions=[
                _mention("sam", "m1", "place", "Самарканде", m1, hint="Самарканд"),
                _mention("bukh", "m2", "place", "Бухаре", m2, hint="Бухара"),
            ],
            candidates=[
                _cand(
                    "corrects_residence",
                    "correction",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "old", "mention_ref": "sam"},
                        {"role": "new", "mention_ref": "bukh"},
                    ],
                    [_ev("m1", m1), _ev("m2", m2, relation="corrects")],
                    temporal={
                        "original_text": "теперь",
                        "valid_from": "2026-07-10T09:01:00+05:00",
                        "valid_to": None,
                        "event_time": None,
                        "precision": "second",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    if len(items) != 40:
        raise RuntimeError(f"expected 40 fixtures, got {len(items)}")
    return items


def main() -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    fixtures = build_fixtures()
    for item in fixtures:
        path = CASES_DIR / f"{item['fixture_id']}.json"
        path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ru = sum(1 for item in fixtures if item["language"] == "ru")
    en = sum(1 for item in fixtures if item["language"] == "en")
    mixed = sum(1 for item in fixtures if item["language"] == "mixed")
    multi = sum(1 for item in fixtures if "multi_turn" in item["slice_tags"])
    hard = sum(1 for item in fixtures if "hard_negative" in item["slice_tags"])

    manifest = {
        "schema_version": "1",
        "pack_id": "text_v1_calibration_r2",
        "pack_version": "1",
        "fixtures": [f"cases/{item['fixture_id']}.json" for item in fixtures],
        "coverage": {
            "fixture_count": 40,
            "smoke_count": 40,
            "language_minimums": {"ru": ru, "en": en, "mixed": mixed},
            "slice_minimums": {
                "correction_followup": 4,
                "direct_attribute_relation": 8,
                "negation": 1,
                "uncertainty_alternative": 5,
                "wrong_speaker_hearsay": 2,
                "exact_tool_result": 2,
                "goal_task_deadline": 6,
                "temporal_precision": 2,
                "preference_constraint": 8,
                "hard_negative": hard,
                "multi_turn": multi,
                "irrelevant_abstention": 4,
            },
            "smoke_slice_minimums": {
                "correction_followup": 1,
                "direct_attribute_relation": 1,
                "preference_constraint": 1,
                "multi_turn": 1,
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

    gate_path = ROOT / "memory" / "eval" / "fixtures" / "gates" / "text_v1_calibration_r2.json"
    gate_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "gate_id": "text_v1_calibration_r2",
                "gate_version": "1",
                "pack_id": "text_v1_calibration_r2",
                "pack_version": "1",
                "pack_hash": pack.pack_hash,
                "subject_type": "all",
                "gates": [
                    {"metric": "fixture_schema_validity", "comparison": "gte", "threshold": 1.0, "active": True},
                    {"metric": "corpus_coverage", "comparison": "gte", "threshold": 1.0, "active": False},
                    {"metric": "release_fixtures_reviewed", "comparison": "gte", "threshold": 1.0, "active": False},
                    {"metric": "matching_metrics_golden", "comparison": "gte", "threshold": 1.0, "active": False},
                    {"metric": "deterministic_replay", "comparison": "gte", "threshold": 1.0, "active": False},
                    {"metric": "mention_precision", "comparison": "gte", "threshold": 0.85, "active": True, "subjects": ["extraction"]},
                    {"metric": "mention_recall", "comparison": "gte", "threshold": 0.80, "active": True, "subjects": ["extraction"]},
                    {"metric": "candidate_precision", "comparison": "gte", "threshold": 0.85, "active": True, "subjects": ["extraction"]},
                    {"metric": "candidate_recall", "comparison": "gte", "threshold": 0.75, "active": True, "subjects": ["extraction"]},
                    {"metric": "unsupported_candidate_rate", "comparison": "lte", "threshold": 0.05, "active": True, "subjects": ["extraction"]},
                    {"metric": "evidence_pointer_accuracy", "comparison": "gte", "threshold": 0.95, "active": True, "subjects": ["extraction"]},
                    {"metric": "exact_quote_accuracy", "comparison": "gte", "threshold": 0.95, "active": True, "subjects": ["extraction"]},
                    {"metric": "negation_scope_accuracy", "comparison": "gte", "threshold": 0.90, "active": True, "subjects": ["extraction"]},
                    {"metric": "uncertainty_scope_accuracy", "comparison": "gte", "threshold": 0.90, "active": True, "subjects": ["extraction"]},
                    {"metric": "wrong_speaker_count", "comparison": "lte", "threshold": 0, "active": True, "subjects": ["extraction"]},
                    {"metric": "forbidden_candidate_count", "comparison": "lte", "threshold": 0, "active": True, "subjects": ["extraction"]},
                    {"metric": "irrelevant_false_positive_rate", "comparison": "lte", "threshold": 0.05, "active": True, "subjects": ["extraction"]},
                    {"metric": "malformed_accepted_output_count", "comparison": "lte", "threshold": 0, "active": True, "subjects": ["extraction"]},
                ],
                "hard_zero_failure_codes": ["fixture_invalid", "subject_error", "subject_timeout"],
                "minimum_slice_counts": {"total": 40, "tier:smoke": 40},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {len(fixtures)} fixtures to {PACK_DIR}")
    print(f"pack_hash={pack.pack_hash}")
    print(f"gate_config={gate_path}")


if __name__ == "__main__":
    main()
