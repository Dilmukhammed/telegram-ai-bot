"""Run full text_v1 extraction (single strategy) and save detailed review artifacts."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from types import MappingProxyType
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory.eval.reports import bounded_case_result, write_reports
from memory.eval.runner import (
    RunnerConfig,
    _cleanup_subject,
    _default_match_case,
    _load_gate_config,
    _load_pack,
    _make_eval_context,
    _match_output,
    _pack_fixtures,
    _pack_metadata,
    _reproduction_command,
    derive_case_seed,
    fixture_id,
    select_fixtures,
)
from memory.eval.subjects import create_subject


def _to_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, MappingProxyType):
        return {str(key): _to_json(item) for key, item in value.items()}
    if is_dataclass(value):
        return {key: _to_json(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _to_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json(item) for item in value]
    if hasattr(value, "value"):
        enum_value = getattr(value, "value", None)
        if isinstance(enum_value, str):
            return enum_value
    return value


def _fixture_expected(case: Any) -> dict[str, Any]:
    path = ROOT / "memory" / "eval" / "fixtures" / "text_v1" / "cases" / f"{fixture_id(case)}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    expected = data.get("expected") or {}
    return {
        "expect_abstention": bool(expected.get("expect_abstention", False)),
        "mentions": list(expected.get("mentions") or []),
        "candidates": list(expected.get("candidates") or []),
        "forbidden_candidates": list(expected.get("forbidden_candidates") or []),
    }


def _segment_texts(case: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for event in getattr(case, "events", ()) or ():
        kind = str(getattr(event, "kind", "") or "")
        if kind == "chat_message":
            rows.append({"kind": kind, "text": str(getattr(event, "text", "") or "")})
        elif kind == "tool_result":
            rows.append({"kind": kind, "text": str(getattr(event, "payload_json", "") or "")})
    return rows


def _extraction_job_outputs(output: Any) -> list[dict[str, Any]]:
    jobs = list(output.jobs) if hasattr(output, "jobs") else list((output or {}).get("jobs") or [])
    extracted: list[dict[str, Any]] = []
    for job in jobs:
        if str(job.get("processor_name", "")) != "text_candidate_extractor":
            continue
        extracted.append(
            {
                "job_id": job.get("job_id"),
                "prompt_version": job.get("prompt_version"),
                "model_profile": job.get("model_profile"),
                "output": dict(job.get("output") or {}),
            }
        )
    return extracted


def _actual_snapshot(output: Any) -> dict[str, Any]:
    data = output.to_mapping() if hasattr(output, "to_mapping") else dict(output or {})
    return {
        "mentions": list(data.get("mentions") or []),
        "candidates": list(data.get("candidates") or []),
        "metadata": dict(data.get("metadata") or {}),
    }


async def _run_case(
    fixture: Any,
    *,
    subject: Any,
    pack_hash: str,
    timeout_seconds: float,
    allow_network: bool,
    review_path: Path,
) -> dict[str, Any]:
    item_id = fixture_id(fixture)
    context = _make_eval_context(
        fixture,
        seed=derive_case_seed(pack_hash, item_id),
        allow_network=allow_network,
        timeout_seconds=timeout_seconds,
        pack_hash=pack_hash,
        actual_dir=None,
    )
    started = time.perf_counter()
    try:
        output = await asyncio.wait_for(
            subject.run(fixture, context),
            timeout=timeout_seconds,
        )
        scored = await _match_output(fixture, output, _default_match_case)
    except TimeoutError:
        scored = {
            "fixture_id": item_id,
            "passed": False,
            "error": True,
            "failures": [
                {
                    "code": "subject_timeout",
                    "message": f"subject exceeded {timeout_seconds:g}s timeout",
                }
            ],
        }
        output = None
    except Exception as exc:
        scored = {
            "fixture_id": item_id,
            "passed": False,
            "error": True,
            "failures": [{"code": "subject_error", "message": f"{type(exc).__name__}: {exc}"}],
        }
        output = None
    finally:
        await _cleanup_subject(subject, fixture, context)

    review = {
        "fixture_id": item_id,
        "title": str(getattr(fixture, "title", "") or ""),
        "language": str(getattr(fixture, "language", "") or ""),
        "slice_tags": [str(tag) for tag in (getattr(fixture, "slice_tags", ()) or ())],
        "passed": bool(scored.get("passed")),
        "failures": list(scored.get("failures") or []),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "segment_texts": _segment_texts(fixture),
        "expected": _fixture_expected(fixture),
        "actual": _actual_snapshot(output) if output is not None else {},
        "extraction_jobs": _extraction_job_outputs(output) if output is not None else [],
    }
    with review_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(review, ensure_ascii=False) + "\n")
    scored.setdefault("fixture_id", item_id)
    scored.setdefault("title", review["title"])
    scored.setdefault("tier", str(getattr(fixture, "tier", "")))
    scored.setdefault("language", review["language"])
    scored.setdefault("criticality", str(getattr(fixture, "criticality", "normal")))
    scored.setdefault("slice_tags", review["slice_tags"])
    return scored


async def async_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args(argv)

    config = RunnerConfig(
        pack="text_v1",
        subject="extraction",
        tier="full",
        concurrency=max(1, args.concurrency),
        timeout_seconds=args.timeout_seconds,
        allow_network=True,
        output=args.output,
    )
    pack = _load_pack(config.pack)
    pack_hash = str(getattr(pack, "pack_hash", "") or config.pack)
    fixtures = select_fixtures(_pack_fixtures(pack), tier=config.tier)
    subject = create_subject(config.subject, allow_network=True)
    args.output.mkdir(parents=True, exist_ok=True)
    review_path = args.output / "manual_review.jsonl"
    review_path.write_text("", encoding="utf-8")

    semaphore = asyncio.Semaphore(config.concurrency)
    completed = 0
    total = len(fixtures)

    async def _guarded(fixture: Any) -> dict[str, Any]:
        nonlocal completed
        async with semaphore:
            result = await _run_case(
                fixture,
                subject=subject,
                pack_hash=pack_hash,
                timeout_seconds=config.timeout_seconds,
                allow_network=config.allow_network,
                review_path=review_path,
            )
            completed += 1
            status = "PASS" if result.get("passed") else "FAIL"
            print(f"[{completed}/{total}] {status} {fixture_id(fixture)}", flush=True)
            return result

    started_at = datetime.now(UTC)
    cases = list(await asyncio.gather(*[_guarded(fixture) for fixture in fixtures]))
    cases.sort(key=lambda item: str(item["fixture_id"]))
    cases = [bounded_case_result(case) for case in cases]

    passed_count = sum(bool(case.get("passed")) for case in cases)
    summary = {
        "report_schema_version": "1",
        **_pack_metadata(pack, config, _load_gate_config(pack, config.pack, config.subject)),
        "subject_id": getattr(subject, "subject_id", config.subject),
        "pipeline_id": getattr(subject, "pipeline_id", "unknown"),
        "subject_type": config.subject,
        "case_count": len(cases),
        "passed_count": passed_count,
        "failed_count": len(cases) - passed_count,
        "error_count": sum(bool(case.get("error")) for case in cases),
        "passed": passed_count == len(cases),
        "manual_review_path": str(review_path),
        "previous_baseline_note": "prior single-strategy full run was approximately 41/64",
    }
    run_id = started_at.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    manifest = {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "filters": {"tier": config.tier},
        "concurrency": config.concurrency,
        "timeout_seconds": config.timeout_seconds,
        "network_allowed": True,
    }
    artifacts = write_reports(
        args.output,
        manifest=manifest,
        cases=cases,
        summary=summary,
        reproduction_command=_reproduction_command(config),
    )
    (args.output / "manual_review_summary.json").write_text(
        json.dumps(
            {
                "passed": passed_count,
                "total": len(cases),
                "failed_fixtures": [case["fixture_id"] for case in cases if not case.get("passed")],
                "manual_review_path": str(review_path),
                "cases_jsonl": str(artifacts["cases"]),
                "summary_json": str(artifacts["summary"]),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Done: {passed_count}/{len(cases)} passed", flush=True)
    print(f"Artifacts: {args.output}", flush=True)
    return 0 if passed_count == len(cases) else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
