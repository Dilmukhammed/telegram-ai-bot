from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any


FAILURE_CODES = (
    "fixture_invalid",
    "source_missing",
    "source_unexpected",
    "segment_missing",
    "segment_unexpected",
    "pointer_owner_mismatch",
    "pointer_dereference_failed",
    "pointer_text_mismatch",
    "mention_missing",
    "mention_unexpected",
    "candidate_missing",
    "candidate_unexpected",
    "forbidden_candidate",
    "missing_evidence",
    "exact_quote_mismatch",
    "lost_negation",
    "uncertainty_flattened",
    "wrong_speaker",
    "temporal_mismatch",
    "expected_abstention",
    "verification_missing",
    "verification_unexpected",
    "forbidden_advancement",
    "verification_scope_error",
    "subject_timeout",
    "subject_error",
)
FAILURE_CODE_SET = frozenset(FAILURE_CODES)

_CANDIDATE_FIELDS = (
    "kind",
    "schema_name",
    "schema_version",
    "polarity",
    "arguments",
    "attributes",
    "epistemic",
    "temporal",
    "status",
    "evidence",
)
_MISSING = object()


@dataclass(frozen=True)
class MatchPair:
    expected_index: int
    actual_index: int


@dataclass(frozen=True)
class MatchResult:
    pairs: tuple[MatchPair, ...]
    missing_expected: tuple[int, ...]
    unexpected_actual: tuple[int, ...]
    expected_count: int
    actual_count: int

    @property
    def true_positives(self) -> int:
        return len(self.pairs)

    @property
    def false_positives(self) -> int:
        return len(self.unexpected_actual)

    @property
    def false_negatives(self) -> int:
        return len(self.missing_expected)

    @property
    def perfect(self) -> bool:
        return not self.missing_expected and not self.unexpected_actual


@dataclass(frozen=True)
class ForbiddenMatch:
    pattern_index: int
    actual_index: int


