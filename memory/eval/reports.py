"""Deterministic report generation for graph-memory evaluations."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree

REPORT_SCHEMA_VERSION = "1"
MAX_FAILURE_MESSAGE = 2_000
MAX_FAILURES_PER_CASE = 25
MAX_SIGNATURES_PER_CASE = 100


class BaselineCompatibilityError(ValueError):
    """Raised when a baseline cannot be compared to the current run."""


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically and without ASCII-escaping corpus text."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    )


def report_hash(cases: Sequence[Mapping[str, Any]], summary: Mapping[str, Any]) -> str:
    """Hash reproducible report content, excluding run-local metadata."""

    stable_summary = {
        key: value
        for key, value in summary.items()
        if key
        not in {
            "run_id",
            "output",
            "started_at",
            "ended_at",
            "duration_seconds",
            "report_hash",
        }
    }
    stable_cases = []
    for case in cases:
        stable_cases.append(
            {
                key: value
                for key, value in case.items()
                if key not in {"duration_seconds", "started_at", "ended_at"}
            }
        )
    payload = {"cases": stable_cases, "summary": stable_summary}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _bounded_text(value: Any, limit: int = MAX_FAILURE_MESSAGE) -> str:
    text = "".join(
        character
        if character in "\t\n\r" or ord(character) >= 32
        else "\N{REPLACEMENT CHARACTER}"
        for character in str(value)
    )
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 15)] + "...[truncated]"


def _finite_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _bounded_json(value: Any, *, depth: int = 0) -> Any:
    if depth >= 8:
        return "...[truncated]"
    if isinstance(value, Mapping):
        return {
            _bounded_text(key, 200): _bounded_json(item, depth=depth + 1)
            for key, item in list(sorted(value.items(), key=lambda pair: str(pair[0])))[:200]
        }
    if isinstance(value, (set, frozenset)):
        value = sorted(value, key=str)
    if isinstance(value, (list, tuple)):
        return [_bounded_json(item, depth=depth + 1) for item in list(value)[:200]]
    if isinstance(value, str):
        return _bounded_text(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def bounded_case_result(case: Mapping[str, Any]) -> dict[str, Any]:
    """Bound potentially provider-controlled fields before writing artifacts."""

    result = dict(case)
    failures: list[dict[str, Any]] = []
    for failure in list(result.get("failures") or [])[:MAX_FAILURES_PER_CASE]:
        if isinstance(failure, Mapping):
            item = dict(failure)
            item["code"] = _bounded_text(item.get("code", "failure"), 120)
            item["message"] = _bounded_text(item.get("message", ""), MAX_FAILURE_MESSAGE)
        else:
            item = {"code": "failure", "message": _bounded_text(failure)}
        failures.append(item)
    if len(result.get("failures") or []) > MAX_FAILURES_PER_CASE:
        failures.append(
            {"code": "failures_truncated", "message": "Additional failures omitted"}
        )
    result["failures"] = failures
    for key in ("expected_signatures", "actual_signatures"):
        values = result.get(key) or []
        result[key] = [
            _bounded_text(value, MAX_FAILURE_MESSAGE)
            for value in list(values)[:MAX_SIGNATURES_PER_CASE]
        ]
        if len(values) > MAX_SIGNATURES_PER_CASE:
            result[key].append("...[truncated]")
    result["metrics"] = _bounded_json(result.get("metrics") or {})
    result["usage"] = _bounded_json(result.get("usage") or {})
    return result


def _compatibility(summary: Mapping[str, Any]) -> dict[str, Any]:
    compatibility = summary.get("compatibility")
    if isinstance(compatibility, Mapping):
        return dict(compatibility)
    return {
        key: summary.get(key)
        for key in (
            "report_schema_version",
            "pack_id",
            "pack_version",
            "pack_hash",
            "gate_schema_version",
            "gate_hash",
            "subject_id",
            "pipeline_id",
            "subject_schema_version",
        )
        if summary.get(key) is not None
    }


def _metric_values(summary: Mapping[str, Any]) -> dict[str, float]:
    metrics = summary.get("metrics")
    if not isinstance(metrics, Mapping):
        return {}
    values: dict[str, float] = {}
    for name, raw in metrics.items():
        value: Any = raw
        if isinstance(raw, Mapping):
            if isinstance(raw.get("micro"), Mapping):
                raw = raw["micro"]
            value = raw.get("value")
            if value is None and raw.get("denominator"):
                value = float(raw.get("numerator", 0)) / float(raw["denominator"])
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if math.isfinite(float(value)):
                values[str(name)] = float(value)
    return values


def compare_baseline(
    summary: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    tolerances: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Compare compatible summaries and return deterministic metric deltas."""

    current_compat = _compatibility(summary)
    baseline_compat = _compatibility(baseline)
    keys = (
        "report_schema_version",
        "pack_id",
        "pack_version",
        "pack_hash",
        "gate_schema_version",
        "gate_hash",
        "subject_id",
        "pipeline_id",
        "subject_schema_version",
    )
    mismatches = {
        key: {"current": current_compat.get(key), "baseline": baseline_compat.get(key)}
        for key in keys
        if current_compat.get(key) != baseline_compat.get(key)
        and (current_compat.get(key) is not None or baseline_compat.get(key) is not None)
    }
    if mismatches:
        details = ", ".join(sorted(mismatches))
        raise BaselineCompatibilityError(f"incompatible baseline fields: {details}")

    current_metrics = _metric_values(summary)
    baseline_metrics = _metric_values(baseline)
    configured = dict(tolerances or summary.get("regression_tolerances") or {})
    deltas: dict[str, dict[str, Any]] = {}
    regressions: list[dict[str, Any]] = []
    for name in sorted(current_metrics.keys() & baseline_metrics.keys()):
        delta = current_metrics[name] - baseline_metrics[name]
        tolerance = float(configured.get(name, 0.0))
        item = {
            "current": current_metrics[name],
            "baseline": baseline_metrics[name],
            "delta": delta,
            "tolerance": tolerance,
        }
        deltas[name] = item
        if delta < -tolerance:
            regressions.append({"metric": name, **item})

    def critical_key(item: Any) -> tuple[str, str]:
        if isinstance(item, Mapping):
            return str(item.get("fixture_id", "")), str(item.get("code", ""))
        return str(item), ""

    current_critical = {
        critical_key(item) for item in summary.get("critical_failures", [])
    }
    baseline_critical = {
        critical_key(item) for item in baseline.get("critical_failures", [])
    }
    new_critical = [
        {"fixture_id": fixture_id, "code": code}
        for fixture_id, code in sorted(current_critical - baseline_critical)
    ]

    hard_zero_codes = set(summary.get("hard_zero_failure_codes") or [])
    current_codes = summary.get("failure_counts") or {}
    baseline_codes = baseline.get("failure_counts") or {}
    hard_zero_regressions = sorted(
        code
        for code in hard_zero_codes
        if int(current_codes.get(code, 0)) > 0 and int(baseline_codes.get(code, 0)) == 0
    )
    return {
        "compatible": True,
        "metric_deltas": deltas,
        "regressions": regressions,
        "new_critical_failures": new_critical,
        "hard_zero_regressions": hard_zero_regressions,
        "passed": not regressions and not new_critical and not hard_zero_regressions,
    }


