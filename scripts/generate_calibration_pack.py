"""Generate text_v1_calibration probe pack (10 fixtures)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PACK_DIR = ROOT / "memory" / "eval" / "fixtures" / "text_v1_calibration"
CASES_DIR = PACK_DIR / "cases"

TZ = "Asia/Tashkent"
REF = "2026-07-10T12:00:00+05:00"


def span(text: str, needle: str) -> tuple[int, int]:
    start = text.index(needle)
    return start, start + len(needle)


def write_fixture(item: dict) -> None:
    path = CASES_DIR / f"{item['fixture_id']}.json"
    path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    fixtures: list[dict] = []

    m1, m2 = "По профессии я дизайнер.", "Исправление: теперь я продакт-менеджер."
    fixtures.append(
        {
            "schema_version": "1",
            "fixture_id": "calib_ru_occupation_065",
            "title": "Occupation correction probe",
            "tier": "smoke",
            "language": "ru",
            "criticality": "critical",
            "slice_tags": [
                "correction_followup",
                "direct_attribute_relation",
                "multi_turn",
                "hard_negative",
            ],
            "reference_time": REF,
            "timezone": TZ,
            "users": [
                {
                    "user_alias": "u1",
                    "user_id": 2065,
                    "display_name": "Synthetic User",
                    "metadata": {"synthetic": True},
                }
            ],
            "events": [
                {
                    "event_id": "m1",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": m1,
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:00:00+05:00",
                    "metadata": {},
                },
                {
                    "event_id": "m2",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": m2,
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:01:00+05:00",
                    "metadata": {},
                },
            ],
            "expected": {
                "sources": [
                    {
                        "source_event": "m1",
                        "source_type": "chat_message",
                        "source_ref_alias": "m1",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m1"},
                        "normalization_job_status": "done",
                    },
                    {
                        "source_event": "m2",
                        "source_type": "chat_message",
                        "source_ref_alias": "m2",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m2"},
                        "normalization_job_status": "done",
                    },
                ],
                "segments": [
                    {
                        "source_event": "m1",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": m1,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m1"},
                    },
                    {
                        "source_event": "m2",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": m2,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m2"},
                    },
                ],
                "mentions": [],
                "candidates": [
                    {
                        "candidate_ref": "c1",
                        "kind": "correction",
                        "schema_name": "corrects_occupation",
                        "schema_version": "1",
                        "arguments": [
                            {"role": "subject", "literal": "self"},
                            {"role": "old", "literal": "designer"},
                            {"role": "new", "literal": "product_manager"},
                        ],
                        "attributes": {},
                        "polarity": "positive",
                        "epistemic": {
                            "mode": "asserted",
                            "speaker_commitment": "certain",
                            "scope": "proposition",
                            "alternatives": [],
                            "needs_confirmation": False,
                        },
                        "temporal": {
                            "original_text": "теперь",
                            "valid_from": "2026-07-10T09:01:00+05:00",
                            "valid_to": None,
                            "event_time": None,
                            "precision": "second",
                            "timezone": TZ,
                        },
                        "status": "proposed",
                        "evidence": [
                            {
                                "source_event": "m1",
                                "relation": "supports",
                                "exact_quote": m1,
                                "char_start": 0,
                                "char_end": len(m1),
                            },
                            {
                                "source_event": "m2",
                                "relation": "corrects",
                                "exact_quote": m2,
                                "char_start": 0,
                                "char_end": len(m2),
                            },
                        ],
                    }
                ],
                "forbidden_candidates": [
                    {
                        "kind": "entity_attribute",
                        "schema_name": "occupation",
                        "arguments": [{"role": "value", "literal": "designer"}],
                    }
                ],
                "expect_abstention": False,
                "forbidden_sources": [],
                "forbidden_segments": [],
            },
            "review": {
                "status": "draft",
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": ["Calibration probe for PR3 extraction pipeline."],
            },
        }
    )

    m1 = "I no longer work at Northstar."
    ps, pe = span(m1, "Northstar")
    fixtures.append(
        {
            "schema_version": "1",
            "fixture_id": "calib_en_negation_066",
            "title": "No longer employed probe",
            "tier": "smoke",
            "language": "en",
            "criticality": "critical",
            "slice_tags": ["negation", "direct_attribute_relation", "hard_negative"],
            "reference_time": REF,
            "timezone": TZ,
            "users": [
                {
                    "user_alias": "u1",
                    "user_id": 2066,
                    "display_name": "Synthetic User",
                    "metadata": {"synthetic": True},
                }
            ],
            "events": [
                {
                    "event_id": "m1",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": m1,
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:00:00+05:00",
                    "metadata": {},
                }
            ],
            "expected": {
                "sources": [
                    {
                        "source_event": "m1",
                        "source_type": "chat_message",
                        "source_ref_alias": "m1",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m1"},
                        "normalization_job_status": "done",
                    }
                ],
                "segments": [
                    {
                        "source_event": "m1",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": m1,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m1"},
                    }
                ],
                "mentions": [
                    {
                        "mention_id": "northstar",
                        "source_event": "m1",
                        "mention_type": "organization",
                        "surface_text": "Northstar",
                        "char_start": ps,
                        "char_end": pe,
                        "normalized_hint": "Northstar",
                        "pointer": {"source_event": "m1", "char_start": ps, "char_end": pe},
                    }
                ],
                "candidates": [
                    {
                        "candidate_ref": "c1",
                        "kind": "relation",
                        "schema_name": "works_at",
                        "schema_version": "1",
                        "arguments": [
                            {"role": "person", "literal": "self"},
                            {"role": "organization", "mention_ref": "northstar"},
                        ],
                        "attributes": {},
                        "polarity": "negative",
                        "epistemic": {
                            "mode": "asserted",
                            "speaker_commitment": "certain",
                            "scope": "proposition",
                            "alternatives": [],
                            "needs_confirmation": False,
                        },
                        "temporal": {
                            "original_text": "no longer",
                            "valid_from": None,
                            "valid_to": "2026-07-10T09:00:00+05:00",
                            "event_time": None,
                            "precision": "second",
                            "timezone": TZ,
                        },
                        "status": "proposed",
                        "evidence": [
                            {
                                "source_event": "m1",
                                "relation": "supports",
                                "exact_quote": m1,
                                "char_start": 0,
                                "char_end": len(m1),
                            }
                        ],
                    }
                ],
                "forbidden_candidates": [
                    {"kind": "relation", "schema_name": "works_at", "polarity": "positive"}
                ],
                "expect_abstention": False,
                "forbidden_sources": [],
                "forbidden_segments": [],
            },
            "review": {
                "status": "draft",
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": ["Calibration probe."],
            },
        }
    )

    m1 = "Я не уверен, что Мария работает в Google."
    ps, pe = span(m1, "Мария")
    os, oe = span(m1, "Google")
    fixtures.append(
        {
            "schema_version": "1",
            "fixture_id": "calib_ru_uncertain_067",
            "title": "Uncertain employment probe",
            "tier": "smoke",
            "language": "ru",
            "criticality": "critical",
            "slice_tags": [
                "uncertainty_alternative",
                "direct_attribute_relation",
                "hard_negative",
            ],
            "reference_time": REF,
            "timezone": TZ,
            "users": [
                {
                    "user_alias": "u1",
                    "user_id": 2067,
                    "display_name": "Synthetic User",
                    "metadata": {"synthetic": True},
                }
            ],
            "events": [
                {
                    "event_id": "m1",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": m1,
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:00:00+05:00",
                    "metadata": {},
                }
            ],
            "expected": {
                "sources": [
                    {
                        "source_event": "m1",
                        "source_type": "chat_message",
                        "source_ref_alias": "m1",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m1"},
                        "normalization_job_status": "done",
                    }
                ],
                "segments": [
                    {
                        "source_event": "m1",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": m1,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m1"},
                    }
                ],
                "mentions": [
                    {
                        "mention_id": "maria",
                        "source_event": "m1",
                        "mention_type": "person",
                        "surface_text": "Мария",
                        "char_start": ps,
                        "char_end": pe,
                        "normalized_hint": "Мария",
                        "pointer": {"source_event": "m1", "char_start": ps, "char_end": pe},
                    },
                    {
                        "mention_id": "google",
                        "source_event": "m1",
                        "mention_type": "organization",
                        "surface_text": "Google",
                        "char_start": os,
                        "char_end": oe,
                        "normalized_hint": "Google",
                        "pointer": {"source_event": "m1", "char_start": os, "char_end": oe},
                    },
                ],
                "candidates": [
                    {
                        "candidate_ref": "c1",
                        "kind": "relation",
                        "schema_name": "works_at",
                        "schema_version": "1",
                        "arguments": [
                            {"role": "person", "mention_ref": "maria"},
                            {"role": "organization", "mention_ref": "google"},
                        ],
                        "attributes": {},
                        "polarity": "unknown",
                        "epistemic": {
                            "mode": "asserted",
                            "speaker_commitment": "uncertain",
                            "scope": "proposition",
                            "alternatives": [],
                            "needs_confirmation": True,
                        },
                        "temporal": None,
                        "status": "needs_confirmation",
                        "evidence": [
                            {
                                "source_event": "m1",
                                "relation": "supports",
                                "exact_quote": m1,
                                "char_start": 0,
                                "char_end": len(m1),
                            }
                        ],
                    }
                ],
                "forbidden_candidates": [
                    {"kind": "relation", "schema_name": "works_at", "polarity": "positive"},
                    {"kind": "relation", "schema_name": "works_at", "polarity": "negative"},
                ],
                "expect_abstention": False,
                "forbidden_sources": [],
                "forbidden_segments": [],
            },
            "review": {
                "status": "draft",
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": ["Calibration probe."],
            },
        }
    )

    m1 = "I might relocate to Berlin."
    ps, pe = span(m1, "Berlin")
    fixtures.append(
        {
            "schema_version": "1",
            "fixture_id": "calib_en_possible_068",
            "title": "Possible relocation probe",
            "tier": "smoke",
            "language": "en",
            "criticality": "critical",
            "slice_tags": ["uncertainty_alternative", "hard_negative", "multi_turn"],
            "reference_time": REF,
            "timezone": TZ,
            "users": [
                {
                    "user_alias": "u1",
                    "user_id": 2068,
                    "display_name": "Synthetic User",
                    "metadata": {"synthetic": True},
                }
            ],
            "events": [
                {
                    "event_id": "m1",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "assistant",
                    "content": "Planning a move?",
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:00:00+05:00",
                    "metadata": {},
                },
                {
                    "event_id": "m2",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": m1,
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:01:00+05:00",
                    "metadata": {},
                },
            ],
            "expected": {
                "sources": [
                    {
                        "source_event": "m1",
                        "source_type": "chat_message",
                        "source_ref_alias": "m1",
                        "authority_class": "assistant_generated",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m1"},
                        "normalization_job_status": "done",
                    },
                    {
                        "source_event": "m2",
                        "source_type": "chat_message",
                        "source_ref_alias": "m2",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m2"},
                        "normalization_job_status": "done",
                    },
                ],
                "segments": [
                    {
                        "source_event": "m1",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": "Planning a move?",
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m1"},
                    },
                    {
                        "source_event": "m2",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": m1,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m2"},
                    },
                ],
                "mentions": [
                    {
                        "mention_id": "berlin",
                        "source_event": "m2",
                        "mention_type": "place",
                        "surface_text": "Berlin",
                        "char_start": ps,
                        "char_end": pe,
                        "normalized_hint": "Berlin",
                        "pointer": {"source_event": "m2", "char_start": ps, "char_end": pe},
                    }
                ],
                "candidates": [
                    {
                        "candidate_ref": "c1",
                        "kind": "event",
                        "schema_name": "moves_to",
                        "schema_version": "1",
                        "arguments": [
                            {"role": "subject", "literal": "self"},
                            {"role": "place", "mention_ref": "berlin"},
                        ],
                        "attributes": {},
                        "polarity": "unknown",
                        "epistemic": {
                            "mode": "asserted",
                            "speaker_commitment": "possible",
                            "scope": "proposition",
                            "alternatives": [],
                            "needs_confirmation": True,
                        },
                        "temporal": None,
                        "status": "needs_confirmation",
                        "evidence": [
                            {
                                "source_event": "m2",
                                "relation": "supports",
                                "exact_quote": m1,
                                "char_start": 0,
                                "char_end": len(m1),
                            }
                        ],
                    }
                ],
                "forbidden_candidates": [
                    {"kind": "event", "schema_name": "moves_to", "polarity": "positive"},
                    {"kind": "event", "schema_name": "moves_to", "polarity": "negative"},
                ],
                "expect_abstention": False,
                "forbidden_sources": [],
                "forbidden_segments": [],
            },
            "review": {
                "status": "draft",
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": ["Calibration probe."],
            },
        }
    )

    m1 = "Коллега говорит, что Петр уволился."
    rs, re = span(m1, "Коллега")
    ps, pe = span(m1, "Петр")
    fixtures.append(
        {
            "schema_version": "1",
            "fixture_id": "calib_ru_hearsay_069",
            "title": "Hearsay job loss probe",
            "tier": "smoke",
            "language": "ru",
            "criticality": "critical",
            "slice_tags": [
                "wrong_speaker_hearsay",
                "uncertainty_alternative",
                "hard_negative",
                "multi_turn",
            ],
            "reference_time": REF,
            "timezone": TZ,
            "users": [
                {
                    "user_alias": "u1",
                    "user_id": 2069,
                    "display_name": "Synthetic User",
                    "metadata": {"synthetic": True},
                }
            ],
            "events": [
                {
                    "event_id": "m1",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "assistant",
                    "content": "Новости о Петре?",
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:00:00+05:00",
                    "metadata": {},
                },
                {
                    "event_id": "m2",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": m1,
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:01:00+05:00",
                    "metadata": {},
                },
            ],
            "expected": {
                "sources": [
                    {
                        "source_event": "m1",
                        "source_type": "chat_message",
                        "source_ref_alias": "m1",
                        "authority_class": "assistant_generated",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m1"},
                        "normalization_job_status": "done",
                    },
                    {
                        "source_event": "m2",
                        "source_type": "chat_message",
                        "source_ref_alias": "m2",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m2"},
                        "normalization_job_status": "done",
                    },
                ],
                "segments": [
                    {
                        "source_event": "m1",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": "Новости о Петре?",
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m1"},
                    },
                    {
                        "source_event": "m2",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": m1,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m2"},
                    },
                ],
                "mentions": [
                    {
                        "mention_id": "reporter",
                        "source_event": "m2",
                        "mention_type": "person",
                        "surface_text": "Коллега",
                        "char_start": rs,
                        "char_end": re,
                        "normalized_hint": "коллега",
                        "pointer": {"source_event": "m2", "char_start": rs, "char_end": re},
                    },
                    {
                        "mention_id": "petr",
                        "source_event": "m2",
                        "mention_type": "person",
                        "surface_text": "Петр",
                        "char_start": ps,
                        "char_end": pe,
                        "normalized_hint": "Петр",
                        "pointer": {"source_event": "m2", "char_start": ps, "char_end": pe},
                    },
                ],
                "candidates": [
                    {
                        "candidate_ref": "c1",
                        "kind": "event",
                        "schema_name": "left_job",
                        "schema_version": "1",
                        "arguments": [{"role": "person", "mention_ref": "petr"}],
                        "attributes": {},
                        "polarity": "unknown",
                        "epistemic": {
                            "mode": "reported",
                            "speaker_commitment": "possible",
                            "scope": "proposition",
                            "alternatives": [],
                            "needs_confirmation": True,
                            "speaker_ref": "reporter",
                        },
                        "temporal": None,
                        "status": "needs_confirmation",
                        "evidence": [
                            {
                                "source_event": "m2",
                                "relation": "supports",
                                "exact_quote": m1,
                                "char_start": 0,
                                "char_end": len(m1),
                            }
                        ],
                    }
                ],
                "forbidden_candidates": [
                    {"kind": "event", "schema_name": "left_job", "polarity": "positive"},
                    {"kind": "event", "schema_name": "left_job", "polarity": "negative"},
                ],
                "expect_abstention": False,
                "forbidden_sources": [],
                "forbidden_segments": [],
            },
            "review": {
                "status": "draft",
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": ["Calibration probe."],
            },
        }
    )

    m1, m2 = "I live in Berlin.", "Нет, теперь я живу в Wien."
    b1s, b1e = span(m1, "Berlin")
    w2s, w2e = span(m2, "Wien")
    fixtures.append(
        {
            "schema_version": "1",
            "fixture_id": "calib_mixed_residence_070",
            "title": "Cross-language residence correction probe",
            "tier": "smoke",
            "language": "mixed",
            "criticality": "critical",
            "slice_tags": [
                "correction_followup",
                "direct_attribute_relation",
                "multi_turn",
                "hard_negative",
            ],
            "reference_time": REF,
            "timezone": TZ,
            "users": [
                {
                    "user_alias": "u1",
                    "user_id": 2070,
                    "display_name": "Synthetic User",
                    "metadata": {"synthetic": True},
                }
            ],
            "events": [
                {
                    "event_id": "m1",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": m1,
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:00:00+05:00",
                    "metadata": {},
                },
                {
                    "event_id": "m2",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": m2,
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:01:00+05:00",
                    "metadata": {},
                },
            ],
            "expected": {
                "sources": [
                    {
                        "source_event": "m1",
                        "source_type": "chat_message",
                        "source_ref_alias": "m1",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m1"},
                        "normalization_job_status": "done",
                    },
                    {
                        "source_event": "m2",
                        "source_type": "chat_message",
                        "source_ref_alias": "m2",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m2"},
                        "normalization_job_status": "done",
                    },
                ],
                "segments": [
                    {
                        "source_event": "m1",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": m1,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m1"},
                    },
                    {
                        "source_event": "m2",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": m2,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m2"},
                    },
                ],
                "mentions": [
                    {
                        "mention_id": "berlin",
                        "source_event": "m1",
                        "mention_type": "place",
                        "surface_text": "Berlin",
                        "char_start": b1s,
                        "char_end": b1e,
                        "normalized_hint": "Berlin",
                        "pointer": {"source_event": "m1", "char_start": b1s, "char_end": b1e},
                    },
                    {
                        "mention_id": "wien",
                        "source_event": "m2",
                        "mention_type": "place",
                        "surface_text": "Wien",
                        "char_start": w2s,
                        "char_end": w2e,
                        "normalized_hint": "Wien",
                        "pointer": {"source_event": "m2", "char_start": w2s, "char_end": w2e},
                    },
                ],
                "candidates": [
                    {
                        "candidate_ref": "c1",
                        "kind": "correction",
                        "schema_name": "corrects_residence",
                        "schema_version": "1",
                        "arguments": [
                            {"role": "subject", "literal": "self"},
                            {"role": "old", "mention_ref": "berlin"},
                            {"role": "new", "mention_ref": "wien"},
                        ],
                        "attributes": {},
                        "polarity": "positive",
                        "epistemic": {
                            "mode": "asserted",
                            "speaker_commitment": "certain",
                            "scope": "proposition",
                            "alternatives": [],
                            "needs_confirmation": False,
                        },
                        "temporal": {
                            "original_text": "теперь",
                            "valid_from": "2026-07-10T09:01:00+05:00",
                            "valid_to": None,
                            "event_time": None,
                            "precision": "second",
                            "timezone": TZ,
                        },
                        "status": "proposed",
                        "evidence": [
                            {
                                "source_event": "m1",
                                "relation": "supports",
                                "exact_quote": m1,
                                "char_start": 0,
                                "char_end": len(m1),
                            },
                            {
                                "source_event": "m2",
                                "relation": "corrects",
                                "exact_quote": m2,
                                "char_start": 0,
                                "char_end": len(m2),
                            },
                        ],
                    }
                ],
                "forbidden_candidates": [
                    {
                        "kind": "relation",
                        "schema_name": "lives_in",
                        "arguments": [{"role": "place", "literal": "Berlin"}],
                    }
                ],
                "expect_abstention": False,
                "forbidden_sources": [],
                "forbidden_segments": [],
            },
            "review": {
                "status": "draft",
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": ["Calibration probe."],
            },
        }
    )

    m0, m1, m2 = (
        "Варианты: Hotel Aurora и Hotel Bristol.",
        "Бронируй его.",
        "Нет, второй.",
    )
    fixtures.append(
        {
            "schema_version": "1",
            "fixture_id": "calib_ru_selection_071",
            "title": "Referential selection correction probe",
            "tier": "smoke",
            "language": "ru",
            "criticality": "critical",
            "slice_tags": [
                "correction_followup",
                "preference_constraint",
                "multi_turn",
                "hard_negative",
            ],
            "reference_time": REF,
            "timezone": TZ,
            "users": [
                {
                    "user_alias": "u1",
                    "user_id": 2071,
                    "display_name": "Synthetic User",
                    "metadata": {"synthetic": True},
                }
            ],
            "events": [
                {
                    "event_id": "m0",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "assistant",
                    "content": m0,
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:00:00+05:00",
                    "metadata": {},
                },
                {
                    "event_id": "m1",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": m1,
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:01:00+05:00",
                    "metadata": {},
                },
                {
                    "event_id": "m2",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": m2,
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:02:00+05:00",
                    "metadata": {},
                },
            ],
            "expected": {
                "sources": [
                    {
                        "source_event": "m0",
                        "source_type": "chat_message",
                        "source_ref_alias": "m0",
                        "authority_class": "assistant_generated",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m0"},
                        "normalization_job_status": "done",
                    },
                    {
                        "source_event": "m1",
                        "source_type": "chat_message",
                        "source_ref_alias": "m1",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m1"},
                        "normalization_job_status": "done",
                    },
                    {
                        "source_event": "m2",
                        "source_type": "chat_message",
                        "source_ref_alias": "m2",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m2"},
                        "normalization_job_status": "done",
                    },
                ],
                "segments": [
                    {
                        "source_event": "m0",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": m0,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m0"},
                    },
                    {
                        "source_event": "m1",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": m1,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m1"},
                    },
                    {
                        "source_event": "m2",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": m2,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m2"},
                    },
                ],
                "mentions": [],
                "candidates": [
                    {
                        "candidate_ref": "c1",
                        "kind": "correction",
                        "schema_name": "corrects_selection",
                        "schema_version": "1",
                        "arguments": [
                            {"role": "subject", "literal": "self"},
                            {"role": "old", "literal": "Hotel Aurora"},
                            {"role": "new", "literal": "Hotel Bristol"},
                        ],
                        "attributes": {},
                        "polarity": "positive",
                        "epistemic": {
                            "mode": "asserted",
                            "speaker_commitment": "certain",
                            "scope": "proposition",
                            "alternatives": [],
                            "needs_confirmation": False,
                        },
                        "temporal": None,
                        "status": "proposed",
                        "evidence": [
                            {
                                "source_event": "m0",
                                "relation": "introduces_alternatives",
                                "exact_quote": m0,
                                "char_start": 0,
                                "char_end": len(m0),
                            },
                            {
                                "source_event": "m1",
                                "relation": "supports",
                                "exact_quote": m1,
                                "char_start": 0,
                                "char_end": len(m1),
                            },
                            {
                                "source_event": "m2",
                                "relation": "corrects",
                                "exact_quote": m2,
                                "char_start": 0,
                                "char_end": len(m2),
                            },
                        ],
                    }
                ],
                "forbidden_candidates": [
                    {
                        "kind": "preference",
                        "schema_name": "selected_option",
                        "arguments": [{"role": "value", "literal": "Hotel Aurora"}],
                    }
                ],
                "expect_abstention": False,
                "forbidden_sources": [],
                "forbidden_segments": [],
            },
            "review": {
                "status": "draft",
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": ["Calibration probe."],
            },
        }
    )

    payload = (
        '{"event":"Терапевт","date":"2026-07-12","time":"14:30","status":"confirmed"}'
    )
    fixtures.append(
        {
            "schema_version": "1",
            "fixture_id": "calib_ru_calendar_072",
            "title": "Calendar tool probe",
            "tier": "smoke",
            "language": "ru",
            "criticality": "critical",
            "slice_tags": [
                "exact_tool_result",
                "goal_task_deadline",
                "temporal_precision",
                "multi_turn",
            ],
            "reference_time": REF,
            "timezone": TZ,
            "users": [
                {
                    "user_alias": "u1",
                    "user_id": 2072,
                    "display_name": "Synthetic User",
                    "metadata": {"synthetic": True},
                }
            ],
            "events": [
                {
                    "event_id": "m1",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": "Покажи запись к терапевту.",
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:00:00+05:00",
                    "metadata": {},
                },
                {
                    "event_id": "t1",
                    "kind": "tool_result",
                    "user_alias": "u1",
                    "tool_name": "google.calendar.events.get",
                    "payload_kind": "result",
                    "payload_json": payload,
                    "ok": True,
                    "cached": False,
                    "occurred_at": "2026-07-10T09:01:00+05:00",
                },
            ],
            "expected": {
                "sources": [
                    {
                        "source_event": "m1",
                        "source_type": "chat_message",
                        "source_ref_alias": "m1",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m1"},
                        "normalization_job_status": "done",
                    },
                    {
                        "source_event": "t1",
                        "source_type": "tool_result",
                        "source_ref_alias": "t1",
                        "authority_class": "tool_api_result",
                        "content_hash_rule": "sha256_raw_payload",
                        "source_version_count": 1,
                        "pointer": {"source_event": "t1"},
                        "normalization_job_status": "done",
                    },
                ],
                "segments": [
                    {
                        "source_event": "m1",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": "Покажи запись к терапевту.",
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m1"},
                    },
                    {
                        "source_event": "t1",
                        "segment_type": "tool_payload",
                        "ordinal": 0,
                        "text": payload,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "t1"},
                    },
                ],
                "mentions": [],
                "candidates": [
                    {
                        "candidate_ref": "c1",
                        "kind": "event",
                        "schema_name": "calendar_event",
                        "schema_version": "1",
                        "arguments": [
                            {"role": "subject", "literal": "self"},
                            {"role": "title", "literal": "Терапевт"},
                        ],
                        "attributes": {},
                        "polarity": "positive",
                        "epistemic": {
                            "mode": "retrieved",
                            "speaker_commitment": "certain",
                            "scope": "proposition",
                            "alternatives": [],
                            "needs_confirmation": False,
                        },
                        "temporal": {
                            "original_text": "2026-07-12 14:30",
                            "valid_from": None,
                            "valid_to": None,
                            "event_time": "2026-07-12T14:30:00+05:00",
                            "precision": "minute",
                            "timezone": TZ,
                        },
                        "status": "proposed",
                        "evidence": [
                            {
                                "source_event": "t1",
                                "relation": "supports",
                                "exact_quote": payload,
                                "char_start": 0,
                                "char_end": len(payload),
                            }
                        ],
                    }
                ],
                "forbidden_candidates": [],
                "expect_abstention": False,
                "forbidden_sources": [{"source_type": "tool_summary"}],
                "forbidden_segments": [{"segment_type": "tool_summary"}],
            },
            "review": {
                "status": "draft",
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": ["Calibration probe."],
            },
        }
    )

    payload = '{"task_id":"task_88","title":"File taxes","status":"needsAction"}'
    fixtures.append(
        {
            "schema_version": "1",
            "fixture_id": "calib_en_task_073",
            "title": "Open task tool probe",
            "tier": "smoke",
            "language": "en",
            "criticality": "critical",
            "slice_tags": ["exact_tool_result", "goal_task_deadline", "multi_turn"],
            "reference_time": REF,
            "timezone": TZ,
            "users": [
                {
                    "user_alias": "u1",
                    "user_id": 2073,
                    "display_name": "Synthetic User",
                    "metadata": {"synthetic": True},
                }
            ],
            "events": [
                {
                    "event_id": "m1",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": "Check my tax task.",
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:00:00+05:00",
                    "metadata": {},
                },
                {
                    "event_id": "t1",
                    "kind": "tool_result",
                    "user_alias": "u1",
                    "tool_name": "google.tasks.get",
                    "payload_kind": "result",
                    "payload_json": payload,
                    "ok": True,
                    "cached": False,
                    "occurred_at": "2026-07-10T09:01:00+05:00",
                },
            ],
            "expected": {
                "sources": [
                    {
                        "source_event": "m1",
                        "source_type": "chat_message",
                        "source_ref_alias": "m1",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m1"},
                        "normalization_job_status": "done",
                    },
                    {
                        "source_event": "t1",
                        "source_type": "tool_result",
                        "source_ref_alias": "t1",
                        "authority_class": "tool_api_result",
                        "content_hash_rule": "sha256_raw_payload",
                        "source_version_count": 1,
                        "pointer": {"source_event": "t1"},
                        "normalization_job_status": "done",
                    },
                ],
                "segments": [
                    {
                        "source_event": "m1",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": "Check my tax task.",
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m1"},
                    },
                    {
                        "source_event": "t1",
                        "segment_type": "tool_payload",
                        "ordinal": 0,
                        "text": payload,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "t1"},
                    },
                ],
                "mentions": [],
                "candidates": [
                    {
                        "candidate_ref": "c1",
                        "kind": "task",
                        "schema_name": "open_task",
                        "schema_version": "1",
                        "arguments": [
                            {"role": "subject", "literal": "self"},
                            {"role": "title", "literal": "File taxes"},
                        ],
                        "attributes": {},
                        "polarity": "positive",
                        "epistemic": {
                            "mode": "retrieved",
                            "speaker_commitment": "certain",
                            "scope": "proposition",
                            "alternatives": [],
                            "needs_confirmation": False,
                        },
                        "temporal": None,
                        "status": "proposed",
                        "evidence": [
                            {
                                "source_event": "t1",
                                "relation": "supports",
                                "exact_quote": payload,
                                "char_start": 0,
                                "char_end": len(payload),
                            }
                        ],
                    }
                ],
                "forbidden_candidates": [],
                "expect_abstention": False,
                "forbidden_sources": [{"source_type": "tool_summary"}],
                "forbidden_segments": [{"segment_type": "tool_summary"}],
            },
            "review": {
                "status": "draft",
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": ["Calibration probe."],
            },
        }
    )

    m1 = "Мария работает в Google."
    ps, pe = span(m1, "Мария")
    os, oe = span(m1, "Google")
    fixtures.append(
        {
            "schema_version": "1",
            "fixture_id": "calib_ru_relation_074",
            "title": "Catchup employment relation probe",
            "tier": "smoke",
            "language": "ru",
            "criticality": "critical",
            "slice_tags": ["direct_attribute_relation"],
            "reference_time": REF,
            "timezone": TZ,
            "users": [
                {
                    "user_alias": "u1",
                    "user_id": 2074,
                    "display_name": "Synthetic User",
                    "metadata": {"synthetic": True},
                }
            ],
            "events": [
                {
                    "event_id": "m1",
                    "kind": "chat_message",
                    "user_alias": "u1",
                    "role": "user",
                    "content": m1,
                    "content_type": "text",
                    "occurred_at": "2026-07-10T09:00:00+05:00",
                    "metadata": {"eval_delivery": "catchup"},
                }
            ],
            "expected": {
                "sources": [
                    {
                        "source_event": "m1",
                        "source_type": "chat_message",
                        "source_ref_alias": "m1",
                        "authority_class": "user_direct_statement",
                        "content_hash_rule": "chat_content_hash",
                        "source_version_count": 1,
                        "pointer": {"source_event": "m1"},
                        "normalization_job_status": "done",
                    }
                ],
                "segments": [
                    {
                        "source_event": "m1",
                        "segment_type": "chat_text",
                        "ordinal": 0,
                        "text": m1,
                        "normalizer_version": "1",
                        "pointer": {"source_event": "m1"},
                    }
                ],
                "mentions": [
                    {
                        "mention_id": "maria",
                        "source_event": "m1",
                        "mention_type": "person",
                        "surface_text": "Мария",
                        "char_start": ps,
                        "char_end": pe,
                        "normalized_hint": "Мария",
                        "pointer": {"source_event": "m1", "char_start": ps, "char_end": pe},
                    },
                    {
                        "mention_id": "google",
                        "source_event": "m1",
                        "mention_type": "organization",
                        "surface_text": "Google",
                        "char_start": os,
                        "char_end": oe,
                        "normalized_hint": "Google",
                        "pointer": {"source_event": "m1", "char_start": os, "char_end": oe},
                    },
                ],
                "candidates": [
                    {
                        "candidate_ref": "c1",
                        "kind": "relation",
                        "schema_name": "works_at",
                        "schema_version": "1",
                        "arguments": [
                            {"role": "person", "mention_ref": "maria"},
                            {"role": "organization", "mention_ref": "google"},
                        ],
                        "attributes": {},
                        "polarity": "positive",
                        "epistemic": {
                            "mode": "asserted",
                            "speaker_commitment": "certain",
                            "scope": "proposition",
                            "alternatives": [],
                            "needs_confirmation": False,
                        },
                        "temporal": None,
                        "status": "proposed",
                        "evidence": [
                            {
                                "source_event": "m1",
                                "relation": "supports",
                                "exact_quote": m1,
                                "char_start": 0,
                                "char_end": len(m1),
                            }
                        ],
                    }
                ],
                "forbidden_candidates": [],
                "expect_abstention": False,
                "forbidden_sources": [],
                "forbidden_segments": [],
            },
            "review": {
                "status": "draft",
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": ["Calibration probe."],
            },
        }
    )

    for item in fixtures:
        write_fixture(item)

    manifest = {
        "schema_version": "1",
        "pack_id": "text_v1_calibration",
        "pack_version": "1",
        "fixtures": [f"cases/{item['fixture_id']}.json" for item in fixtures],
        "coverage": {
            "fixture_count": 10,
            "smoke_count": 10,
            "language_minimums": {"ru": 5, "en": 3, "mixed": 1},
            "slice_minimums": {
                "correction_followup": 3,
                "direct_attribute_relation": 4,
                "negation": 1,
                "uncertainty_alternative": 3,
                "wrong_speaker_hearsay": 1,
                "exact_tool_result": 2,
                "goal_task_deadline": 2,
                "temporal_precision": 1,
                "preference_constraint": 1,
                "hard_negative": 6,
                "multi_turn": 6,
            },
            "smoke_slice_minimums": {
                "correction_followup": 1,
                "direct_attribute_relation": 1,
                "negation": 1,
                "uncertainty_alternative": 1,
                "wrong_speaker_hearsay": 1,
                "exact_tool_result": 1,
                "hard_negative": 1,
                "multi_turn": 1,
            },
            "multi_turn_minimum": 6,
            "hard_negative_minimum": 6,
            "require_reviewed": False,
        },
    }
    manifest_path = PACK_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    from memory.eval.loader import load_pack

    pack = load_pack(PACK_DIR)
    manifest["pack_hash"] = pack.pack_hash
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(fixtures)} fixtures to {PACK_DIR}")
    print(f"pack_hash={pack.pack_hash}")


if __name__ == "__main__":
    main()
