"""Generate text_v1_verification_v2 pack (30 PR4 verification probes)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PACK_DIR = ROOT / "memory" / "eval" / "fixtures" / "text_v1_verification_v2"
CASES_DIR = PACK_DIR / "cases"
EXPECTATIONS_PATH = ROOT / "memory" / "eval" / "fixtures" / "verification_v2.json"

TZ = "Asia/Tashkent"
REF = "2026-07-11T12:00:00+05:00"

_ADVERSARIAL_SLICES = {
    "negation",
    "uncertainty_alternative",
    "wrong_speaker_hearsay",
    "correction_followup",
    "goal_task_deadline",
    "temporal_precision",
    "multi_turn",
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
        "occurred_at": f"2026-07-11T09:{minute:02d}:00+05:00",
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
        "occurred_at": f"2026-07-11T09:{minute:02d}:00+05:00",
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
    user_id: int = 3200,
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
            "notes": ["PR4 verification v2 probe."],
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


def _verification_expectation(fixture: dict[str, Any]) -> dict[str, Any]:
    if fixture["expected"].get("expect_abstention"):
        return {"outcomes": [], "forbid_unexpected_advancement": True}
    candidates = fixture["expected"]["candidates"]
    if not candidates:
        return {"outcomes": [], "forbid_unexpected_advancement": True}
    tags = set(fixture["slice_tags"])
    adversarial = bool(tags & _ADVERSARIAL_SLICES) and "exact_tool_result" not in tags
    outcomes = []
    for candidate in candidates:
        outcomes.append(
            {
                "candidate_ref": str(candidate["candidate_ref"]),
                "status": "ready_for_resolution",
                "verdict": "supported",
                "adversarial": adversarial,
            }
        )
    return {
        "outcomes": outcomes,
        "forbid_unexpected_advancement": True,
    }


def build_fixtures() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    t = "Пью только чёрный кофе без сахара."
    items.append(
        _fixture(
            fixture_id="verify3_ru_pref_201",
            title="Black coffee preference",
            language="ru",
            slice_tags=["preference_constraint"],
            user_id=3201,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "prefers",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "чёрный кофе"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "I avoid crowded restaurants."
    items.append(
        _fixture(
            fixture_id="verify3_en_pref_202",
            title="Restaurant avoidance",
            language="en",
            slice_tags=["preference_constraint"],
            user_id=3202,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "avoids",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "crowded restaurants"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Я продуктовый дизайнер в Notion."
    items.append(
        _fixture(
            fixture_id="verify3_ru_occupation_203",
            title="Product designer role",
            language="ru",
            slice_tags=["direct_attribute_relation"],
            user_id=3203,
            events=[_chat("m1", t)],
            mentions=[_mention("notion", "m1", "organization", "Notion", t)],
            candidates=[
                _cand(
                    "works_at",
                    "relation",
                    [
                        {"role": "person", "literal": "self"},
                        {"role": "organization", "mention_ref": "notion"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "We relocated to Tallinn last spring."
    items.append(
        _fixture(
            fixture_id="verify3_en_residence_204",
            title="Tallinn residence",
            language="en",
            slice_tags=["direct_attribute_relation"],
            user_id=3204,
            events=[_chat("m1", t)],
            mentions=[_mention("tallinn", "m1", "place", "Tallinn", t)],
            candidates=[
                _cand(
                    "lives_in",
                    "relation",
                    [
                        {"role": "person", "literal": "self"},
                        {"role": "place", "mention_ref": "tallinn"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Собираюсь сдать IELTS в декабре."
    items.append(
        _fixture(
            fixture_id="verify3_ru_goal_205",
            title="IELTS goal",
            language="ru",
            slice_tags=["goal_task_deadline", "temporal_precision"],
            user_id=3205,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "exam_goal",
                    "goal",
                    [{"role": "subject", "literal": "self"}, {"role": "exam", "literal": "IELTS"}],
                    [_ev("m1", t)],
                    temporal={
                        "original_text": "в декабре",
                        "valid_from": None,
                        "valid_to": None,
                        "event_time": "2026-12-01T00:00:00+05:00",
                        "precision": "month",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    t = "Remind me to renew my driver's license next week."
    items.append(
        _fixture(
            fixture_id="verify3_en_task_206",
            title="License renewal task",
            language="en",
            slice_tags=["goal_task_deadline"],
            user_id=3206,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "renew_license",
                    "task",
                    [{"role": "subject", "literal": "self"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "У меня непереносимость лактозы."
    items.append(
        _fixture(
            fixture_id="verify3_ru_health_207",
            title="Lactose intolerance",
            language="ru",
            slice_tags=["preference_constraint", "direct_attribute_relation"],
            user_id=3207,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "dietary_constraint",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "excluded", "literal": "лактоза"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "I'm pescatarian."
    items.append(
        _fixture(
            fixture_id="verify3_en_diet_208",
            title="Pescatarian diet",
            language="en",
            slice_tags=["preference_constraint"],
            user_id=3208,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "dietary_label",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "pescatarian"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Я живу в Астане?"
    items.append(
        _fixture(
            fixture_id="verify3_ru_question_209",
            title="Residence question abstain",
            language="ru",
            slice_tags=["irrelevant_abstention", "hard_negative"],
            user_id=3209,
            events=[_chat("m1", t)],
            candidates=[],
            expect_abstention=True,
            forbidden_candidates=[{"kind": "relation", "schema_name": "lives_in"}],
        )
    )

    t = "What allergies do I have?"
    items.append(
        _fixture(
            fixture_id="verify3_en_question_210",
            title="Allergy question abstain",
            language="en",
            slice_tags=["irrelevant_abstention", "hard_negative"],
            user_id=3210,
            events=[_chat("m1", t)],
            candidates=[],
            expect_abstention=True,
            forbidden_candidates=[{"kind": "entity_attribute", "schema_name": "allergic_to"}],
        )
    )

    t = "Возможно, перееду в Алматы."
    items.append(
        _fixture(
            fixture_id="verify3_ru_uncertain_211",
            title="Possible relocation",
            language="ru",
            slice_tags=["uncertainty_alternative", "hard_negative"],
            user_id=3211,
            events=[_chat("m1", t)],
            mentions=[_mention("almaty", "m1", "place", "Алматы", t, hint="Алматы")],
            candidates=[
                _cand(
                    "relocating_to",
                    "goal",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "place", "mention_ref": "almaty"},
                    ],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(commitment="possible", needs_confirmation=True),
                    status="needs_confirmation",
                )
            ],
        )
    )

    t = "I might switch teams next quarter."
    items.append(
        _fixture(
            fixture_id="verify3_en_uncertain_212",
            title="Possible team switch",
            language="en",
            slice_tags=["uncertainty_alternative", "hard_negative"],
            user_id=3212,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "team_change",
                    "goal",
                    [{"role": "subject", "literal": "self"}],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(commitment="possible", needs_confirmation=True),
                    status="needs_confirmation",
                )
            ],
        )
    )

    t = "Я больше не курю."
    items.append(
        _fixture(
            fixture_id="verify3_ru_negation_213",
            title="Stopped smoking",
            language="ru",
            slice_tags=["negation", "direct_attribute_relation", "hard_negative"],
            user_id=3213,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "smokes",
                    "state",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "false"}],
                    [_ev("m1", t)],
                    polarity="negative",
                    temporal={
                        "original_text": "больше не",
                        "valid_from": None,
                        "valid_to": "2026-07-11T09:00:00+05:00",
                        "event_time": None,
                        "precision": "second",
                        "timezone": TZ,
                    },
                )
            ],
            forbidden_candidates=[{"kind": "state", "schema_name": "smokes", "polarity": "positive"}],
        )
    )

    t = "I no longer own a car."
    items.append(
        _fixture(
            fixture_id="verify3_en_negation_214",
            title="No car ownership",
            language="en",
            slice_tags=["negation", "direct_attribute_relation", "hard_negative"],
            user_id=3214,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "owns_car",
                    "state",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "false"}],
                    [_ev("m1", t)],
                    polarity="negative",
                    temporal={
                        "original_text": "no longer",
                        "valid_from": None,
                        "valid_to": "2026-07-11T09:00:00+05:00",
                        "event_time": None,
                        "precision": "second",
                        "timezone": TZ,
                    },
                )
            ],
            forbidden_candidates=[{"kind": "state", "schema_name": "owns_car", "polarity": "positive"}],
        )
    )

    t = 'Nora said, "I adore sushi."'
    items.append(
        _fixture(
            fixture_id="verify3_en_quote_215",
            title="Quoted sushi preference",
            language="en",
            slice_tags=["wrong_speaker_hearsay"],
            user_id=3215,
            events=[_chat("m1", t)],
            mentions=[_mention("nora", "m1", "person", "Nora", t)],
            candidates=[
                _cand(
                    "likes_food",
                    "preference",
                    [
                        {"role": "subject", "mention_ref": "nora"},
                        {"role": "value", "literal": "sushi"},
                    ],
                    [_ev("m1", t)],
                    epistemic=_ep(mode="quoted"),
                )
            ],
        )
    )

    t = "Сосед сказал, что Петр уехал в командировку."
    items.append(
        _fixture(
            fixture_id="verify3_ru_hearsay_216",
            title="Reported business trip",
            language="ru",
            slice_tags=["wrong_speaker_hearsay", "uncertainty_alternative", "hard_negative"],
            user_id=3216,
            events=[_chat("m1", t)],
            mentions=[
                _mention("neighbor", "m1", "person", "Сосед", t),
                _mention("petr", "m1", "person", "Петр", t),
            ],
            candidates=[
                _cand(
                    "traveling",
                    "event",
                    [{"role": "person", "mention_ref": "petr"}],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(mode="reported", commitment="possible", needs_confirmation=True),
                    status="needs_confirmation",
                )
            ],
        )
    )

    t = "I appear to be catching a cold."
    items.append(
        _fixture(
            fixture_id="verify3_en_inferred_217",
            title="Inferred illness",
            language="en",
            slice_tags=["uncertainty_alternative", "hard_negative"],
            user_id=3217,
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

    t = "Открой мои задачи на сегодня."
    items.append(
        _fixture(
            fixture_id="verify3_ru_command_218",
            title="Tasks command abstain",
            language="ru",
            slice_tags=["irrelevant_abstention", "hard_negative"],
            user_id=3218,
            events=[_chat("m1", t)],
            candidates=[],
            expect_abstention=True,
        )
    )

    t = "Wonderful, I just adore Monday mornings."
    items.append(
        _fixture(
            fixture_id="verify3_en_sarcasm_219",
            title="Sarcasm abstain",
            language="en",
            slice_tags=["irrelevant_abstention", "hard_negative"],
            user_id=3219,
            events=[_chat("m1", t)],
            candidates=[],
            expect_abstention=True,
        )
    )

    t = "У меня аллергия на киви."
    items.append(
        _fixture(
            fixture_id="verify3_ru_allergy_220",
            title="Kiwi allergy",
            language="ru",
            slice_tags=["preference_constraint", "direct_attribute_relation"],
            user_id=3220,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "allergic_to",
                    "entity_attribute",
                    [{"role": "subject", "literal": "self"}, {"role": "allergen", "literal": "киви"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "My travel budget is €1200."
    items.append(
        _fixture(
            fixture_id="verify3_en_budget_221",
            title="Travel budget",
            language="en",
            slice_tags=["preference_constraint"],
            user_id=3221,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "budget_limit",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "amount", "literal": "€1200"}],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    m1, m2 = "Я вегетарианец.", "Уточнение: я больше не вегетарианец."
    items.append(
        _fixture(
            fixture_id="verify3_ru_corr_222",
            title="Vegetarian correction",
            language="ru",
            slice_tags=["correction_followup", "multi_turn", "hard_negative"],
            user_id=3222,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            candidates=[
                _cand(
                    "diet_correction",
                    "correction",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "old", "literal": "вегетарианец"},
                        {"role": "new", "literal": "не вегетарианец"},
                    ],
                    [_ev("m1", m1), _ev("m2", m2, relation="corrects")],
                    temporal={
                        "original_text": "больше не",
                        "valid_from": "2026-07-11T09:01:00+05:00",
                        "valid_to": None,
                        "event_time": None,
                        "precision": "second",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    m1, m2 = "I work in Berlin.", "Correction: I now work in Munich."
    items.append(
        _fixture(
            fixture_id="verify3_en_corr_223",
            title="City correction",
            language="en",
            slice_tags=["correction_followup", "multi_turn", "hard_negative"],
            user_id=3223,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            mentions=[
                _mention("berlin", "m1", "place", "Berlin", m1),
                _mention("munich", "m2", "place", "Munich", m2),
            ],
            candidates=[
                _cand(
                    "corrects_workplace",
                    "correction",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "old", "mention_ref": "berlin"},
                        {"role": "new", "mention_ref": "munich"},
                    ],
                    [_ev("m1", m1), _ev("m2", m2, relation="corrects")],
                )
            ],
        )
    )

    t = "Моя сестра Оля живёт в Казани."
    items.append(
        _fixture(
            fixture_id="verify3_ru_sibling_224",
            title="Sister residence",
            language="ru",
            slice_tags=["direct_attribute_relation"],
            user_id=3224,
            events=[_chat("m1", t)],
            mentions=[
                _mention("olya", "m1", "person", "Оля", t),
                _mention("kazan", "m1", "place", "Казани", t, hint="Казань"),
            ],
            candidates=[
                _cand(
                    "lives_in",
                    "relation",
                    [
                        {"role": "person", "mention_ref": "olya"},
                        {"role": "place", "mention_ref": "kazan"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "I report to Elena."
    items.append(
        _fixture(
            fixture_id="verify3_en_manager_225",
            title="Manager relation",
            language="en",
            slice_tags=["direct_attribute_relation"],
            user_id=3225,
            events=[_chat("m1", t)],
            mentions=[_mention("elena", "m1", "person", "Elena", t)],
            candidates=[
                _cand(
                    "reports_to",
                    "relation",
                    [
                        {"role": "person", "literal": "self"},
                        {"role": "manager", "mention_ref": "elena"},
                    ],
                    [_ev("m1", t)],
                )
            ],
        )
    )

    t = "Думаю переехать в Варшаву осенью."
    items.append(
        _fixture(
            fixture_id="verify3_ru_relocate_226",
            title="Planned relocation",
            language="ru",
            slice_tags=["goal_task_deadline", "uncertainty_alternative", "temporal_precision"],
            user_id=3226,
            events=[_chat("m1", t)],
            mentions=[_mention("warsaw", "m1", "place", "Варшаву", t, hint="Варшава")],
            candidates=[
                _cand(
                    "relocating_to",
                    "goal",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "place", "mention_ref": "warsaw"},
                    ],
                    [_ev("m1", t)],
                    polarity="unknown",
                    epistemic=_ep(commitment="probable", needs_confirmation=True),
                    status="needs_confirmation",
                    temporal={
                        "original_text": "осенью",
                        "valid_from": None,
                        "valid_to": None,
                        "event_time": "2026-09-01T00:00:00+05:00",
                        "precision": "month",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    t = "I moved to Lisbon this year."
    items.append(
        _fixture(
            fixture_id="verify3_en_residence_227",
            title="Lisbon residence",
            language="en",
            slice_tags=["direct_attribute_relation", "temporal_precision"],
            user_id=3227,
            events=[_chat("m1", t)],
            mentions=[_mention("lisbon", "m1", "place", "Lisbon", t)],
            candidates=[
                _cand(
                    "lives_in",
                    "relation",
                    [
                        {"role": "person", "literal": "self"},
                        {"role": "place", "mention_ref": "lisbon"},
                    ],
                    [_ev("m1", t)],
                    temporal={
                        "original_text": "this year",
                        "valid_from": "2026-01-01T00:00:00+00:00",
                        "valid_to": None,
                        "event_time": None,
                        "precision": "year",
                        "timezone": "UTC",
                    },
                )
            ],
        )
    )

    m1, m2 = "Book a quiet hotel.", "I prefer boutique hotels near the center."
    items.append(
        _fixture(
            fixture_id="verify3_en_hotel_228",
            title="Hotel preference follow-up",
            language="en",
            slice_tags=["preference_constraint", "multi_turn"],
            user_id=3228,
            events=[_chat("m1", m1, minute=0), _chat("m2", m2, minute=1)],
            candidates=[
                _cand(
                    "hotel_preference",
                    "preference",
                    [{"role": "subject", "literal": "self"}, {"role": "value", "literal": "boutique hotels"}],
                    [_ev("m2", m2)],
                )
            ],
        )
    )

    t = "Дедлайн по отчёту — 20 июля."
    items.append(
        _fixture(
            fixture_id="verify3_ru_deadline_229",
            title="Report deadline",
            language="ru",
            slice_tags=["goal_task_deadline", "temporal_precision"],
            user_id=3229,
            events=[_chat("m1", t)],
            candidates=[
                _cand(
                    "report_deadline",
                    "task",
                    [{"role": "subject", "literal": "self"}, {"role": "title", "literal": "отчёт"}],
                    [_ev("m1", t)],
                    temporal={
                        "original_text": "20 июля",
                        "valid_from": None,
                        "valid_to": None,
                        "event_time": "2026-07-20T00:00:00+05:00",
                        "precision": "day",
                        "timezone": TZ,
                    },
                )
            ],
        )
    )

    payload = json.dumps(
        {"flight": "HY704", "departure": "2026-07-18T08:15:00+05:00", "seat": "14A"},
        ensure_ascii=False,
    )
    items.append(
        _fixture(
            fixture_id="verify3_en_tool_230",
            title="Flight tool result",
            language="en",
            slice_tags=["exact_tool_result", "goal_task_deadline", "multi_turn"],
            user_id=3230,
            events=[
                _chat("m1", "Show my flight booking.", minute=0),
                _tool("t1", payload, tool_name="travel.flights.get", minute=1),
            ],
            candidates=[
                _cand(
                    "flight_booking",
                    "event",
                    [
                        {"role": "subject", "literal": "self"},
                        {"role": "flight", "literal": "HY704"},
                    ],
                    [_ev("t1", payload)],
                    epistemic=_ep(mode="retrieved"),
                )
            ],
        )
    )

    if len(items) != 30:
        raise RuntimeError(f"expected 30 fixtures, got {len(items)}")
    return items


def refresh_pack_metadata() -> None:
    fixtures = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(CASES_DIR.glob("verify3_*.json"))
    ]
    ru = sum(1 for item in fixtures if item["language"] == "ru")
    en = sum(1 for item in fixtures if item["language"] == "en")
    mixed = sum(1 for item in fixtures if item["language"] == "mixed")
    multi = sum(1 for item in fixtures if "multi_turn" in item["slice_tags"])
    hard = sum(1 for item in fixtures if "hard_negative" in item["slice_tags"])
    manifest = {
        "schema_version": "1",
        "pack_id": "text_v1_verification_v2",
        "pack_version": "1",
        "fixtures": [f"cases/{item['fixture_id']}.json" for item in fixtures],
        "coverage": {
            "fixture_count": len(fixtures),
            "smoke_count": len(fixtures),
            "language_minimums": {"ru": ru, "en": en, "mixed": mixed},
            "slice_minimums": {
                "correction_followup": 2,
                "direct_attribute_relation": 6,
                "negation": 2,
                "uncertainty_alternative": 4,
                "wrong_speaker_hearsay": 2,
                "exact_tool_result": 1,
                "goal_task_deadline": 5,
                "temporal_precision": 4,
                "preference_constraint": 6,
                "hard_negative": hard,
                "multi_turn": multi,
                "irrelevant_abstention": 4,
            },
            "smoke_slice_minimums": {
                "correction_followup": 1,
                "direct_attribute_relation": 1,
                "preference_constraint": 1,
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
        "pack_id": "verification_v2",
        "base_pack_id": "text_v1_verification_v2",
        "review": {
            "status": "draft",
            "reviewed_by": None,
            "reviewed_at": None,
            "notes": [
                "PR4 verification v2 expectations calibrated from extraction gold.",
                "Re-run verification eval after extraction stabilizes.",
            ],
        },
        "cases": {
            item["fixture_id"]: _verification_expectation(item) for item in fixtures
        },
    }
    EXPECTATIONS_PATH.write_text(
        json.dumps(expectations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    gate_path = ROOT / "memory" / "eval" / "fixtures" / "gates" / "text_v1_verification_v2.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["pack_hash"] = pack.pack_hash
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"pack_hash={pack.pack_hash}")


def main() -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    fixtures = build_fixtures()
    for item in fixtures:
        path = CASES_DIR / f"{item['fixture_id']}.json"
        path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    refresh_pack_metadata()
    gate_path = ROOT / "memory" / "eval" / "fixtures" / "gates" / "text_v1_verification_v2.json"
    print(f"Wrote {len(fixtures)} fixtures to {PACK_DIR}")
    print(f"expectations={EXPECTATIONS_PATH}")
    print(f"gate_config={gate_path}")


if __name__ == "__main__":
    main()