def load_baseline(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BaselineCompatibilityError("baseline summary must be a JSON object")
    return data


def _render_markdown(
    summary: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    reproduction_command: str,
) -> str:
    passed = bool(summary.get("passed"))
    lines = [
        f"# Graph memory evaluation: {'PASS' if passed else 'FAIL'}",
        "",
        f"- Cases: {summary.get('case_count', len(cases))}",
        f"- Passed: {summary.get('passed_count', 0)}",
        f"- Failed: {summary.get('failed_count', 0)}",
        f"- Harness errors: {summary.get('error_count', 0)}",
        f"- Report hash: `{summary.get('report_hash', '')}`",
    ]

    critical = list(summary.get("critical_failures") or [])
    if critical:
        lines.extend(["", "## Critical failures"])
        for item in critical[:25]:
            if isinstance(item, Mapping):
                lines.append(
                    f"- `{_bounded_text(item.get('fixture_id', 'unknown'), 160)}`: "
                    f"{_bounded_text(item.get('message', item.get('code', 'failure')), 500)}"
                )
            else:
                lines.append(f"- {_bounded_text(item, 500)}")

    failed_gates = [
        gate for gate in summary.get("gates", []) if not bool(gate.get("passed", False))
    ]
    if failed_gates:
        lines.extend(["", "## Failed gates"])
        for gate in failed_gates[:50]:
            lines.append(
                f"- `{_bounded_text(gate.get('gate_id', gate.get('name', 'gate')), 160)}`: "
                f"{_bounded_text(gate.get('message', 'threshold not met'), 500)}"
            )

    baseline = summary.get("baseline")
    if isinstance(baseline, Mapping) and baseline.get("regressions"):
        lines.extend(["", "## Largest regressions"])
        regressions = sorted(
            baseline["regressions"], key=lambda item: float(item.get("delta", 0.0))
        )
        for item in regressions[:20]:
            lines.append(
                f"- `{item.get('metric')}`: {float(item.get('delta', 0.0)):+.6f}"
            )

    breakdowns = summary.get("breakdowns")
    if isinstance(breakdowns, Mapping) and breakdowns:
        lines.extend(["", "## Breakdowns"])
        for group_name in sorted(breakdowns):
            lines.append(f"- **{group_name}**: `{canonical_json(breakdowns[group_name])}`")

    slowest = sorted(
        cases,
        key=lambda item: (
            -_finite_float(item.get("duration_seconds", 0.0)),
            str(item.get("fixture_id")),
        ),
    )[:10]
    if slowest:
        lines.extend(["", "## Slowest cases"])
        for case in slowest:
            lines.append(
                f"- `{case.get('fixture_id')}`: "
                f"{_finite_float(case.get('duration_seconds', 0.0)):.3f}s"
            )

    costliest = sorted(
        cases,
        key=lambda item: (
            -_finite_float((item.get("usage") or {}).get("estimated_cost", 0.0)),
            str(item.get("fixture_id")),
        ),
    )[:10]
    if any(
        _finite_float((case.get("usage") or {}).get("estimated_cost", 0.0))
        for case in costliest
    ):
        lines.extend(["", "## Costliest cases"])
        for case in costliest:
            lines.append(
                f"- `{case.get('fixture_id')}`: "
                f"{_finite_float((case.get('usage') or {}).get('estimated_cost', 0.0)):.6f}"
            )

    if reproduction_command:
        lines.extend(["", "## Reproduce", "", f"`{_bounded_text(reproduction_command, 2_000)}`"])
    return "\n".join(lines) + "\n"


def _render_junit(cases: Sequence[Mapping[str, Any]]) -> bytes:
    failures = sum(1 for case in cases if not case.get("passed") and not case.get("error"))
    errors = sum(1 for case in cases if case.get("error"))
    suite = ElementTree.Element(
        "testsuite",
        {
            "name": "graph-memory-eval",
            "tests": str(len(cases)),
            "failures": str(failures),
            "errors": str(errors),
            "time": f"{sum(_finite_float(case.get('duration_seconds', 0.0)) for case in cases):.6f}",
        },
    )
    for case in cases:
        node = ElementTree.SubElement(
            suite,
            "testcase",
            {
                "classname": "memory.eval",
                "name": _bounded_text(case.get("fixture_id", "unknown"), 300),
                "time": f"{_finite_float(case.get('duration_seconds', 0.0)):.6f}",
            },
        )
        case_failures = list(case.get("failures") or [])
        if case_failures:
            first = case_failures[0]
            code = _bounded_text(first.get("code", "failure"), 120)
            message = _bounded_text(first.get("message", ""), MAX_FAILURE_MESSAGE)
            details = "; ".join(
                f"{_bounded_text(item.get('code', 'failure'), 120)}: "
                f"{_bounded_text(item.get('message', ''), 500)}"
                for item in case_failures[:5]
            )
            tag = "error" if case.get("error") else "failure"
            ElementTree.SubElement(
                node,
                tag,
                {"type": code, "message": message},
            ).text = _bounded_text(details, MAX_FAILURE_MESSAGE)
    return ElementTree.tostring(suite, encoding="utf-8", xml_declaration=True)


def write_reports(
    output_dir: str | Path,
    *,
    manifest: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    reproduction_command: str = "",
) -> dict[str, Path]:
    """Atomically-ish emit all required artifacts in deterministic case order."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    bounded_cases = [bounded_case_result(case) for case in cases]
    final_summary = dict(summary)
    final_summary.setdefault("report_schema_version", REPORT_SCHEMA_VERSION)
    final_summary["report_hash"] = report_hash(bounded_cases, final_summary)
    final_manifest = dict(manifest)
    final_manifest.setdefault("report_schema_version", REPORT_SCHEMA_VERSION)
    final_manifest["report_hash"] = final_summary["report_hash"]

    artifacts = {
        "run_manifest": output / "run_manifest.json",
        "cases": output / "cases.jsonl",
        "summary": output / "summary.json",
        "report": output / "report.md",
        "junit": output / "junit.xml",
    }
    artifacts["run_manifest"].write_text(
        json.dumps(final_manifest, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default)
        + "\n",
        encoding="utf-8",
    )
    cases_text = "".join(canonical_json(case) + "\n" for case in bounded_cases)
    artifacts["cases"].write_text(cases_text, encoding="utf-8")
    artifacts["summary"].write_text(
        json.dumps(final_summary, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default)
        + "\n",
        encoding="utf-8",
    )
    artifacts["report"].write_text(
        _render_markdown(final_summary, bounded_cases, reproduction_command),
        encoding="utf-8",
    )
    artifacts["junit"].write_bytes(_render_junit(bounded_cases))
    return artifacts
