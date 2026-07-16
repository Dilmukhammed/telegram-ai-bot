from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from memory.resolution.er_types import CandidateSet, EntityCandidate
from memory.resolution.normalization import display_label, lookup_key
from memory.resolution.normalization_lang import detect_script_language

_STABLE_ID_KEYS = ("stable_id", "external_id", "email", "phone", "account_id")
_EXACT_ALIAS_TYPES = frozenset({"organization", "place", "project"})
_TIER_RANK = {
    "stable_id": 0,
    "exact_alias": 1,
    "fuzzy": 2,
    "cross_language": 3,
}


def extract_stable_id(mention: Mapping[str, Any]) -> str | None:
    """First stable identifier from mention attributes/metadata, casefolded."""
    for container in _mention_containers(mention):
        for key in _STABLE_ID_KEYS:
            if key not in container:
                continue
            value = container.get(key)
            if value is None:
                continue
            text = display_label(value).casefold()
            if text:
                return text
    return None


def _mention_containers(mention: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    containers: list[Mapping[str, Any]] = []
    for key in ("attributes", "metadata"):
        raw = mention.get(key)
        if isinstance(raw, Mapping):
            containers.append(raw)
        elif isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, Mapping):
                containers.append(parsed)
    pointer_raw = mention.get("pointer_json")
    if isinstance(pointer_raw, str) and pointer_raw.strip():
        try:
            parsed = json.loads(pointer_raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, Mapping):
            metadata = parsed.get("metadata")
            if isinstance(metadata, Mapping):
                containers.append(metadata)
    return containers


def trigram_jaccard(a: str, b: str) -> float:
    left = _trigrams(lookup_key(a))
    right = _trigrams(lookup_key(b))
    if not left and not right:
        return 1.0 if lookup_key(a) == lookup_key(b) else 0.0
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    union = len(left | right)
    return intersection / union if union else 0.0


def _trigrams(text: str) -> set[str]:
    padded = f"  {text} "
    if len(padded) < 3:
        return {padded} if padded.strip() else set()
    return {padded[index : index + 3] for index in range(len(padded) - 2)}


def generate_candidates(
    conn: sqlite3.Connection,
    user_id: int,
    mention: Mapping[str, Any],
    *,
    fuzzy_enabled: bool,
    fuzzy_min_trigram: float,
    cross_language_enabled: bool,
    max_candidates: int,
) -> CandidateSet:
    mention_id = str(mention["mention_id"])
    mention_type = str(mention.get("mention_type") or "unknown")
    surface = display_label(mention.get("surface_text") or "")
    normalized = lookup_key(surface)
    stable_id = extract_stable_id(mention)

    by_entity: dict[str, EntityCandidate] = {}

    if stable_id is not None:
        identity_key = f"stable:{stable_id}"
        for row in conn.execute(
            """
            SELECT entity_id, entity_type, identity_key, canonical_label, status
            FROM memory_entities
            WHERE user_id = ?
              AND entity_type = ?
              AND identity_key = ?
              AND status IN ('active', 'provisional')
            ORDER BY created_at, entity_id
            """,
            (user_id, mention_type, identity_key),
        ).fetchall():
            _upsert_candidate(
                by_entity,
                _candidate_from_row(
                    row,
                    tier="stable_id",
                    blocking_reason="stable_id_match",
                    stable_id=stable_id,
                ),
            )

    if mention_type == "person":
        return CandidateSet(
            mention_id=mention_id,
            mention_type=mention_type,
            candidates=_cap_candidates(by_entity.values(), max_candidates),
        )

    if mention_type not in _EXACT_ALIAS_TYPES:
        return CandidateSet(
            mention_id=mention_id,
            mention_type=mention_type,
            candidates=_cap_candidates(by_entity.values(), max_candidates),
        )

    if normalized:
        for row in conn.execute(
            """
            SELECT e.entity_id, e.entity_type, e.identity_key, e.canonical_label, e.status
            FROM memory_entity_aliases a
            JOIN memory_entities e ON e.entity_id = a.entity_id
            WHERE a.user_id = ?
              AND a.normalized_alias = ?
              AND a.status = 'active'
              AND e.status IN ('active', 'provisional')
              AND e.entity_type = ?
            ORDER BY a.created_at, a.alias_id
            """,
            (user_id, normalized, mention_type),
        ).fetchall():
            _upsert_candidate(
                by_entity,
                _candidate_from_row(
                    row,
                    tier="exact_alias",
                    blocking_reason="exact_alias_match",
                ),
            )

    if fuzzy_enabled and normalized:
        for row in conn.execute(
            """
            SELECT e.entity_id, e.entity_type, e.identity_key, e.canonical_label, e.status,
                   a.normalized_alias
            FROM memory_entity_aliases a
            JOIN memory_entities e ON e.entity_id = a.entity_id
            WHERE a.user_id = ?
              AND a.status = 'active'
              AND e.status IN ('active', 'provisional')
              AND e.entity_type = ?
              AND a.normalized_alias != ?
            ORDER BY a.created_at, a.alias_id
            """,
            (user_id, mention_type, normalized),
        ).fetchall():
            score = trigram_jaccard(normalized, str(row["normalized_alias"]))
            if score < fuzzy_min_trigram:
                continue
            _upsert_candidate(
                by_entity,
                _candidate_from_row(
                    row,
                    tier="fuzzy",
                    blocking_reason=f"fuzzy_trigram:{score:.3f}",
                ),
            )

    if cross_language_enabled and normalized:
        language = detect_script_language(surface)
        for equivalent_alias in _equivalent_aliases(
            conn,
            user_id=user_id,
            entity_type=mention_type,
            normalized_alias=normalized,
            language=language,
        ):
            for row in conn.execute(
                """
                SELECT e.entity_id, e.entity_type, e.identity_key, e.canonical_label, e.status
                FROM memory_entity_aliases a
                JOIN memory_entities e ON e.entity_id = a.entity_id
                WHERE a.user_id = ?
                  AND a.normalized_alias = ?
                  AND a.status = 'active'
                  AND e.status IN ('active', 'provisional')
                  AND e.entity_type = ?
                ORDER BY a.created_at, a.alias_id
                """,
                (user_id, equivalent_alias, mention_type),
            ).fetchall():
                _upsert_candidate(
                    by_entity,
                    _candidate_from_row(
                        row,
                        tier="cross_language",
                        blocking_reason="cross_language_equivalence",
                    ),
                )

    return CandidateSet(
        mention_id=mention_id,
        mention_type=mention_type,
        candidates=_cap_candidates(by_entity.values(), max_candidates),
    )


