from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory.eval.matching import FAILURE_CODE_SET, canonical_json, to_plain
from memory.eval.metrics import Metric, MetricAggregate


GATE_SCHEMA_VERSION = "1"
DEFAULT_GATE_PATH = Path(__file__).parent / "fixtures" / "gates" / "text_v1.json"
_COMPARISONS = frozenset({"gte", "lte", "eq"})
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "gate_id",
        "gate_version",
        "pack_id",
        "pack_version",
        "pack_hash",
        "subject_type",
        "gates",
        "hard_zero_failure_codes",
        "minimum_slice_counts",
    }
)
_GATE_FIELDS = frozenset(
    {"metric", "comparison", "threshold", "active", "subjects"}
)


class GateConfigError(ValueError):
    pass


@dataclass(frozen=True)
class GateSpec:
    metric: str
    comparison: str
    threshold: float
    active: bool
    subjects: tuple[str, ...] = ()

    def applies_to(self, subject_type: str | None) -> bool:
        return self.active and (
            not self.subjects
            or subject_type is None
            or subject_type in self.subjects
        )

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "metric": self.metric,
            "comparison": self.comparison,
            "threshold": self.threshold,
            "active": self.active,
        }
        if self.subjects:
            result["subjects"] = list(self.subjects)
        return result


@dataclass(frozen=True)
class GateConfig:
    schema_version: str
    gate_id: str
    gate_version: str
    pack_id: str
    pack_version: str
    pack_hash: str
    subject_type: str
    gates: tuple[GateSpec, ...]
    hard_zero_failure_codes: tuple[str, ...]
    minimum_slice_counts: Mapping[str, int]
    config_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "gate_id": self.gate_id,
            "gate_version": self.gate_version,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "pack_hash": self.pack_hash,
            "subject_type": self.subject_type,
            "gates": [gate.as_dict() for gate in self.gates],
            "hard_zero_failure_codes": list(self.hard_zero_failure_codes),
            "minimum_slice_counts": dict(sorted(self.minimum_slice_counts.items())),
        }


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    observed: float | int | None
    comparison: str
    threshold: float | int
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "observed": self.observed,
            "comparison": self.comparison,
            "threshold": self.threshold,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GateEvaluation:
    passed: bool
    gate_hash: str
    results: tuple[GateResult, ...]

    @property
    def failed(self) -> tuple[GateResult, ...]:
        return tuple(result for result in self.results if not result.passed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "gate_hash": self.gate_hash,
            "results": [result.as_dict() for result in self.results],
        }


