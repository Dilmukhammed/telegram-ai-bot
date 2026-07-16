"""Run PR4 verification pack for manual review.

Live extract→verify; dumps actuals to JSONL + readable MD.
Gold match is recorded for reference only — exit status is runtime health,
not gold pass/fail (free labels make automated gold unreliable).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
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
from memory.verification.jobs import VERIFICATION_PROMPT_VERSION


def _to_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, MappingProxyType):
        return {str(key): _to_json(item) for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _to_json(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _to_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json(item) for item in value]
    if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
        return value.value
    return value


def _event_kind(event: Any) -> str:
    kind = getattr(event, "kind", "")
    return str(getattr(kind, "value", kind) or "")


def _segment_texts(case: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for event in getattr(case, "events", ()) or ():
        kind = _event_kind(event)
        event_id = str(getattr(event, "event_id", "") or "")
        if kind == "chat_message":
            text = str(getattr(event, "content", None) or getattr(event, "text", "") or "")
            rows.append({"event_id": event_id, "kind": kind, "text": text})
        elif kind == "tool_result":
            text = str(getattr(event, "payload_json", "") or "")
            rows.append({"event_id": event_id, "kind": kind, "text": text})
    return rows


def _fixture_expected_path(pack: str, case: Any) -> Path | None:
    item_id = fixture_id(case)
    pack_dir = ROOT / "memory" / "eval" / "fixtures" / pack / "cases"
    path = pack_dir / f"{item_id}.json"
    return path if path.is_file() else None


def _fixture_expected(pack: str, case: Any) -> dict[str, Any]:
    path = _fixture_expected_path(pack, case)
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    expected = data.get("expected") or {}
    return {
        "expect_abstention": bool(expected.get("expect_abstention", False)),
        "mentions": list(expected.get("mentions") or []),
        "candidates": list(expected.get("candidates") or []),
        "forbidden_candidates": list(expected.get("forbidden_candidates") or []),
    }


def _candidate_brief(candidate: dict[str, Any]) -> dict[str, Any]:
    epistemic = candidate.get("epistemic") or {}
    return {
        "candidate_ref": candidate.get("candidate_ref") or candidate.get("candidate_id"),
        "kind": candidate.get("kind") or candidate.get("candidate_kind"),
        "schema_name": candidate.get("schema_name"),
        "polarity": candidate.get("polarity"),
        "status": candidate.get("status"),
        "verification_status": candidate.get("verification_status"),
        "roles": [arg.get("role") for arg in candidate.get("arguments") or []],
        "literals": [
            arg.get("literal")
            for arg in candidate.get("arguments") or []
            if arg.get("has_literal") or arg.get("literal") is not None
        ],
        "epistemic_mode": epistemic.get("mode"),
        "commitment": epistemic.get("speaker_commitment"),
        "needs_confirmation": epistemic.get("needs_confirmation"),
    }


def _actual_snapshot(output: Any) -> dict[str, Any]:
    data = output.to_mapping() if hasattr(output, "to_mapping") else dict(output or {})
    candidates = list(data.get("candidates") or [])
    verdicts = list(data.get("verdicts") or [])
    scores = list(data.get("candidate_scores") or [])
    verdicts_by: dict[str, list[dict[str, Any]]] = {}
    for verdict in verdicts:
        key = str(verdict.get("candidate_id") or "")
        verdicts_by.setdefault(key, []).append(
            {
                "role": verdict.get("role"),
                "verdict": verdict.get("verdict"),
                "directness": verdict.get("evidence_directness"),
                "scope_errors": list(verdict.get("scope_errors") or []),
                "ambiguities": list(verdict.get("ambiguities") or []),
                "missing_context": list(verdict.get("missing_context") or []),
            }
        )
    scores_by = {
        str(score.get("candidate_id") or ""): {
            "route_status": score.get("route_status"),
            "components": dict(score.get("components") or {}),
            "status": score.get("status"),
        }
        for score in scores
    }
    joined = []
    for candidate in candidates:
        brief = _candidate_brief(candidate)
        key = str(brief.get("candidate_ref") or "")
        brief["verdicts"] = verdicts_by.get(key, [])
        brief["score"] = scores_by.get(key)
        joined.append(brief)
    return {
        "mentions": list(data.get("mentions") or []),
        "candidates": candidates,
        "candidate_briefs": joined,
        "verdicts": verdicts,
        "candidate_scores": scores,
        "metadata": dict(data.get("metadata") or {}),
    }


def _runtime_ok(scored: dict[str, Any]) -> bool:
    if scored.get("error"):
        return False
    for failure in scored.get("failures") or []:
        if str(failure.get("code") or "") in {"subject_timeout", "subject_error"}:
            return False
    return True


async def _run_case(
    fixture: Any,
    *,
    subject: Any,
    pack: str,
    pack_hash: str,
    timeout_seconds: float,
    allow_network: bool,
    review_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
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
    except Exception as exc:  # noqa: BLE001 - keep pack run going
        scored = {
            "fixture_id": item_id,
            "passed": False,
            "error": True,
            "failures": [{"code": "subject_error", "message": f"{type(exc).__name__}: {exc}"}],
        }
        output = None
    finally:
        await _cleanup_subject(subject, fixture, context)

    actual = _actual_snapshot(output) if output is not None else {}
    review = {
        "fixture_id": item_id,
        "title": str(getattr(fixture, "title", "") or ""),
        "language": str(getattr(fixture, "language", "") or ""),
        "slice_tags": [str(tag) for tag in (getattr(fixture, "slice_tags", ()) or ())],
        "gold_passed": bool(scored.get("passed")),
        "runtime_ok": _runtime_ok(scored),
        "failures": list(scored.get("failures") or []),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "segment_texts": _segment_texts(fixture),
        "expected_reference": _fixture_expected(pack, fixture),
        "actual": actual,
    }
    with review_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(review, ensure_ascii=False) + "\n")

    scored.setdefault("fixture_id", item_id)
    scored.setdefault("title", review["title"])
    scored.setdefault("tier", str(getattr(fixture, "tier", "")))
    scored.setdefault("language", review["language"])
    scored.setdefault("criticality", str(getattr(fixture, "criticality", "normal")))
    scored.setdefault("slice_tags", review["slice_tags"])
    scored["runtime_ok"] = review["runtime_ok"]
    scored["gold_passed"] = review["gold_passed"]
    return scored, review


def _write_markdown(path: Path, *, report: dict[str, Any], reviews: list[dict[str, Any]]) -> None:
    lines: list[str] = [
        "# PR4 verification manual review",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- pack: `{report['pack']}`",
        f"- tier: `{report['tier']}`",
        f"- subject: `{report['subject']}`",
        f"- verification_prompt_version: `{report['verification_prompt_version']}`",
        f"- runtime_ok: **{report['runtime_ok_count']}/{report['case_count']}**",
        f"- gold_passed (reference only): `{report['gold_passed_count']}/{report['case_count']}`",
        "",
        "Gold failures are expected under free labels. Judge routes/verdicts by eye.",
        "",
    ]
    for case in reviews:
        lines.append(f"## {case['fixture_id']}")
        lines.append("")
        lines.append(f"- title: {case.get('title')}")
        lines.append(f"- language: `{case.get('language')}`")
        lines.append(f"- tags: `{case.get('slice_tags')}`")
        lines.append(f"- runtime_ok: `{case.get('runtime_ok')}`")
        lines.append(f"- gold_passed: `{case.get('gold_passed')}`")
        lines.append(f"- duration_s: `{case.get('duration_seconds')}`")
        lines.append("")
        lines.append("### Input")
        lines.append("")
        for segment in case.get("segment_texts") or []:
            lines.append(f"- `{segment.get('event_id')}` ({segment.get('kind')}):")
            lines.append("")
            lines.append("```text")
            lines.append(str(segment.get("text") or ""))
            lines.append("```")
            lines.append("")
        if not case.get("runtime_ok"):
            lines.append("**runtime failures:**")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(case.get("failures") or [], ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
            continue
        actual = case.get("actual") or {}
        briefs = list(actual.get("candidate_briefs") or [])
        lines.append(f"### Actual candidates ({len(briefs)})")
        lines.append("")
        if not briefs:
            lines.append("_no candidates_")
            lines.append("")
        for item in briefs:
            score = item.get("score") or {}
            lines.append(
                "- "
                f"schema=`{item.get('schema_name')}` "
                f"kind=`{item.get('kind')}` "
                f"polarity=`{item.get('polarity')}` "
                f"mode=`{item.get('epistemic_mode')}`/"
                f"`{item.get('commitment')}` "
                f"verify=`{item.get('verification_status')}` "
                f"route=`{score.get('route_status')}` "
                f"roles=`{item.get('roles')}` "
                f"literals=`{item.get('literals')}`"
            )
            for verdict in item.get("verdicts") or []:
                extra = ""
                if verdict.get("scope_errors"):
                    extra += f" scope={verdict.get('scope_errors')}"
                if verdict.get("ambiguities"):
                    extra += f" amb={verdict.get('ambiguities')}"
                lines.append(
                    f"  - {verdict.get('role')}: `{verdict.get('verdict')}`"
                    f" direct=`{verdict.get('directness')}`{extra}"
                )
        lines.append("")
        if case.get("failures"):
            lines.append("<details><summary>gold failures (reference)</summary>")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(case.get("failures"), ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
            lines.append("</details>")
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def async_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack",
        default="text_v1_verification_v3",
        help="fixture pack id (default: text_v1_verification_v3)",
    )
    parser.add_argument("--tier", default="smoke", help="fixture tier filter")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--language", default=None)
    parser.add_argument("--slice", action="append", default=[], dest="slice_tags")
    parser.add_argument("--case", action="append", default=[], dest="case_ids")
    args = parser.parse_args(argv)

    config = RunnerConfig(
        pack=args.pack,
        subject="verification",
        tier=args.tier,
        concurrency=max(1, args.concurrency),
        timeout_seconds=args.timeout_seconds,
        allow_network=True,
        output=args.output,
        language=args.language,
        slice_tags=tuple(args.slice_tags or ()),
        case_ids=tuple(args.case_ids or ()),
    )
    pack = _load_pack(config.pack)
    pack_hash = str(getattr(pack, "pack_hash", "") or config.pack)
    fixtures = select_fixtures(
        _pack_fixtures(pack),
        tier=config.tier,
        case_ids=config.case_ids,
        slice_tags=config.slice_tags,
        language=config.language,
    )
    if not fixtures:
        raise SystemExit("no fixtures matched filters")

    subject = create_subject(config.subject, allow_network=True)
    args.output.mkdir(parents=True, exist_ok=True)
    review_path = args.output / "manual_review.jsonl"
    review_path.write_text("", encoding="utf-8")

    semaphore = asyncio.Semaphore(config.concurrency)
    completed = 0
    total = len(fixtures)
    reviews: list[dict[str, Any]] = []

    async def _guarded(fixture: Any) -> dict[str, Any]:
        nonlocal completed
        async with semaphore:
            scored, review = await _run_case(
                fixture,
                subject=subject,
                pack=config.pack,
                pack_hash=pack_hash,
                timeout_seconds=config.timeout_seconds,
                allow_network=config.allow_network,
                review_path=review_path,
            )
            reviews.append(review)
            completed += 1
            runtime = "OK" if review.get("runtime_ok") else "RUNTIME_FAIL"
            gold = "gold+" if review.get("gold_passed") else "gold-"
            print(
                f"[{completed}/{total}] {runtime} {gold} {fixture_id(fixture)} "
                f"({review.get('duration_seconds')}s)",
                flush=True,
            )
            return scored

    started_at = datetime.now(UTC)
    cases = list(await asyncio.gather(*[_guarded(fixture) for fixture in fixtures]))
    cases.sort(key=lambda item: str(item["fixture_id"]))
    cases = [bounded_case_result(case) for case in cases]
    reviews.sort(key=lambda item: str(item["fixture_id"]))

    runtime_ok_count = sum(1 for item in reviews if item.get("runtime_ok"))
    gold_passed_count = sum(1 for item in reviews if item.get("gold_passed"))
    report_meta = {
        "generated_at": datetime.now(UTC).isoformat(),
        "pack": config.pack,
        "tier": config.tier,
        "subject": config.subject,
        "verification_prompt_version": VERIFICATION_PROMPT_VERSION,
        "case_count": len(reviews),
        "runtime_ok_count": runtime_ok_count,
        "gold_passed_count": gold_passed_count,
    }
    md_path = args.output / "manual_review.md"
    _write_markdown(md_path, report=report_meta, reviews=reviews)
    latest_md = args.output / "manual_review-latest.md"
    latest_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")

    summary = {
        "report_schema_version": "1",
        **_pack_metadata(pack, config, _load_gate_config(pack, config.pack, config.subject)),
        "subject_id": getattr(subject, "subject_id", config.subject),
        "pipeline_id": getattr(subject, "pipeline_id", "unknown"),
        "subject_type": config.subject,
        "case_count": len(cases),
        "runtime_ok_count": runtime_ok_count,
        "gold_passed_count": gold_passed_count,
        "passed_count": gold_passed_count,
        "failed_count": len(cases) - gold_passed_count,
        "error_count": sum(bool(case.get("error")) for case in cases),
        "passed": runtime_ok_count == len(cases),
        "manual_review_path": str(review_path),
        "manual_review_md": str(md_path),
        "note": "Exit/pass based on runtime_ok; gold_passed is reference only.",
    }
    run_id = started_at.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    manifest = {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "filters": {
            "tier": config.tier,
            "language": config.language,
            "slice_tags": list(config.slice_tags),
            "case_ids": list(config.case_ids),
        },
        "concurrency": config.concurrency,
        "timeout_seconds": config.timeout_seconds,
        "network_allowed": True,
        "verification_prompt_version": VERIFICATION_PROMPT_VERSION,
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
                **report_meta,
                "runtime_failed_fixtures": [
                    item["fixture_id"] for item in reviews if not item.get("runtime_ok")
                ],
                "gold_failed_fixtures": [
                    item["fixture_id"] for item in reviews if not item.get("gold_passed")
                ],
                "manual_review_path": str(review_path),
                "manual_review_md": str(md_path),
                "cases_jsonl": str(artifacts["cases"]),
                "summary_json": str(artifacts["summary"]),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Done: runtime_ok {runtime_ok_count}/{len(cases)}; "
        f"gold_passed {gold_passed_count}/{len(cases)} (reference)",
        flush=True,
    )
    print(f"Review MD: {md_path}", flush=True)
    print(f"Artifacts: {args.output}", flush=True)
    return 0 if runtime_ok_count == len(cases) else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