def _candidate_from_row(
    row: sqlite3.Row | Mapping[str, Any],
    *,
    tier: str,
    blocking_reason: str,
    stable_id: str | None = None,
) -> EntityCandidate:
    return EntityCandidate(
        entity_id=str(row["entity_id"]),
        entity_type=str(row["entity_type"]),
        identity_key=str(row["identity_key"]),
        canonical_label=str(row["canonical_label"]),
        status=str(row["status"]),
        tier=tier,
        blocking_reason=blocking_reason,
        stable_id=stable_id,
    )


def _upsert_candidate(
    by_entity: dict[str, EntityCandidate],
    candidate: EntityCandidate,
) -> None:
    existing = by_entity.get(candidate.entity_id)
    if existing is None or _TIER_RANK[candidate.tier] < _TIER_RANK[existing.tier]:
        by_entity[candidate.entity_id] = candidate


def _cap_candidates(
    candidates: Any,
    max_candidates: int,
) -> tuple[EntityCandidate, ...]:
    ordered = sorted(
        candidates,
        key=lambda item: (_TIER_RANK.get(item.tier, 99), item.entity_id),
    )
    if max_candidates < 1:
        return ()
    return tuple(ordered[:max_candidates])


def _equivalent_aliases(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    entity_type: str,
    normalized_alias: str,
    language: str | None,
) -> set[str]:
    try:
        rows = conn.execute(
            """
            SELECT normalized_alias_a, language_a, normalized_alias_b, language_b
            FROM memory_entity_alias_equivalences
            WHERE user_id = ?
              AND entity_type = ?
              AND status = 'active'
              AND (
                    normalized_alias_a = ? OR normalized_alias_b = ?
              )
            """,
            (user_id, entity_type, normalized_alias, normalized_alias),
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    equivalents: set[str] = set()
    for row in rows:
        alias_a = str(row["normalized_alias_a"])
        alias_b = str(row["normalized_alias_b"])
        if alias_a == normalized_alias:
            if language is None or row["language_b"] in (None, language):
                equivalents.add(alias_b)
        elif alias_b == normalized_alias:
            if language is None or row["language_a"] in (None, language):
                equivalents.add(alias_a)
    equivalents.discard(normalized_alias)
    return equivalents