def _required_text(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise GateConfigError(f"{name} must be a non-empty string")
    return value


def _config_payload(config: Any) -> dict[str, Any]:
    if isinstance(config, GateConfig):
        return config.as_dict()
    plain = to_plain(config)
    if not isinstance(plain, dict):
        raise GateConfigError("gate config must be a mapping or dataclass")
    plain.pop("config_hash", None)
    return plain


def gate_config_hash(config: Any) -> str:
    payload = canonical_json(_config_payload(config)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


gate_hash = gate_config_hash


def parse_gate_config(config: Any) -> GateConfig:
    data = _config_payload(config)
    unknown = set(data) - _TOP_LEVEL_FIELDS
    missing = _TOP_LEVEL_FIELDS - set(data)
    if unknown:
        raise GateConfigError(f"unknown gate config fields: {sorted(unknown)}")
    if missing:
        raise GateConfigError(f"missing gate config fields: {sorted(missing)}")
    schema_version = _required_text(data, "schema_version")
    if schema_version != GATE_SCHEMA_VERSION:
        raise GateConfigError(f"unsupported gate schema version: {schema_version!r}")

    raw_gates = data["gates"]
    if not isinstance(raw_gates, list):
        raise GateConfigError("gates must be a list")
    gates: list[GateSpec] = []
    seen_metrics: set[str] = set()
    for index, raw_gate in enumerate(raw_gates):
        if not isinstance(raw_gate, Mapping):
            raise GateConfigError(f"gates[{index}] must be a mapping")
        unknown_gate_fields = set(raw_gate) - _GATE_FIELDS
        required_gate_fields = {"metric", "comparison", "threshold", "active"}
        missing_gate_fields = required_gate_fields - set(raw_gate)
        if unknown_gate_fields:
            raise GateConfigError(
                f"unknown gates[{index}] fields: {sorted(unknown_gate_fields)}"
            )
        if missing_gate_fields:
            raise GateConfigError(
                f"missing gates[{index}] fields: {sorted(missing_gate_fields)}"
            )
        metric = _required_text(raw_gate, "metric")
        if metric in seen_metrics:
            raise GateConfigError(f"duplicate gate metric: {metric!r}")
        seen_metrics.add(metric)
        comparison = raw_gate["comparison"]
        if comparison not in _COMPARISONS:
            raise GateConfigError(
                f"gates[{index}].comparison must be one of {sorted(_COMPARISONS)}"
            )
        threshold = raw_gate["threshold"]
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise GateConfigError(f"gates[{index}].threshold must be numeric")
        if not math.isfinite(threshold):
            raise GateConfigError(f"gates[{index}].threshold must be finite")
        active = raw_gate["active"]
        if not isinstance(active, bool):
            raise GateConfigError(f"gates[{index}].active must be boolean")
        raw_subjects = raw_gate.get("subjects", [])
        if (
            not isinstance(raw_subjects, list)
            or any(not isinstance(subject, str) or not subject for subject in raw_subjects)
        ):
            raise GateConfigError(f"gates[{index}].subjects must be a string list")
        gates.append(
            GateSpec(
                metric=metric,
                comparison=comparison,
                threshold=float(threshold),
                active=active,
                subjects=tuple(sorted(set(raw_subjects))),
            )
        )

    raw_codes = data["hard_zero_failure_codes"]
    if not isinstance(raw_codes, list) or any(not isinstance(code, str) for code in raw_codes):
        raise GateConfigError("hard_zero_failure_codes must be a string list")
    unknown_codes = set(raw_codes) - FAILURE_CODE_SET
    if unknown_codes:
        raise GateConfigError(f"unknown hard-zero failure codes: {sorted(unknown_codes)}")
    if len(raw_codes) != len(set(raw_codes)):
        raise GateConfigError("hard_zero_failure_codes contains duplicates")

    raw_slice_counts = data["minimum_slice_counts"]
    if not isinstance(raw_slice_counts, Mapping):
        raise GateConfigError("minimum_slice_counts must be a mapping")
    slice_counts: dict[str, int] = {}
    for name, count in raw_slice_counts.items():
        if not isinstance(name, str) or not name:
            raise GateConfigError("minimum slice names must be non-empty strings")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise GateConfigError(f"minimum slice count for {name!r} must be non-negative")
        slice_counts[name] = count

    normalized = {
        **data,
        "gates": [gate.as_dict() for gate in gates],
        "hard_zero_failure_codes": sorted(raw_codes),
        "minimum_slice_counts": dict(sorted(slice_counts.items())),
    }
    return GateConfig(
        schema_version=schema_version,
        gate_id=_required_text(data, "gate_id"),
        gate_version=_required_text(data, "gate_version"),
        pack_id=_required_text(data, "pack_id"),
        pack_version=_required_text(data, "pack_version"),
        pack_hash=_required_text(data, "pack_hash"),
        subject_type=_required_text(data, "subject_type"),
        gates=tuple(gates),
        hard_zero_failure_codes=tuple(sorted(raw_codes)),
        minimum_slice_counts=dict(sorted(slice_counts.items())),
        config_hash=gate_config_hash(normalized),
    )


def load_gate_config(path: str | Path = DEFAULT_GATE_PATH) -> GateConfig:
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise GateConfigError(f"cannot load gate config {source}: {exc}") from exc
    return parse_gate_config(data)


def _metric_observed(value: Any) -> float | None:
    if isinstance(value, MetricAggregate):
        return value.micro.value
    if isinstance(value, Metric):
        return value.value
    plain = to_plain(value)
    if isinstance(plain, Mapping):
        if "micro" in plain:
            return _metric_observed(plain["micro"])
        if "numerator" in plain and "denominator" in plain:
            return Metric(plain["numerator"], plain["denominator"]).value
        if "value" in plain:
            return _metric_observed(plain["value"])
    if plain is None:
        return None
    if isinstance(plain, bool) or not isinstance(plain, (int, float)):
        raise TypeError("gate metric must be numeric or contain raw counts")
    return float(plain)


def _passes(observed: float, comparison: str, threshold: float) -> bool:
    if comparison == "gte":
        return observed >= threshold
    if comparison == "lte":
        return observed <= threshold
    return observed == threshold


def _failure_code(value: Any) -> str:
    if isinstance(value, str):
        return value
    plain = to_plain(value)
    if isinstance(plain, Mapping) and isinstance(plain.get("code"), str):
        return plain["code"]
    raise TypeError("failures must be codes or mapping/dataclass objects with a code")


def evaluate_gates(
    config: GateConfig | Mapping[str, Any],
    metrics: Mapping[str, Any],
    *,
    failure_codes: Iterable[Any] = (),
    slice_counts: Mapping[str, int] | None = None,
    subject_type: str | None = None,
) -> GateEvaluation:
    parsed = config if isinstance(config, GateConfig) else parse_gate_config(config)
    if (
        subject_type is not None
        and parsed.subject_type not in {"all", subject_type}
    ):
        raise GateConfigError(
            f"gate config is for {parsed.subject_type!r}, not {subject_type!r}"
        )
    results: list[GateResult] = []
    for gate in parsed.gates:
        if not gate.applies_to(subject_type):
            continue
        if gate.metric not in metrics:
            results.append(
                GateResult(
                    name=gate.metric,
                    passed=False,
                    observed=None,
                    comparison=gate.comparison,
                    threshold=gate.threshold,
                    reason="metric_missing",
                )
            )
            continue
        observed = _metric_observed(metrics[gate.metric])
        results.append(
            GateResult(
                name=gate.metric,
                passed=observed is not None
                and _passes(observed, gate.comparison, gate.threshold),
                observed=observed,
                comparison=gate.comparison,
                threshold=gate.threshold,
                reason=None if observed is not None else "metric_undefined",
            )
        )

    failure_counts = Counter(_failure_code(failure) for failure in failure_codes)
    unknown_failures = set(failure_counts) - FAILURE_CODE_SET
    if unknown_failures:
        raise ValueError(f"unknown evaluation failure codes: {sorted(unknown_failures)}")
    for code in parsed.hard_zero_failure_codes:
        observed = failure_counts[code]
        results.append(
            GateResult(
                name=f"failure_code:{code}",
                passed=observed == 0,
                observed=observed,
                comparison="eq",
                threshold=0,
            )
        )

    supplied_slice_counts = {} if slice_counts is None else dict(slice_counts)
    for name, minimum in parsed.minimum_slice_counts.items():
        observed = supplied_slice_counts.get(name, 0)
        if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
            raise ValueError(f"slice count for {name!r} must be a non-negative integer")
        results.append(
            GateResult(
                name=f"slice_count:{name}",
                passed=observed >= minimum,
                observed=observed,
                comparison="gte",
                threshold=minimum,
            )
        )

    ordered = tuple(sorted(results, key=lambda result: result.name))
    return GateEvaluation(
        passed=all(result.passed for result in ordered),
        gate_hash=parsed.config_hash,
        results=ordered,
    )