def to_plain(value: Any) -> Any:
    """Convert mappings and dataclasses to a deterministic JSON-compatible tree."""
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((to_plain(item) for item in value), key=canonical_json)
    if isinstance(value, Enum):
        return to_plain(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        to_plain(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def strict_equal(expected: Any, actual: Any) -> bool:
    """Compare values strictly after normalizing mapping/dataclass representation."""
    try:
        return canonical_json(expected) == canonical_json(actual)
    except (TypeError, ValueError):
        return False


def _as_mapping(value: Any, *, label: str) -> dict[str, Any]:
    plain = to_plain(value)
    if not isinstance(plain, dict):
        raise TypeError(f"{label} must be a mapping or dataclass")
    return plain


def _sort_unordered(values: Any) -> Any:
    if not isinstance(values, list):
        return values
    return sorted(values, key=canonical_json)


def mention_signature(mention: Any) -> str:
    item = _as_mapping(mention, label="mention")
    source = item.get("source_event", item.get("source_alias", _MISSING))
    signature = {
        "source_event": source,
        "mention_type": item.get("mention_type", _MISSING),
        "char_start": item.get("char_start", _MISSING),
        "char_end": item.get("char_end", _MISSING),
        "surface_text": item.get("surface_text", _MISSING),
    }
    if _MISSING in signature.values():
        missing = [key for key, value in signature.items() if value is _MISSING]
        raise ValueError(f"mention is missing signature fields: {', '.join(missing)}")
    return canonical_json(signature)


def _candidate_projection(candidate: Any) -> dict[str, Any]:
    item = _as_mapping(candidate, label="candidate")
    projection: dict[str, Any] = {}
    for name in _CANDIDATE_FIELDS:
        projection[name] = item[name] if name in item else {"__missing_field__": name}
    if projection["schema_name"] == "likes":
        projection["schema_name"] = "prefers"
    projection["arguments"] = _sort_unordered(to_plain(projection["arguments"]))
    projection["evidence"] = _sort_unordered(to_plain(projection["evidence"]))
    return projection


def candidate_signature(candidate: Any) -> str:
    """Return the semantic signature, excluding run/provider/identity metadata."""
    return canonical_json(_candidate_projection(candidate))


def candidate_matches(expected: Any, actual: Any) -> bool:
    expected_item = _as_mapping(expected, label="expected candidate")
    expected_projection = _candidate_projection(expected_item)
    actual_projection = _candidate_projection(actual)
    allow_extra_attributes = expected_item.get("allow_extra_attributes") is True
    if allow_extra_attributes:
        expected_attributes = expected_projection["attributes"]
        actual_attributes = actual_projection["attributes"]
        expected_projection["attributes"] = {}
        actual_projection["attributes"] = {}
        return strict_equal(expected_projection, actual_projection) and partial_pattern_matches(
            expected_attributes,
            actual_attributes,
        )
    return strict_equal(expected_projection, actual_projection)


def _keyed_semantics(value: Any, keys: frozenset[str], path: str = "") -> tuple[Any, ...]:
    plain = to_plain(value)
    found: list[tuple[str, Any]] = []
    if isinstance(plain, dict):
        for key, item in sorted(plain.items()):
            item_path = f"{path}.{key}" if path else key
            if key in keys:
                found.append((item_path, item))
            found.extend(_keyed_semantics(item, keys, item_path))
    elif isinstance(plain, list):
        for index, item in enumerate(plain):
            found.extend(_keyed_semantics(item, keys, f"{path}[{index}]"))
    return tuple(found)


def candidate_difference_codes(expected: Any, actual: Any) -> tuple[str, ...]:
    """Classify important semantic candidate regressions with stable codes."""
    expected_item = _as_mapping(expected, label="expected candidate")
    actual_item = _as_mapping(actual, label="actual candidate")
    codes: set[str] = set()

    if expected_item.get("polarity") == "negative" and actual_item.get("polarity") != "negative":
        codes.add("lost_negation")

    expected_epistemic = expected_item.get("epistemic")
    actual_epistemic = actual_item.get("epistemic")
    epistemic_plain = to_plain(expected_epistemic)
    uncertainty_expected = isinstance(epistemic_plain, dict) and (
        epistemic_plain.get("speaker_commitment")
        in {"probable", "possible", "uncertain", "unknown", "hedged"}
        or epistemic_plain.get("needs_confirmation") is True
        or bool(epistemic_plain.get("alternatives"))
    )
    if uncertainty_expected and not strict_equal(expected_epistemic, actual_epistemic):
        codes.add("uncertainty_flattened")

    speaker_keys = frozenset(
        {"speaker", "speaker_ref", "speaker_alias", "source_user_alias", "authority_class"}
    )
    expected_speaker = _keyed_semantics(expected_item, speaker_keys)
    if expected_speaker and not strict_equal(
        expected_speaker,
        _keyed_semantics(actual_item, speaker_keys),
    ):
        codes.add("wrong_speaker")

    if not strict_equal(expected_item.get("temporal"), actual_item.get("temporal")):
        codes.add("temporal_mismatch")

    expected_evidence = to_plain(expected_item.get("evidence"))
    actual_evidence = to_plain(actual_item.get("evidence"))
    if expected_evidence and not actual_evidence:
        codes.add("missing_evidence")
    elif expected_evidence:
        expected_quotes = _keyed_semantics(expected_evidence, frozenset({"exact_quote"}))
        actual_quotes = _keyed_semantics(actual_evidence, frozenset({"exact_quote"}))
        if expected_quotes and not strict_equal(expected_quotes, actual_quotes):
            codes.add("exact_quote_mismatch")

    return tuple(code for code in FAILURE_CODES if code in codes)


def _stable_key(value: Any, index: int) -> tuple[str, int]:
    try:
        return canonical_json(value), index
    except (TypeError, ValueError):
        return repr(value), index


def match_one_to_one(
    expected: Sequence[Any],
    actual: Sequence[Any],
    predicate: Callable[[Any, Any], bool] = strict_equal,
) -> MatchResult:
    """Compute a deterministic maximum-cardinality bipartite matching."""
    expected_items = tuple(expected)
    actual_items = tuple(actual)
    expected_order = sorted(
        range(len(expected_items)),
        key=lambda index: _stable_key(expected_items[index], index),
    )
    actual_order = sorted(
        range(len(actual_items)),
        key=lambda index: _stable_key(actual_items[index], index),
    )
    adjacency = {
        expected_index: tuple(
            actual_index
            for actual_index in actual_order
            if predicate(expected_items[expected_index], actual_items[actual_index])
        )
        for expected_index in expected_order
    }
    actual_owner: dict[int, int] = {}

    def assign(expected_index: int, seen_actual: set[int]) -> bool:
        for actual_index in adjacency[expected_index]:
            if actual_index in seen_actual:
                continue
            seen_actual.add(actual_index)
            owner = actual_owner.get(actual_index)
            if owner is None or assign(owner, seen_actual):
                actual_owner[actual_index] = expected_index
                return True
        return False

    for expected_index in expected_order:
        assign(expected_index, set())

    pairs = tuple(
        sorted(
            (
                MatchPair(expected_index=expected_index, actual_index=actual_index)
                for actual_index, expected_index in actual_owner.items()
            ),
            key=lambda pair: (pair.expected_index, pair.actual_index),
        )
    )
    matched_expected = {pair.expected_index for pair in pairs}
    matched_actual = {pair.actual_index for pair in pairs}
    return MatchResult(
        pairs=pairs,
        missing_expected=tuple(
            index for index in range(len(expected_items)) if index not in matched_expected
        ),
        unexpected_actual=tuple(
            index for index in range(len(actual_items)) if index not in matched_actual
        ),
        expected_count=len(expected_items),
        actual_count=len(actual_items),
    )


def match_strict_items(expected: Sequence[Any], actual: Sequence[Any]) -> MatchResult:
    return match_one_to_one(expected, actual, strict_equal)


def match_mentions(expected: Sequence[Any], actual: Sequence[Any]) -> MatchResult:
    def same_mention(left: Any, right: Any) -> bool:
        try:
            return mention_signature(left) == mention_signature(right)
        except (TypeError, ValueError):
            return False

    return match_one_to_one(expected, actual, same_mention)


def match_candidates(expected: Sequence[Any], actual: Sequence[Any]) -> MatchResult:
    return match_one_to_one(expected, actual, candidate_matches)


def partial_pattern_matches(pattern: Any, value: Any) -> bool:
    """Match a recursive partial pattern; collection members match one-to-one."""
    pattern = to_plain(pattern)
    value = to_plain(value)
    if isinstance(pattern, dict):
        if not isinstance(value, dict):
            return False
        return all(
            key in value and partial_pattern_matches(pattern_item, value[key])
            for key, pattern_item in pattern.items()
        )
    if isinstance(pattern, list):
        if not isinstance(value, list):
            return False
        return match_one_to_one(pattern, value, partial_pattern_matches).false_negatives == 0
    return strict_equal(pattern, value)


def find_forbidden_matches(
    patterns: Sequence[Any],
    actual: Sequence[Any],
) -> tuple[ForbiddenMatch, ...]:
    matches = [
        ForbiddenMatch(pattern_index=pattern_index, actual_index=actual_index)
        for pattern_index, pattern in enumerate(patterns)
        for actual_index, candidate in enumerate(actual)
        if partial_pattern_matches(pattern, candidate)
    ]
    return tuple(sorted(matches, key=lambda match: (match.pattern_index, match.actual_index)))


def validate_failure_code(code: str) -> str:
    if code not in FAILURE_CODE_SET:
        raise ValueError(f"unknown evaluation failure code: {code!r}")
    return code


def failure_codes_for_match(
    result: MatchResult,
    *,
    missing_code: str,
    unexpected_code: str,
) -> tuple[str, ...]:
    validate_failure_code(missing_code)
    validate_failure_code(unexpected_code)
    return (
        *((missing_code,) * result.false_negatives),
        *((unexpected_code,) * result.false_positives),
    )
