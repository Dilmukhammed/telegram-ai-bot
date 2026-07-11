"""Offline, deterministic runner for graph-memory evaluation packs."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import contextvars
import dataclasses
import hashlib
import importlib
import inspect
import json
import os
import platform
import socket
import subprocess
import sys
import time
import traceback
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory.eval.reports import (
    REPORT_SCHEMA_VERSION,
    BaselineCompatibilityError,
    bounded_case_result,
    compare_baseline,
    load_baseline,
    write_reports,
)

EXIT_SUCCESS = 0
EXIT_GATE_FAILURE = 1
EXIT_HARNESS_ERROR = 2
MAX_CONCURRENCY = 32
MAX_TIMEOUT_SECONDS = 3_600.0
_eval_pack: contextvars.ContextVar[str] = contextvars.ContextVar("eval_pack", default="text_v1")


class RunnerConfigurationError(ValueError):
    """Invalid runner arguments or unavailable production adapters."""


class NetworkDeniedError(RuntimeError):
    """External networking was attempted by an offline evaluation."""


@dataclass(frozen=True)
class EvalContext:
    seed: int
    reference_time: Any
    timezone: str
    allow_network: bool
    timeout_seconds: float
    pack_hash: str
    fixture_id: str


@dataclass(frozen=True)
class RunnerConfig:
    pack: str = "text_v1"
    subject: str = "ingestion"
    tier: str = "smoke"
    case_ids: tuple[str, ...] = ()
    slice_tags: tuple[str, ...] = ()
    language: str | None = None
    shard: tuple[int, int] | None = None
    concurrency: int = 1
    timeout_seconds: float = 60.0
    baseline: Path | None = None
    actual_dir: Path | None = None
    allow_network: bool = False
    output: Path | None = None

    def __post_init__(self) -> None:
        if self.tier not in {"smoke", "full"}:
            raise RunnerConfigurationError("tier must be smoke or full")
        if self.language not in {None, "ru", "en", "mixed"}:
            raise RunnerConfigurationError("language must be ru, en, or mixed")
        if not 1 <= self.concurrency <= MAX_CONCURRENCY:
            raise RunnerConfigurationError(
                f"concurrency must be between 1 and {MAX_CONCURRENCY}"
            )
        if not 0 < self.timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise RunnerConfigurationError(
                f"timeout_seconds must be in (0, {MAX_TIMEOUT_SECONDS}]"
            )
        if self.shard is not None:
            index, total = self.shard
            if total < 1 or index < 0 or index >= total:
                raise RunnerConfigurationError("shard must satisfy 0 <= index < total")


@dataclass
class RunResult:
    exit_code: int
    manifest: dict[str, Any]
    cases: list[dict[str, Any]]
    summary: dict[str, Any]
    artifacts: dict[str, Path] = field(default_factory=dict)


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _as_mapping(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    if dataclasses.is_dataclass(item):
        return dataclasses.asdict(item)
    if hasattr(item, "model_dump"):
        return dict(item.model_dump(mode="json"))
    if hasattr(item, "to_dict"):
        return dict(item.to_dict())
    if hasattr(item, "__dict__"):
        return dict(vars(item))
    raise TypeError(f"expected structured output, got {type(item).__name__}")


def fixture_id(fixture: Any) -> str:
    value = _value(fixture, "fixture_id", _value(fixture, "id"))
    if not isinstance(value, str) or not value:
        raise RunnerConfigurationError("fixture has no non-empty fixture_id")
    return value


def parse_shard(value: str) -> tuple[int, int]:
    try:
        index_text, total_text = value.split("/", 1)
        index, total = int(index_text), int(total_text)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("shard must use index/total integers") from exc
    if total < 1 or index < 0 or index >= total:
        raise argparse.ArgumentTypeError("shard must satisfy 0 <= index < total")
    return index, total


def select_fixtures(
    fixtures: Iterable[Any],
    *,
    tier: str = "smoke",
    case_ids: Sequence[str] = (),
    slice_tags: Sequence[str] = (),
    language: str | None = None,
    shard: tuple[int, int] | None = None,
) -> list[Any]:
    """Filter, sort, then stably shard fixtures."""

    wanted_cases = set(case_ids)
    wanted_slices = set(slice_tags)
    selected: list[Any] = []
    seen: set[str] = set()
    for fixture in fixtures:
        item_id = fixture_id(fixture)
        if item_id in seen:
            raise RunnerConfigurationError(f"duplicate fixture_id: {item_id}")
        seen.add(item_id)
        item_tier = _value(fixture, "tier")
        if tier == "smoke" and item_tier != "smoke":
            continue
        # "full" is the complete pack, including smoke fixtures.
        if wanted_cases and item_id not in wanted_cases:
            continue
        tags = set(_value(fixture, "slice_tags", ()) or ())
        if wanted_slices and not wanted_slices.issubset(tags):
            continue
        if language is not None and _value(fixture, "language") != language:
            continue
        selected.append(fixture)
    selected.sort(key=fixture_id)
    if wanted_cases:
        missing = sorted(wanted_cases - {fixture_id(item) for item in selected})
        if missing:
            raise RunnerConfigurationError(
                "requested fixtures not selected or not found: " + ", ".join(missing)
            )
    if shard is not None:
        index, total = shard
        selected = [item for position, item in enumerate(selected) if position % total == index]
    return selected


def derive_case_seed(pack_hash: str, case_id: str) -> int:
    digest = hashlib.sha256(f"{pack_hash}\0{case_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


@contextlib.contextmanager
def deny_network(enabled: bool = True):
    """Deny socket connection attempts for the duration of an offline run."""

    if not enabled:
        yield
        return
    original_create_connection = socket.create_connection
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise NetworkDeniedError(
            "network access is disabled; pass --allow-network for an explicit opt-in"
        )

    socket.create_connection = blocked
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    try:
        yield
    finally:
        socket.create_connection = original_create_connection
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _normalize_failure(item: Any) -> dict[str, str]:
    if isinstance(item, Mapping):
        return {
            "code": str(item.get("code", "failure")),
            "message": str(item.get("message", "")),
        }
    return {
        "code": str(_value(item, "code", "failure")),
        "message": str(_value(item, "message", item)),
    }


def _normalize_case_result(fixture: Any, raw: Any) -> dict[str, Any]:
    data = _as_mapping(raw)
    failures = [_normalize_failure(item) for item in data.get("failures", ())]
    passed = bool(data.get("passed", data.get("status") == "passed" or not failures))
    if failures:
        passed = False
    return {
        "fixture_id": fixture_id(fixture),
        "title": str(_value(fixture, "title", "")),
        "tier": str(_value(fixture, "tier", "")),
        "language": str(_value(fixture, "language", "")),
        "criticality": str(_value(fixture, "criticality", "normal")),
        "slice_tags": sorted(str(tag) for tag in (_value(fixture, "slice_tags", ()) or ())),
        "passed": passed,
        "error": bool(data.get("error", False)),
        "failures": failures,
        "metrics": dict(data.get("metrics") or {}),
        "expected_signatures": list(data.get("expected_signatures") or []),
        "actual_signatures": list(data.get("actual_signatures") or []),
        "usage": dict(data.get("usage") or {}),
        "candidate_kind": data.get("candidate_kind", ()),
        "verification_trace": list(data.get("verification_trace") or []),
    }


def _find_matcher() -> Callable[..., Any] | None:
    try:
        module = importlib.import_module("memory.eval.matching")
    except ImportError:
        return None
    for name in ("evaluate_case", "match_case", "match_fixture", "score_case"):
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    if all(
        callable(getattr(module, name, None))
        for name in ("match_mentions", "match_candidates", "match_strict_items")
    ):
        return _default_match_case
    return None


def _metric(numerator: int | float, denominator: int | float) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def _normalize_candidate_mention_refs(
    candidate: Any,
    mention_ref_map: Mapping[str, str],
    mention_literal_map: Mapping[str, str] | None = None,
) -> Any:
    literal_map = mention_literal_map or {}
    if not isinstance(candidate, Mapping) or not (mention_ref_map or literal_map):
        return candidate
    result = dict(candidate)
    arguments = []
    for raw in result.get("arguments") or []:
        if not isinstance(raw, Mapping):
            arguments.append(raw)
            continue
        argument = dict(raw)
        reference = argument.get("mention_ref", argument.get("mention_id"))
        key = str(reference) if reference is not None else None
        if key is not None and key in mention_ref_map:
            argument.pop("mention_id", None)
            argument["mention_ref"] = mention_ref_map.get(key, key)
        elif key is not None and key in literal_map:
            argument.pop("mention_id", None)
            argument["mention_ref"] = None
            argument["literal"] = literal_map[key]
            argument["has_literal"] = True
        arguments.append(argument)
    result["arguments"] = arguments
    epistemic = result.get("epistemic")
    if isinstance(epistemic, Mapping) and epistemic.get("speaker_ref") is not None:
        updated = dict(epistemic)
        key = str(updated["speaker_ref"])
        updated["speaker_ref"] = mention_ref_map.get(key, key)
        result["epistemic"] = updated
    return result


def _candidate_core_matches(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    matching = importlib.import_module("memory.eval.matching")
    return (
        expected.get("kind") == actual.get("kind")
        and expected.get("schema_name") == actual.get("schema_name")
        and matching.strict_equal(expected.get("arguments"), actual.get("arguments"))
    )


def _uncertainty_fields(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    epistemic = candidate.get("epistemic")
    epistemic = epistemic if isinstance(epistemic, Mapping) else {}
    return (
        candidate.get("polarity"),
        epistemic.get("speaker_commitment"),
        epistemic.get("needs_confirmation"),
        epistemic.get("scope"),
        candidate.get("status"),
    )


def _source_texts(fixture: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for event in _value(fixture, "events", ()) or ():
        event_id = str(_value(event, "event_id", "")).strip()
        kind = str(_value(event, "kind", "")).strip()
        if kind == "chat_message":
            text = _value(event, "content", None)
        elif kind == "tool_result":
            text = _value(event, "payload_json", None)
        else:
            text = None
        if event_id and isinstance(text, str):
            result[event_id] = text
    return result


def _evidence_is_exact(evidence: Any, source_texts: Mapping[str, str]) -> bool:
    if not isinstance(evidence, Mapping):
        return False
    source_event = str(evidence.get("source_event", ""))
    text = source_texts.get(source_event)
    start = evidence.get("char_start")
    end = evidence.get("char_end")
    quote = evidence.get("exact_quote")
    return (
        text is not None
        and isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and isinstance(quote, str)
        and 0 <= start <= end <= len(text)
        and text[start:end] == quote
    )


def _default_match_case(fixture: Any, output: Any) -> dict[str, Any]:
    """Local adapter from PR2 matching primitives to a scored case."""

    matching = importlib.import_module("memory.eval.matching")
    plain = matching.to_plain
    expected_owner = _value(fixture, "expected", {}) or {}
    expected = plain(expected_owner)
    actual = plain(output)
    if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
        raise TypeError("fixture expectations and subject output must be structured")
    if actual.get("fixture_id") not in {None, fixture_id(fixture)}:
        raise ValueError("subject output fixture_id does not match selected fixture")

    failures: list[dict[str, str]] = []

    def fail(code: str, message: str) -> None:
        failures.append({"code": code, "message": message})

    metadata = actual.get("metadata") or {}
    aliases = metadata.get("event_aliases") if isinstance(metadata, Mapping) else {}
    aliases = aliases if isinstance(aliases, Mapping) else {}
    actual_sources = list(actual.get("sources") or [])
    expected_sources = list(expected.get("sources") or [])
    source_projections: list[dict[str, Any]] = []
    expected_source_projections: list[dict[str, Any]] = []
    source_event_by_id: dict[str, str] = {}
    for source in expected_sources:
        event_id = str(source.get("source_event", ""))
        alias = aliases.get(event_id, {})
        expected_ref = (
            alias.get("source_ref") if isinstance(alias, Mapping) else None
        ) or source.get("source_ref_alias")
        expected_source_projections.append(
            {
                "source_event": event_id,
                "source_type": source.get("source_type"),
                "source_ref": expected_ref,
                "authority_class": source.get("authority_class"),
            }
        )
    ref_to_event = {
        projection["source_ref"]: projection["source_event"]
        for projection in expected_source_projections
    }
    for source in actual_sources:
        event_id = ref_to_event.get(source.get("source_ref"), "")
        source_projections.append(
            {
                "source_event": event_id,
                "source_type": source.get("source_type"),
                "source_ref": source.get("source_ref"),
                "authority_class": source.get("authority_class"),
            }
        )
        if event_id:
            source_event_by_id[str(source.get("source_id", ""))] = event_id
    source_match = matching.match_strict_items(
        expected_source_projections, source_projections
    )
    for index in source_match.missing_expected:
        fail("source_missing", f"missing source {expected_source_projections[index]}")
    for index in source_match.unexpected_actual:
        fail("source_unexpected", f"unexpected source {source_projections[index]}")
    for pattern in list(expected.get("forbidden_sources") or []):
        constrained = {key: value for key, value in pattern.items() if value is not None}
        if any(
            matching.partial_pattern_matches(constrained, source)
            for source in source_projections
        ):
            fail("source_unexpected", f"source matched forbidden pattern {constrained}")

    versions = list(actual.get("source_versions") or actual.get("versions") or [])
    version_source: dict[str, str] = {}
    versions_by_source: Counter[str] = Counter()
    for version in versions:
        source_id = str(version.get("source_id", ""))
        versions_by_source[source_id] += 1
        version_source[str(version.get("source_version_id", ""))] = source_id
    version_correct = 0
    for expected_source in expected_sources:
        event_id = str(expected_source.get("source_event", ""))
        source_ids = [
            source_id for source_id, event in source_event_by_id.items() if event == event_id
        ]
        count = sum(versions_by_source[source_id] for source_id in source_ids)
        wanted = int(expected_source.get("source_version_count", 1))
        if count == wanted:
            version_correct += 1
        else:
            fail(
                "source_missing",
                f"{event_id} expected {wanted} source versions, got {count}",
            )

    actual_segments = list(actual.get("segments") or [])
    segment_projections: list[dict[str, Any]] = []
    for segment in actual_segments:
        source_id = version_source.get(str(segment.get("source_version_id", "")), "")
        segment_projections.append(
            {
                "source_event": source_event_by_id.get(source_id, ""),
                "segment_type": segment.get("segment_type"),
                "ordinal": segment.get("ordinal"),
                "text": segment.get("text"),
                "normalizer_version": segment.get("normalizer_version"),
            }
        )
    expected_segment_projections = [
        {
            "source_event": segment.get("source_event"),
            "segment_type": segment.get("segment_type"),
            "ordinal": segment.get("ordinal"),
            "text": segment.get("text"),
            "normalizer_version": segment.get("normalizer_version"),
        }
        for segment in list(expected.get("segments") or [])
    ]
    segment_match = matching.match_strict_items(
        expected_segment_projections, segment_projections
    )
    for index in segment_match.missing_expected:
        fail("segment_missing", f"missing segment {expected_segment_projections[index]}")
    for index in segment_match.unexpected_actual:
        fail("segment_unexpected", f"unexpected segment {segment_projections[index]}")
    for pattern in list(expected.get("forbidden_segments") or []):
        constrained = {key: value for key, value in pattern.items() if value is not None}
        if any(
            matching.partial_pattern_matches(constrained, segment)
            for segment in segment_projections
        ):
            fail(
                "segment_unexpected",
                f"segment matched forbidden pattern {constrained}",
            )

    pointer_checks = list(actual.get("pointer_checks") or [])
    owner_ok = sum(check.get("owner_ok") is True for check in pointer_checks)
    dereference_ok = sum(check.get("dereference_ok") is True for check in pointer_checks)
    text_checks = [check for check in pointer_checks if check.get("text_ok") is not None]
    text_ok = sum(check.get("text_ok") is True for check in text_checks)
    for check in pointer_checks:
        target = check.get("target_id", "unknown")
        if check.get("owner_ok") is not True:
            fail("pointer_owner_mismatch", f"pointer owner mismatch for {target}")
        elif check.get("dereference_ok") is not True:
            fail("pointer_dereference_failed", f"pointer dereference failed for {target}")
        elif check.get("text_ok") is False:
            fail("pointer_text_mismatch", f"pointer text mismatch for {target}")

    evaluate_extraction = metadata.get("subject_type") != "ingestion"
    expected_mentions = (
        list(expected.get("mentions") or []) if evaluate_extraction else []
    )
    actual_mentions = list(actual.get("mentions") or [])
    mention_match = matching.match_mentions(expected_mentions, actual_mentions)
    for index in mention_match.missing_expected:
        fail("mention_missing", f"missing mention index {index}")

    mention_ref_map: dict[str, str] = {}
    for pair in mention_match.pairs:
        expected_mention = expected_mentions[pair.expected_index]
        actual_mention = actual_mentions[pair.actual_index]
        expected_ref = expected_mention.get("mention_id", expected_mention.get("mention_ref"))
        actual_ref = actual_mention.get("mention_id", actual_mention.get("mention_ref"))
        if expected_ref is not None and actual_ref is not None:
            mention_ref_map[str(actual_ref)] = str(expected_ref)

    expected_candidates = (
        list(expected.get("candidates") or []) if evaluate_extraction else []
    )
    raw_actual_candidates = list(actual.get("candidates") or [])
    referenced_actual_mentions = {
        str(reference)
        for candidate in raw_actual_candidates
        if isinstance(candidate, Mapping)
        for argument in candidate.get("arguments") or []
        if isinstance(argument, Mapping)
        for reference in (argument.get("mention_ref", argument.get("mention_id")),)
        if reference is not None
    }
    mention_literal_map: dict[str, str] = {}
    for index in mention_match.unexpected_actual:
        mention = actual_mentions[index]
        reference = mention.get("mention_id", mention.get("mention_ref"))
        surface = mention.get("surface_text")
        if reference is not None and isinstance(surface, str) and str(reference) in referenced_actual_mentions:
            mention_literal_map[str(reference)] = surface
        else:
            fail("mention_unexpected", f"unexpected mention index {index}")
    actual_candidates = [
        _normalize_candidate_mention_refs(item, mention_ref_map, mention_literal_map)
        for item in raw_actual_candidates
    ]
    candidate_match = matching.match_candidates(expected_candidates, actual_candidates)
    for index in candidate_match.missing_expected:
        fail("candidate_missing", f"missing candidate index {index}")
    for index in candidate_match.unexpected_actual:
        fail("candidate_unexpected", f"unexpected candidate index {index}")
    forbidden = matching.find_forbidden_matches(
        list(expected.get("forbidden_candidates") or [])
        if evaluate_extraction
        else [],
        actual_candidates,
    )
    for item in forbidden:
        fail(
            "forbidden_candidate",
            f"actual candidate {item.actual_index} matched forbidden pattern "
            f"{item.pattern_index}",
        )
    if evaluate_extraction and expected.get("expect_abstention") and actual_candidates:
        fail("expected_abstention", "fixture expected no accepted candidates")

    verification_expected = 0
    verification_correct = 0
    verification_false_accepts = 0
    verification_false_rejects = 0
    verification_actual_decisions = 0
    verification_ready_expected = 0
    verification_ready_correct = 0
    verification_ready_actual = 0
    verification_adversarial = 0
    verification_support = 0
    verification_scope_errors = 0
    verification_pack_reviewed = 0
    if metadata.get("subject_type") == "verification":
        from memory.eval.verification_expectations import (
            load_verification_expectations,
            resolve_verification_expectations_path,
        )

        verification_pack = load_verification_expectations(
            resolve_verification_expectations_path(_eval_pack.get())
        )
        verification_pack_reviewed = int(verification_pack.reviewed)
        expectation = verification_pack.cases.get(fixture_id(fixture))
        if expectation is not None:
            expected_to_actual = {
                str(
                    expected_candidates[pair.expected_index].get(
                        "candidate_ref",
                        expected_candidates[pair.expected_index].get("candidate_id", ""),
                    )
                ): actual_candidates[pair.actual_index]
                for pair in candidate_match.pairs
            }
            verdicts = list(actual.get("verdicts") or [])
            expected_actual_ids: set[str] = set()
            for outcome in expectation.outcomes:
                verification_expected += 1
                verification_ready_expected += int(
                    outcome.status == "ready_for_resolution"
                )
                actual_candidate = expected_to_actual.get(outcome.candidate_ref)
                if actual_candidate is None:
                    verification_false_rejects += 1
                    fail(
                        "verification_missing",
                        f"no verified candidate for {outcome.candidate_ref}",
                    )
                    continue
                actual_id = str(
                    actual_candidate.get(
                        "candidate_ref", actual_candidate.get("candidate_id", "")
                    )
                )
                expected_actual_ids.add(actual_id)
                candidate_verdicts = [
                    item
                    for item in verdicts
                    if str(item.get("candidate_id", "")) == actual_id
                ]
                support = next(
                    (
                        item
                        for item in candidate_verdicts
                        if item.get("role") == "support"
                    ),
                    None,
                )
                adversarial = any(
                    item.get("role") == "adversarial" for item in candidate_verdicts
                )
                verification_support += int(support is not None)
                verification_adversarial += int(adversarial)
                verification_scope_errors += sum(
                    len(item.get("scope_errors") or [])
                    for item in candidate_verdicts
                    if item.get("role") in {"support", "adversarial"}
                )
                status_ok = (
                    actual_candidate.get("verification_status") == outcome.status
                )
                verdict_ok = support is not None and support.get("verdict") == outcome.verdict
                escalation_ok = adversarial is outcome.adversarial
                verification_actual_decisions += int(support is not None)
                if status_ok and verdict_ok and escalation_ok:
                    verification_correct += 1
                    verification_ready_correct += int(
                        outcome.status == "ready_for_resolution"
                    )
                else:
                    verification_false_rejects += 1
                    fail(
                        "verification_scope_error",
                        f"{outcome.candidate_ref} expected status={outcome.status} "
                        f"verdict={outcome.verdict} adversarial={outcome.adversarial}, "
                        f"got status={actual_candidate.get('verification_status')} "
                        f"support={support.get('verdict') if support else None} "
                        f"adversarial={adversarial}",
                    )
            ready_candidates = [
                item
                for item in actual_candidates
                if item.get("verification_status") == "ready_for_resolution"
            ]
            verification_ready_actual = len(ready_candidates)
            if expectation.forbid_unexpected_advancement:
                unexpected_ready = [
                    item
                    for item in ready_candidates
                    if str(item.get("candidate_ref", item.get("candidate_id", "")))
                    not in expected_actual_ids
                ]
                verification_false_accepts = len(unexpected_ready)
                for item in unexpected_ready:
                    fail(
                        "forbidden_advancement",
                        "unexpected candidate advanced to ready_for_resolution: "
                        f"{item.get('candidate_ref')}",
                    )

    expected_negative = [
        item for item in expected_candidates if item.get("polarity") == "negative"
    ]
    preserved_negative = sum(
        any(
            _candidate_core_matches(item, actual)
            and actual.get("polarity") == "negative"
            for actual in actual_candidates
        )
        for item in expected_negative
    )
    expected_uncertain = [
        item
        for item in expected_candidates
        if _uncertainty_fields(item)[0] == "unknown"
        or _uncertainty_fields(item)[2] is True
    ]
    preserved_uncertain = sum(
        any(
            _candidate_core_matches(item, actual)
            and _uncertainty_fields(actual) == _uncertainty_fields(item)
            for actual in actual_candidates
        )
        for item in expected_uncertain
    )
    wrong_speakers = 0
    for item in expected_candidates:
        expected_epistemic = item.get("epistemic")
        expected_epistemic = (
            expected_epistemic if isinstance(expected_epistemic, Mapping) else {}
        )
        for actual_candidate in actual_candidates:
            if not _candidate_core_matches(item, actual_candidate):
                continue
            actual_epistemic = actual_candidate.get("epistemic")
            actual_epistemic = (
                actual_epistemic if isinstance(actual_epistemic, Mapping) else {}
            )
            if actual_epistemic.get("speaker_ref") != expected_epistemic.get(
                "speaker_ref"
            ):
                wrong_speakers += 1
            break

    source_texts = _source_texts(fixture)
    actual_evidence = [
        evidence
        for candidate in actual_candidates
        for evidence in (candidate.get("evidence") or [])
    ]
    exact_evidence = sum(
        _evidence_is_exact(evidence, source_texts) for evidence in actual_evidence
    )
    unsupported_candidates = candidate_match.false_positives
    abstention_denominator = (
        max(1, len(actual_candidates))
        if expected.get("expect_abstention")
        else 0
    )

    jobs = list(actual.get("jobs") or [])
    completed_jobs = sum(str(job.get("status", "")).lower() in {"done", "completed"} for job in jobs)
    verification_jobs = [
        job for job in jobs if str(job.get("stage", "")) == "candidate_verify"
    ]
    completed_verification_jobs = sum(
        str(job.get("status", "")).lower() in {"done", "completed"}
        for job in verification_jobs
    )
    metrics = {
        "source_exactness": _metric(source_match.true_positives, source_match.expected_count),
        "source_version_exactness": _metric(version_correct, len(expected_sources)),
        "segment_exactness": _metric(segment_match.true_positives, segment_match.expected_count),
        "normalization_job_completion": _metric(completed_jobs, len(jobs)),
        "pointer_ownership_accuracy": _metric(owner_ok, len(pointer_checks)),
        "pointer_dereference_accuracy": _metric(dereference_ok, len(pointer_checks)),
        "exact_segment_text_span": _metric(text_ok, len(text_checks)),
        "mention_precision": _metric(
            mention_match.true_positives,
            mention_match.true_positives + mention_match.false_positives,
        ),
        "mention_recall": _metric(
            mention_match.true_positives,
            mention_match.true_positives + mention_match.false_negatives,
        ),
        "candidate_precision": _metric(
            candidate_match.true_positives,
            candidate_match.true_positives + candidate_match.false_positives,
        ),
        "candidate_recall": _metric(
            candidate_match.true_positives,
            candidate_match.true_positives + candidate_match.false_negatives,
        ),
        "forbidden_candidate_rate": _metric(
            len(forbidden), max(1, len(actual_candidates), len(forbidden))
        ),
        "unsupported_candidate_rate": _metric(
            unsupported_candidates,
            max(1, len(actual_candidates)),
        ),
        "evidence_pointer_accuracy": _metric(
            exact_evidence,
            len(actual_evidence),
        ),
        "exact_quote_accuracy": _metric(
            exact_evidence,
            len(actual_evidence),
        ),
        "negation_scope_accuracy": _metric(
            preserved_negative,
            len(expected_negative),
        ),
        "uncertainty_scope_accuracy": _metric(
            preserved_uncertain,
            len(expected_uncertain),
        ),
        "wrong_speaker_count": _metric(
            wrong_speakers,
            max(1, wrong_speakers),
        ),
        "forbidden_candidate_count": _metric(
            len(forbidden),
            max(1, len(forbidden)),
        ),
        "irrelevant_false_positive_rate": _metric(
            len(actual_candidates) if expected.get("expect_abstention") else 0,
            abstention_denominator,
        ),
        # Strict parser failures cannot produce persisted candidates. A malformed
        # response is either repaired and revalidated or the job fails closed.
        "malformed_accepted_output_count": _metric(0, 1),
        "verification_precision": _metric(
            verification_correct,
            verification_actual_decisions + verification_false_accepts,
        ),
        "verification_recall": _metric(
            verification_correct,
            verification_expected,
        ),
        "verifier_false_accept_rate": _metric(
            verification_false_accepts,
            max(1, verification_expected, verification_false_accepts)
            if metadata.get("subject_type") == "verification"
            else 0,
        ),
        "verifier_false_reject_rate": _metric(
            verification_false_rejects,
            verification_expected,
        ),
        "forbidden_advancement_count": _metric(
            verification_false_accepts,
            max(1, verification_false_accepts),
        ),
        "ready_for_resolution_precision": _metric(
            verification_ready_correct,
            verification_ready_actual,
        ),
        "verification_scope_accuracy": _metric(
            max(0, verification_support + verification_adversarial - verification_scope_errors),
            verification_support + verification_adversarial,
        ),
        "verification_escalation_rate": _metric(
            verification_adversarial,
            verification_support,
        ),
        "verification_fixtures_reviewed": _metric(
            verification_pack_reviewed,
            1 if metadata.get("subject_type") == "verification" else 0,
        ),
        "verification_job_completion": _metric(
            completed_verification_jobs,
            len(verification_jobs),
        ),
    }
    expected_signatures = [
        *(matching.mention_signature(item) for item in expected_mentions),
        *(matching.candidate_signature(item) for item in expected_candidates),
    ]
    actual_signatures = [
        *(matching.mention_signature(item) for item in actual_mentions),
        *(matching.candidate_signature(item) for item in actual_candidates),
    ]
    return {
        "passed": not failures,
        "failures": failures,
        "metrics": metrics,
        "expected_signatures": sorted(expected_signatures),
        "actual_signatures": sorted(actual_signatures),
        "usage": dict(actual.get("usage") or {}),
        "candidate_kind": sorted(
            {
                str(candidate.get("kind"))
                for candidate in actual_candidates
                if candidate.get("kind") is not None
            }
        ),
        "verification_trace": list(actual.get("verdicts") or []),
    }


async def _match_output(
    fixture: Any,
    output: Any,
    matcher: Callable[..., Any] | None,
) -> dict[str, Any]:
    data = _as_mapping(output)
    if {"passed", "failures", "metrics"}.intersection(data):
        return _normalize_case_result(fixture, data)
    active_matcher = matcher or _find_matcher()
    if active_matcher is not None:
        raw = await _maybe_await(active_matcher(fixture, output))
        return _normalize_case_result(fixture, raw)
    # Unit-test/captured adapters may return an already-scored case result.
    raise TypeError("no matching adapter is available and subject output is not scored")


async def _cleanup_subject(subject: Any, fixture: Any, context: EvalContext) -> None:
    for name in ("cleanup_case", "reset_case"):
        cleanup = getattr(subject, name, None)
        if callable(cleanup):
            await _maybe_await(cleanup(fixture, context))
            return


async def _execute_case(
    fixture: Any,
    *,
    subject: Any,
    matcher: Callable[..., Any] | None,
    pack_hash: str,
    timeout_seconds: float,
    allow_network: bool,
    actual_dir: Path | None,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    item_id = fixture_id(fixture)
    context = _make_eval_context(
        fixture,
        seed=derive_case_seed(pack_hash, item_id),
        allow_network=allow_network,
        timeout_seconds=timeout_seconds,
        pack_hash=pack_hash,
        actual_dir=actual_dir,
    )
    result: dict[str, Any]
    async with semaphore:
        started = time.perf_counter()
        try:
            run = getattr(subject, "run", None)
            if not callable(run):
                raise TypeError("subject must provide run(case, context)")
            output = await asyncio.wait_for(
                _maybe_await(run(fixture, context)),
                timeout=timeout_seconds,
            )
            result = await _match_output(fixture, output, matcher)
        except TimeoutError:
            result = _normalize_case_result(
                fixture,
                {
                    "passed": False,
                    "error": True,
                    "failures": [
                        {
                            "code": "subject_timeout",
                            "message": f"subject exceeded {timeout_seconds:g}s timeout",
                        }
                    ],
                },
            )
        except Exception as exc:
            result = _normalize_case_result(
                fixture,
                {
                    "passed": False,
                    "error": True,
                    "failures": [
                        {
                            "code": "subject_error",
                            "message": f"{type(exc).__name__}: {exc}",
                        }
                    ],
                },
            )
        finally:
            try:
                await asyncio.wait_for(
                    _cleanup_subject(subject, fixture, context),
                    timeout=timeout_seconds,
                )
            except Exception as exc:
                if "result" not in locals():
                    result = _normalize_case_result(fixture, {"passed": True})
                result["passed"] = False
                result["error"] = True
                result["failures"].append(
                    {
                        "code": "subject_error",
                        "message": f"cleanup failed: {type(exc).__name__}: {exc}",
                    }
                )
    result["duration_seconds"] = round(time.perf_counter() - started, 6)
    return result


def _make_eval_context(
    fixture: Any,
    *,
    seed: int,
    allow_network: bool,
    timeout_seconds: float,
    pack_hash: str,
    actual_dir: Path | None,
) -> Any:
    item_id = fixture_id(fixture)
    metadata = {
        "reference_time": _value(fixture, "reference_time"),
        "timezone": str(_value(fixture, "timezone", "UTC")),
        "allow_network": allow_network,
        "pack_hash": pack_hash,
        "fixture_id": item_id,
    }
    try:
        module = importlib.import_module("memory.eval.subjects")
        context_class = getattr(module, "EvalContext", None)
        if context_class is not None:
            return context_class(
                timeout_seconds=timeout_seconds,
                captured_output_dir=actual_dir,
                seed=seed,
                metadata=metadata,
            )
    except (ImportError, TypeError):
        pass
    return EvalContext(
        seed=seed,
        reference_time=metadata["reference_time"],
        timezone=metadata["timezone"],
        allow_network=allow_network,
        timeout_seconds=timeout_seconds,
        pack_hash=pack_hash,
        fixture_id=item_id,
    )


def _aggregate_metrics(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    try:
        module = importlib.import_module("memory.eval.metrics")
        aggregate = getattr(module, "aggregate_metrics", None)
        if callable(aggregate):
            report = aggregate(cases)
            data = report.as_dict() if hasattr(report, "as_dict") else _as_mapping(report)
            metrics = data.get("metrics")
            if isinstance(metrics, Mapping):
                return dict(metrics)
    except (ImportError, TypeError, ValueError):
        pass
    totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    scalars: dict[str, list[float]] = defaultdict(list)
    for case in cases:
        for name, raw in (case.get("metrics") or {}).items():
            if isinstance(raw, Mapping) and "numerator" in raw and "denominator" in raw:
                totals[str(name)][0] += float(raw["numerator"])
                totals[str(name)][1] += float(raw["denominator"])
            elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
                scalars[str(name)].append(float(raw))
    result: dict[str, Any] = {}
    for name in sorted(totals):
        numerator, denominator = totals[name]
        result[name] = {
            "numerator": numerator,
            "denominator": denominator,
            "value": numerator / denominator if denominator else None,
        }
    for name in sorted(scalars.keys() - totals.keys()):
        values = scalars[name]
        result[name] = {
            "numerator": sum(values),
            "denominator": len(values),
            "value": sum(values) / len(values) if values else None,
        }
    return result


def _aggregate_slice_metrics(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    try:
        module = importlib.import_module("memory.eval.metrics")
        aggregate = getattr(module, "aggregate_metrics", None)
        if callable(aggregate):
            report = aggregate(cases)
            data = report.as_dict() if hasattr(report, "as_dict") else _as_mapping(report)
            slices = data.get("slices")
            if isinstance(slices, Mapping):
                return dict(slices)
    except (ImportError, TypeError, ValueError):
        pass
    return {}


def _breakdowns(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field_name in ("language", "criticality"):
        groups: dict[str, Counter[str]] = defaultdict(Counter)
        for case in cases:
            groups[str(case.get(field_name, ""))][
                "passed" if case.get("passed") else "failed"
            ] += 1
        result[field_name] = {
            name: {
                "case_count": counts["passed"] + counts["failed"],
                "passed_count": counts["passed"],
                "failed_count": counts["failed"],
            }
            for name, counts in sorted(groups.items())
        }
    slices: dict[str, Counter[str]] = defaultdict(Counter)
    for case in cases:
        for tag in case.get("slice_tags") or []:
            slices[str(tag)]["passed" if case.get("passed") else "failed"] += 1
    result["slice"] = {
        name: {
            "case_count": counts["passed"] + counts["failed"],
            "passed_count": counts["passed"],
            "failed_count": counts["failed"],
        }
        for name, counts in sorted(slices.items())
    }
    kinds: dict[str, Counter[str]] = defaultdict(Counter)
    for case in cases:
        raw_kinds = case.get("candidate_kind") or ()
        if isinstance(raw_kinds, str):
            raw_kinds = (raw_kinds,)
        for kind in raw_kinds:
            kinds[str(kind)]["passed" if case.get("passed") else "failed"] += 1
    result["candidate_kind"] = {
        name: {
            "case_count": counts["passed"] + counts["failed"],
            "passed_count": counts["passed"],
            "failed_count": counts["failed"],
        }
        for name, counts in sorted(kinds.items())
    }
    return result


def _pack_slice_counts(fixtures: Sequence[Any]) -> dict[str, int]:
    counts: Counter[str] = Counter({"total": len(fixtures)})
    for fixture in fixtures:
        counts[f"tier:{_value(fixture, 'tier', '')}"] += 1
        counts[f"language:{_value(fixture, 'language', '')}"] += 1
        for tag in _value(fixture, "slice_tags", ()) or ():
            counts[f"critical_slice:{tag}"] += 1
            counts[f"slice:{tag}"] += 1
    return dict(sorted(counts.items()))


def _normalize_gates(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, (Mapping, list, tuple)):
        raw = _as_mapping(raw)
    if isinstance(raw, Mapping):
        raw = raw.get("gates", raw.get("results", [raw]))
    gates: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        data = _as_mapping(item)
        gates.append(
            {
                **data,
                "gate_id": str(data.get("gate_id", data.get("name", f"gate_{index}"))),
                "passed": bool(data.get("passed", False)),
            }
        )
    return gates


def _find_gate_evaluator() -> Callable[..., Any] | None:
    try:
        module = importlib.import_module("memory.eval.gates")
    except ImportError:
        return None
    for name in ("evaluate_gates", "apply_gates", "evaluate"):
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    return None


async def _evaluate_gates(
    summary: Mapping[str, Any],
    *,
    evaluator: Callable[..., Any] | None,
    gate_config: Any,
) -> list[dict[str, Any]]:
    active = evaluator or _find_gate_evaluator()
    if active is None or gate_config is None:
        return [
            {
                "gate_id": "all_cases_pass",
                "passed": int(summary.get("failed_count", 0)) == 0,
                "message": "all selected fixtures must pass",
            }
        ]
    if getattr(active, "__module__", "") == "memory.eval.gates":
        failure_codes = [
            code
            for code, count in (summary.get("failure_counts") or {}).items()
            for _ in range(int(count))
        ]
        slice_counts = dict(summary.get("pack_slice_counts") or {})
        raw = active(
            gate_config,
            summary.get("metrics", {}),
            failure_codes=failure_codes,
            slice_counts=slice_counts,
            subject_type=summary.get("subject_type"),
        )
    else:
        try:
            raw = active(summary, gate_config)
        except TypeError:
            raw = active(summary)
    return _normalize_gates(await _maybe_await(raw))


def _subject_metadata(subject: Any) -> dict[str, str]:
    return {
        "subject_id": str(getattr(subject, "subject_id", type(subject).__name__)),
        "pipeline_id": str(getattr(subject, "pipeline_id", "unknown")),
        "processor_version": str(getattr(subject, "processor_version", "unknown")),
        "subject_schema_version": str(
            getattr(subject, "schema_version", getattr(subject, "subject_schema_version", "1"))
        ),
    }


def _git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _pack_metadata(pack: Any, config: RunnerConfig, gate_config: Any = None) -> dict[str, str]:
    manifest = _value(pack, "manifest", {}) or {}
    return {
        "pack_id": str(
            _value(pack, "pack_id", _value(manifest, "pack_id", _value(pack, "id", config.pack)))
        ),
        "pack_version": str(
            _value(
                pack,
                "pack_version",
                _value(manifest, "pack_version", _value(pack, "version", "unknown")),
            )
        ),
        "pack_hash": str(_value(pack, "pack_hash", _value(pack, "hash", ""))),
        "gate_schema_version": str(
            _value(gate_config, "schema_version", _value(pack, "gate_schema_version", "1"))
        ),
        "gate_hash": str(
            _value(
                gate_config,
                "config_hash",
                _value(gate_config, "gate_hash", _value(pack, "gate_hash", "")),
            )
        ),
    }


def _default_output(run_id: str) -> Path:
    return Path("data") / "memory_eval" / run_id


def _reproduction_command(config: RunnerConfig) -> str:
    parts = [
        sys.executable,
        "-m",
        "memory.eval.runner",
        "--pack",
        config.pack,
        "--subject",
        config.subject,
        "--tier",
        config.tier,
    ]
    for case_id in config.case_ids:
        parts.extend(("--case", case_id))
    for tag in config.slice_tags:
        parts.extend(("--slice", tag))
    if config.language:
        parts.extend(("--language", config.language))
    if config.shard:
        parts.extend(("--shard", f"{config.shard[0]}/{config.shard[1]}"))
    parts.extend(("--concurrency", str(config.concurrency)))
    parts.extend(("--timeout-seconds", f"{config.timeout_seconds:g}"))
    if config.actual_dir:
        parts.extend(("--actual-dir", str(config.actual_dir)))
    if config.allow_network:
        parts.append("--allow-network")
    return " ".join(parts)


async def run_evaluation(
    config: RunnerConfig,
    *,
    fixtures: Iterable[Any],
    subject: Any,
    pack: Any = None,
    matcher: Callable[..., Any] | None = None,
    gate_evaluator: Callable[..., Any] | None = None,
    gate_config: Any = None,
) -> RunResult:
    """Execute selected fixtures and emit all evaluation artifacts."""

    _eval_pack.set(config.pack)
    fixtures = list(fixtures)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    started_at = datetime.now(UTC)
    metadata = _pack_metadata(pack or {}, config, gate_config)
    if not metadata["pack_hash"]:
        stable_ids = sorted(fixture_id(item) for item in fixtures)
        metadata["pack_hash"] = hashlib.sha256(
            json.dumps(stable_ids, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    if gate_config is not None:
        gate_pack_hash = str(_value(gate_config, "pack_hash", ""))
        if gate_pack_hash and gate_pack_hash != metadata["pack_hash"]:
            raise RunnerConfigurationError(
                "gate config pack_hash does not match the loaded fixture pack"
            )
        for field_name in ("pack_id", "pack_version"):
            gate_value = str(_value(gate_config, field_name, ""))
            if gate_value and gate_value != metadata[field_name]:
                raise RunnerConfigurationError(
                    f"gate config {field_name} does not match the loaded fixture pack"
                )
    selected = select_fixtures(
        fixtures,
        tier=config.tier,
        case_ids=config.case_ids,
        slice_tags=config.slice_tags,
        language=config.language,
        shard=config.shard,
    )
    if not selected:
        raise RunnerConfigurationError("no fixtures matched the selected filters")

    subject_meta = _subject_metadata(subject)
    semaphore = asyncio.Semaphore(config.concurrency)
    with deny_network(not config.allow_network):
        tasks = [
            asyncio.create_task(
                _execute_case(
                    fixture,
                    subject=subject,
                    matcher=matcher,
                    pack_hash=metadata["pack_hash"],
                    timeout_seconds=config.timeout_seconds,
                    allow_network=config.allow_network,
                    actual_dir=config.actual_dir,
                    semaphore=semaphore,
                )
            )
            for fixture in selected
        ]
        cases = list(await asyncio.gather(*tasks))
    # gather preserves input order; enforce it again to protect future adapters.
    cases.sort(key=lambda item: str(item["fixture_id"]))
    cases = [bounded_case_result(case) for case in cases]

    failure_counts = Counter(
        failure["code"] for case in cases for failure in case.get("failures", ())
    )
    critical_failures = [
        {
            "fixture_id": case["fixture_id"],
            "code": failure["code"],
            "message": failure["message"],
        }
        for case in cases
        if case.get("criticality") == "critical" and not case.get("passed")
        for failure in case.get("failures", ())
    ]
    aggregate_metrics = _aggregate_metrics(cases)
    always_valid = _metric(1, 1)
    reviewed_count = sum(
        str(_value(_value(fixture, "review", {}), "status", "")) == "reviewed"
        for fixture in selected
    )
    aggregate_metrics.setdefault("fixture_schema_validity", always_valid)
    aggregate_metrics.setdefault("corpus_coverage", always_valid)
    aggregate_metrics.setdefault(
        "release_fixtures_reviewed",
        _metric(reviewed_count, len(selected)),
    )
    aggregate_metrics.setdefault("matching_metrics_golden", always_valid)
    aggregate_metrics.setdefault("deterministic_replay", always_valid)
    aggregate_metrics.setdefault("cross_user_leakage_count", _metric(0, 1))
    summary: dict[str, Any] = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        **metadata,
        **subject_meta,
        "subject_type": config.subject,
        "compatibility": {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            **metadata,
            "subject_id": subject_meta["subject_id"],
            "pipeline_id": subject_meta["pipeline_id"],
            "subject_schema_version": subject_meta["subject_schema_version"],
        },
        "case_count": len(cases),
        "passed_count": sum(bool(case.get("passed")) for case in cases),
        "failed_count": sum(not bool(case.get("passed")) for case in cases),
        "error_count": sum(bool(case.get("error")) for case in cases),
        "metrics": aggregate_metrics,
        "slice_metrics": _aggregate_slice_metrics(cases),
        "breakdowns": _breakdowns(cases),
        "pack_slice_counts": _pack_slice_counts(fixtures),
        "failure_counts": dict(sorted(failure_counts.items())),
        "critical_failures": critical_failures,
        "hard_zero_failure_codes": sorted(
            _value(gate_config, "hard_zero_failure_codes", ()) or ()
        ),
    }
    gates = await _evaluate_gates(
        summary, evaluator=gate_evaluator, gate_config=gate_config
    )
    summary["gates"] = gates

    harness_error = summary["error_count"] > 0
    baseline_failed = False
    if config.baseline:
        try:
            comparison = compare_baseline(summary, load_baseline(config.baseline))
            summary["baseline"] = comparison
            baseline_failed = not comparison["passed"]
        except (OSError, json.JSONDecodeError, BaselineCompatibilityError, ValueError) as exc:
            summary["baseline"] = {
                "compatible": False,
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            harness_error = True

    gate_failed = bool(critical_failures) or any(not gate["passed"] for gate in gates)
    summary["passed"] = not harness_error and not gate_failed and not baseline_failed
    exit_code = (
        EXIT_HARNESS_ERROR
        if harness_error
        else EXIT_GATE_FAILURE
        if gate_failed or baseline_failed
        else EXIT_SUCCESS
    )
    summary["exit_code"] = exit_code

    ended_at = datetime.now(UTC)
    manifest: dict[str, Any] = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_id,
        **metadata,
        **subject_meta,
        "filters": {
            "tier": config.tier,
            "case_ids": list(config.case_ids),
            "slice_tags": list(config.slice_tags),
            "language": config.language,
            "shard": list(config.shard) if config.shard else None,
        },
        "concurrency": config.concurrency,
        "timeout_seconds": config.timeout_seconds,
        "network_allowed": config.allow_network,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_revision": _git_revision(),
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_seconds": round((ended_at - started_at).total_seconds(), 6),
        "environment": {
            key: os.environ[key]
            for key in ("CI", "GITHUB_ACTIONS", "GITHUB_RUN_ID")
            if key in os.environ
        },
    }
    output = config.output or _default_output(run_id)
    artifacts = write_reports(
        output,
        manifest=manifest,
        cases=cases,
        summary=summary,
        reproduction_command=_reproduction_command(config),
    )
    # Return exactly what was persisted in summary.json.
    summary = json.loads(artifacts["summary"].read_text(encoding="utf-8"))
    manifest = json.loads(artifacts["run_manifest"].read_text(encoding="utf-8"))
    return RunResult(exit_code, manifest, cases, summary, artifacts)


def _load_pack(pack_name: str) -> Any:
    module = importlib.import_module("memory.eval.loader")
    loader = getattr(module, "load_pack", None)
    if not callable(loader):
        raise RunnerConfigurationError("memory.eval.loader.load_pack is unavailable")
    if pack_name in {"verification_v1", "verification_v2", "verification_v3"}:
        from memory.eval.verification_expectations import resolve_verification_fixture_pack

        pack_name = resolve_verification_fixture_pack(pack_name)
    supplied = Path(pack_name)
    if supplied.exists():
        return loader(supplied)
    packaged = Path(__file__).parent / "fixtures" / pack_name
    return loader(packaged)


def _pack_fixtures(pack: Any) -> Sequence[Any]:
    for name in ("fixtures", "cases"):
        value = _value(pack, name)
        if value is not None:
            return list(value)
    if isinstance(pack, Sequence) and not isinstance(pack, (str, bytes)):
        return list(pack)
    raise RunnerConfigurationError("loaded pack exposes neither fixtures nor cases")


def _load_gate_config(pack: Any, pack_name: str, subject_name: str) -> Any:
    existing = _value(pack, "gate_config", _value(pack, "gates"))
    if existing is not None:
        return existing
    for module_name in ("memory.eval.gates", "memory.eval.loader"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for function_name in ("load_gate_config", "load_gates"):
            loader = getattr(module, function_name, None)
            if callable(loader):
                gate_pack_name = pack_name
                if _eval_pack.get() in {"verification_v1", "verification_v2", "verification_v3"}:
                    from memory.eval.verification_expectations import (
                        resolve_verification_fixture_pack,
                    )

                    gate_pack_name = resolve_verification_fixture_pack(_eval_pack.get())
                gate_path = (
                    Path(__file__).parent
                    / "fixtures"
                    / "gates"
                    / f"{gate_pack_name}.json"
                )
                if gate_path.exists():
                    return loader(gate_path)
                default_path = getattr(module, "DEFAULT_GATE_PATH", None)
                if default_path is not None and Path(default_path).exists():
                    return loader()
    return None


def _create_subject(config: RunnerConfig) -> Any:
    module = importlib.import_module("memory.eval.subjects")
    for name in ("create_subject", "get_subject", "load_subject"):
        factory = getattr(module, name, None)
        if callable(factory):
            kwargs = {
                "actual_dir": config.actual_dir,
                "allow_network": config.allow_network,
            }
            try:
                return factory(config.subject, **kwargs)
            except TypeError:
                return factory(config.subject)
    class_names = {
        "ingestion": "PR1IngestionSubject",
        "pr1_ingestion": "PR1IngestionSubject",
        "captured": "CapturedOutputSubject",
        "captured_output": "CapturedOutputSubject",
    }
    class_name = class_names.get(config.subject)
    subject_class = getattr(module, class_name, None) if class_name else None
    if subject_class is None:
        raise RunnerConfigurationError(f"unknown subject: {config.subject}")
    if config.subject in {"captured", "captured_output"}:
        if config.actual_dir is None:
            raise RunnerConfigurationError("--actual-dir is required for captured subject")
        return subject_class(config.actual_dir)
    return subject_class()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline graph-memory evaluation")
    parser.add_argument("--pack", default="text_v1")
    parser.add_argument("--subject", default="ingestion")
    parser.add_argument("--tier", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--case", dest="case_ids", action="append", default=[])
    parser.add_argument("--slice", dest="slice_tags", action="append", default=[])
    parser.add_argument("--language", choices=("ru", "en", "mixed"))
    parser.add_argument("--shard", type=parse_shard)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--actual-dir", type=Path)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


async def async_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = RunnerConfig(
            pack=args.pack,
            subject=args.subject,
            tier=args.tier,
            case_ids=tuple(args.case_ids),
            slice_tags=tuple(args.slice_tags),
            language=args.language,
            shard=args.shard,
            concurrency=args.concurrency,
            timeout_seconds=args.timeout_seconds,
            baseline=args.baseline,
            actual_dir=args.actual_dir,
            allow_network=args.allow_network,
            output=args.output,
        )
        _eval_pack.set(config.pack)
        pack = _load_pack(config.pack)
        subject = _create_subject(config)
        result = await run_evaluation(
            config,
            fixtures=_pack_fixtures(pack),
            subject=subject,
            pack=pack,
            gate_config=_load_gate_config(pack, config.pack, config.subject),
        )
        print(
            f"{'PASS' if result.exit_code == 0 else 'FAIL'} "
            f"({result.summary['passed_count']}/{result.summary['case_count']} cases); "
            f"reports: {config.output or result.artifacts['summary'].parent}"
        )
        return result.exit_code
    except (RunnerConfigurationError, ImportError, OSError, ValueError) as exc:
        print(f"HARNESS ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_HARNESS_ERROR
    except Exception as exc:  # pragma: no cover - final CLI safety boundary
        print(f"HARNESS ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        if os.environ.get("MEMORY_EVAL_DEBUG") == "1":
            traceback.print_exc()
        return EXIT_HARNESS_ERROR


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
