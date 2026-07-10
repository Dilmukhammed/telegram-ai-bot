from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from memory.eval.matching import MatchResult, to_plain


_WILSON_95_Z = 1.959963984540054


@dataclass(frozen=True)
class WilsonInterval:
    lower: float
    upper: float
    confidence: float = 0.95

    def as_dict(self) -> dict[str, float]:
        return {
            "confidence": self.confidence,
            "lower": self.lower,
            "upper": self.upper,
        }


@dataclass(frozen=True)
class Metric:
    numerator: float
    denominator: float

    def __post_init__(self) -> None:
        for name, value in (
            ("numerator", self.numerator),
            ("denominator", self.denominator),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.numerator > self.denominator:
            raise ValueError("numerator cannot exceed denominator")

    @property
    def value(self) -> float | None:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

    @property
    def wilson_95(self) -> WilsonInterval | None:
        if self.denominator == 0:
            return None
        return wilson_interval(self.numerator, self.denominator)

    def as_dict(self, *, include_interval: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": self.value,
        }
        if include_interval:
            interval = self.wilson_95
            result["wilson_95"] = None if interval is None else interval.as_dict()
        return result


@dataclass(frozen=True)
class PrecisionRecallF1:
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: Metric
    recall: Metric
    f1: Metric

    def as_dict(self) -> dict[str, Any]:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": self.precision.as_dict(),
            "recall": self.recall.as_dict(),
            "f1": self.f1.as_dict(),
        }


@dataclass(frozen=True)
class MetricAggregate:
    micro: Metric
    macro: Metric

    def as_dict(self) -> dict[str, Any]:
        return {
            "micro": self.micro.as_dict(),
            "macro": self.macro.as_dict(include_interval=False),
        }


@dataclass(frozen=True)
class AggregateReport:
    metrics: Mapping[str, MetricAggregate]
    slices: Mapping[str, Mapping[str, Mapping[str, MetricAggregate]]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "metrics": {
                name: aggregate.as_dict()
                for name, aggregate in sorted(self.metrics.items())
            },
            "slices": {
                dimension: {
                    value: {
                        name: aggregate.as_dict()
                        for name, aggregate in sorted(metrics.items())
                    }
                    for value, metrics in sorted(values.items())
                }
                for dimension, values in sorted(self.slices.items())
            },
        }


def wilson_interval(
    numerator: float,
    denominator: float,
    *,
    z: float = _WILSON_95_Z,
) -> WilsonInterval:
    """Return a deterministic two-sided Wilson score interval."""
    if isinstance(numerator, bool) or isinstance(denominator, bool):
        raise TypeError("Wilson counts must be numeric")
    if denominator <= 0:
        raise ValueError("Wilson denominator must be positive")
    if numerator < 0 or numerator > denominator:
        raise ValueError("Wilson numerator must be between zero and denominator")
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        raise ValueError("Wilson counts must be finite")
    if not math.isfinite(z) or z <= 0:
        raise ValueError("z must be finite and positive")
    proportion = numerator / denominator
    z_squared = z * z
    scale = 1.0 + z_squared / denominator
    center = (proportion + z_squared / (2.0 * denominator)) / scale
    margin = (
        z
        * math.sqrt(
            (proportion * (1.0 - proportion) / denominator)
            + (z_squared / (4.0 * denominator * denominator))
        )
        / scale
    )
    return WilsonInterval(
        lower=max(0.0, center - margin),
        upper=min(1.0, center + margin),
    )


def precision_recall_f1(
    true_positives: int,
    false_positives: int,
    false_negatives: int,
) -> PrecisionRecallF1:
    for name, value in (
        ("true_positives", true_positives),
        ("false_positives", false_positives),
        ("false_negatives", false_negatives),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    return PrecisionRecallF1(
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=Metric(true_positives, true_positives + false_positives),
        recall=Metric(true_positives, true_positives + false_negatives),
        f1=Metric(
            2 * true_positives,
            (2 * true_positives) + false_positives + false_negatives,
        ),
    )


def metrics_from_match(result: MatchResult) -> PrecisionRecallF1:
    return precision_recall_f1(
        result.true_positives,
        result.false_positives,
        result.false_negatives,
    )


calculate_precision_recall_f1 = precision_recall_f1


def coerce_metric(value: Any) -> Metric:
    if isinstance(value, Metric):
        return value
    plain = to_plain(value)
    if isinstance(plain, Mapping):
        if "numerator" not in plain or "denominator" not in plain:
            raise ValueError("metric mapping requires numerator and denominator")
        return Metric(plain["numerator"], plain["denominator"])
    if isinstance(plain, (list, tuple)) and len(plain) == 2:
        return Metric(plain[0], plain[1])
    raise TypeError("metric must be Metric, mapping/dataclass, or a two-item sequence")


def micro_average(metrics: Iterable[Any]) -> Metric:
    values = tuple(coerce_metric(metric) for metric in metrics)
    return Metric(
        sum(metric.numerator for metric in values),
        sum(metric.denominator for metric in values),
    )


def macro_average(metrics: Iterable[Any]) -> Metric:
    values = tuple(coerce_metric(metric) for metric in metrics)
    defined = tuple(metric.value for metric in values if metric.value is not None)
    return Metric(sum(defined), len(defined))


def aggregate_metric(metrics: Iterable[Any]) -> MetricAggregate:
    values = tuple(coerce_metric(metric) for metric in metrics)
    return MetricAggregate(micro=micro_average(values), macro=macro_average(values))


def _record_mapping(record: Any) -> Mapping[str, Any]:
    plain = to_plain(record)
    if not isinstance(plain, Mapping):
        raise TypeError("aggregate records must be mappings or dataclasses")
    return plain


def _record_metrics(record: Mapping[str, Any]) -> Mapping[str, Any]:
    metrics = record.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError("aggregate record requires a metrics mapping")
    return metrics


def _slice_values(record: Mapping[str, Any], field: str) -> tuple[str, ...]:
    value = record.get(field)
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(sorted({str(item) for item in value}))
    return (str(value),)


def aggregate_metrics(
    records: Iterable[Any],
    *,
    metric_names: Iterable[str] | None = None,
    slice_fields: Sequence[str] = (
        "language",
        "slice_tags",
        "candidate_kind",
        "criticality",
    ),
) -> AggregateReport:
    """Aggregate case metrics with exact micro/macro and deterministic slices."""
    case_records = tuple(_record_mapping(record) for record in records)
    if metric_names is None:
        names = sorted(
            {
                str(name)
                for record in case_records
                for name in _record_metrics(record)
            }
        )
    else:
        names = sorted({str(name) for name in metric_names})

    overall = {
        name: aggregate_metric(
            _record_metrics(record)[name]
            for record in case_records
            if name in _record_metrics(record)
        )
        for name in names
    }
    slices: dict[str, dict[str, dict[str, MetricAggregate]]] = {}
    for field in slice_fields:
        values = sorted(
            {
                value
                for record in case_records
                for value in _slice_values(record, field)
            }
        )
        slices[field] = {}
        for value in values:
            selected = tuple(
                record
                for record in case_records
                if value in _slice_values(record, field)
            )
            slices[field][value] = {
                name: aggregate_metric(
                    _record_metrics(record)[name]
                    for record in selected
                    if name in _record_metrics(record)
                )
                for name in names
            }
    return AggregateReport(metrics=overall, slices=slices)


def abstention_accuracy(
    cases: Iterable[tuple[bool, int]],
) -> Metric:
    """Score cases as correct when abstention expectation matches output emptiness."""
    values = tuple(cases)
    correct = sum(
        1
        for expect_abstention, actual_count in values
        if bool(expect_abstention) == (actual_count == 0)
    )
    return Metric(correct, len(values))
