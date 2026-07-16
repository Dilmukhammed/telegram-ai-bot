"""Live PR4 free-field verification probe.

Runs the curated PR3 free-field utterances through the full extract→verify
path and writes JSON + markdown reports.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory.eval.subjects import (  # noqa: E402
    EvalContext,
    SubjectOutput,
    _build_verification_subject,
)
from memory.verification.jobs import VERIFICATION_PROMPT_VERSION  # noqa: E402


def _load_pr3_probes() -> list[dict[str, Any]]:
    path = ROOT / "scripts" / "run_pr3_free_fields_live.py"
    spec = importlib.util.spec_from_file_location("run_pr3_free_fields_live", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.PROBES)


PROBES: list[dict[str, Any]] = _load_pr3_probes()


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
    if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
        return value.value
    return value


def _load_probes(*, from_pr3_json: Path | None, ids: str | None) -> list[dict[str, Any]]:
    if from_pr3_json is not None:
        payload = json.loads(from_pr3_json.read_text(encoding="utf-8"))
        cases = payload.get("cases") or []
        probes: list[dict[str, Any]] = []
        by_id = {probe["id"]: probe for probe in PROBES}
        for case in cases:
            probe_id = str(case.get("id") or "")
            base = dict(by_id.get(probe_id) or {})
            base.update(
                {
                    "id": probe_id,
                    "language": case.get("language") or base.get("language"),
                    "segment_text": case.get("segment_text") or base.get("segment_text"),
                    "authority_class": case.get("authority_class")
                    or base.get("authority_class"),
                    "note": case.get("note") or base.get("note"),
                    "source_type": base.get("source_type") or "chat",
                    "prior_segments": base.get("prior_segments") or [],
                }
            )
            if base.get("segment_text"):
                probes.append(base)
        selected = probes
    else:
        selected = list(PROBES)

    if ids:
        wanted = {item.strip() for item in ids.split(",") if item.strip()}
        selected = [probe for probe in selected if probe["id"] in wanted]
        missing = sorted(wanted - {probe["id"] for probe in selected})
        if missing:
            raise SystemExit(f"unknown probe ids: {missing}")
    return selected


def _fixture_from_probe(probe: dict[str, Any], *, user_id: int) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    minute = 0
    for index, prior in enumerate(probe.get("prior_segments") or []):
        minute += 1
        events.append(
            {
                "event_id": f"prior{index}",
                "kind": "chat_message",
                "user_alias": "u1",
                "role": "user",
                "content": str(prior["segment_text"]),
                "content_type": "text",
                "occurred_at": f"2026-07-11T10:{minute:02d}:00+05:00",
                "metadata": {},
            }
        )
    minute += 1
    if str(probe.get("source_type") or "chat") == "tool":
        events.append(
            {
                "event_id": "t1",
                "kind": "tool_result",
                "user_alias": "u1",
                "tool_name": "tasks.create",
                "payload_kind": "result",
                "payload_json": str(probe["segment_text"]),
                "ok": True,
                "cached": False,
                "occurred_at": f"2026-07-11T10:{minute:02d}:00+05:00",
            }
        )
    else:
        events.append(
            {
                "event_id": "m1",
                "kind": "chat_message",
                "user_alias": "u1",
                "role": "user",
                "content": str(probe["segment_text"]),
                "content_type": "text",
                "occurred_at": f"2026-07-11T10:{minute:02d}:00+05:00",
                "metadata": {},
            }
        )
    return {
        "fixture_id": str(probe["id"]),
        "users": [{"user_alias": "u1", "user_id": user_id}],
        "events": events,
        "expected": {"sources": [], "segments": [], "mentions": [], "candidates": []},
    }


def _case_summary(output: SubjectOutput) -> dict[str, Any]:
    verdicts_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for verdict in output.verdicts:
        candidate_id = str(verdict.get("candidate_id") or "")
        verdicts_by_candidate.setdefault(candidate_id, []).append(
            {
                "role": verdict.get("role"),
                "verdict": verdict.get("verdict"),
                "scope_errors": list(verdict.get("scope_errors") or []),
            }
        )
    scores_by_candidate = {
        str(score.get("candidate_id") or ""): {
            "route_status": score.get("route_status"),
            "argument_completeness": (score.get("components") or {}).get(
                "argument_completeness"
            ),
        }
        for score in output.candidate_scores
    }
    candidates = []
    for candidate in output.candidates:
        candidate_id = str(
            candidate.get("candidate_id")
            or candidate.get("candidate_ref")
            or ""
        )
        candidates.append(
            {
                "candidate_id": candidate_id,
                "kind": candidate.get("kind") or candidate.get("candidate_kind"),
                "schema_name": candidate.get("schema_name"),
                "polarity": candidate.get("polarity"),
                "status": candidate.get("verification_status") or candidate.get("status"),
                "roles": [
                    arg.get("role") for arg in candidate.get("arguments") or []
                ],
                "epistemic_mode": (candidate.get("epistemic") or {}).get("mode"),
                "verdicts": verdicts_by_candidate.get(candidate_id, []),
                "score": scores_by_candidate.get(candidate_id),
            }
        )
    return {
        "candidate_count": len(candidates),
        "verdict_count": len(output.verdicts),
        "score_count": len(output.candidate_scores),
        "candidates": candidates,
    }


async def _run_probe(
    subject: Any,
    probe: dict[str, Any],
    *,
    user_id: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    started = datetime.now(UTC)
    fixture = _fixture_from_probe(probe, user_id=user_id)
    try:
        output = await subject.run(
            fixture,
            EvalContext(
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=0.05,
            ),
        )
        summary = _case_summary(output)
        return {
            "id": probe["id"],
            "ok": True,
            "note": probe.get("note"),
            "language": probe.get("language"),
            "segment_text": probe.get("segment_text"),
            "authority_class": probe.get("authority_class"),
            "elapsed_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
            "summary": summary,
            "output": _to_json(output),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - probe should keep going
        return {
            "id": probe["id"],
            "ok": False,
            "note": probe.get("note"),
            "language": probe.get("language"),
            "segment_text": probe.get("segment_text"),
            "authority_class": probe.get("authority_class"),
            "elapsed_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
            "summary": None,
            "output": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines: list[str] = [
        "# PR4 free-field live probe",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- verification_prompt_version: `{report['verification_prompt_version']}`",
        f"- ok: **{report['ok_count']}/{report['probe_count']}**",
        "",
    ]
    for case in report["cases"]:
        lines.append(f"## {case['id']}")
        lines.append("")
        lines.append(f"- note: {case.get('note')}")
        lines.append(f"- ok: `{case['ok']}`")
        lines.append(f"- elapsed_ms: `{case.get('elapsed_ms')}`")
        lines.append("")
        lines.append("```text")
        lines.append(str(case.get("segment_text") or ""))
        lines.append("```")
        lines.append("")
        if not case["ok"]:
            lines.append(f"**error:** `{case.get('error')}`")
            lines.append("")
            continue
        summary = case.get("summary") or {}
        lines.append(f"- candidates: `{summary.get('candidate_count')}`")
        lines.append(f"- verdicts: `{summary.get('verdict_count')}`")
        lines.append(f"- scores: `{summary.get('score_count')}`")
        lines.append("- verified:")
        for item in summary.get("candidates") or []:
            score = item.get("score") or {}
            lines.append(
                "  - "
                f"kind=`{item.get('kind')}` "
                f"schema=`{item.get('schema_name')}` "
                f"status=`{item.get('status')}` "
                f"route=`{score.get('route_status')}` "
                f"roles=`{item.get('roles')}` "
                f"verdicts=`{[v.get('role') + ':' + str(v.get('verdict')) for v in item.get('verdicts') or []]}`"
            )
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _main_async(args: argparse.Namespace) -> int:
    probes = _load_probes(
        from_pr3_json=Path(args.from_pr3_json) if args.from_pr3_json else None,
        ids=args.ids,
    )
    subject = _build_verification_subject()
    cases: list[dict[str, Any]] = []
    for index, probe in enumerate(probes):
        print(f"running {probe['id']}...", flush=True)
        case = await _run_probe(
            subject,
            probe,
            user_id=9200 + index,
            timeout_seconds=args.timeout_seconds,
        )
        cases.append(case)
        status = "ok" if case["ok"] else f"FAIL {case['error']}"
        print(f"  -> {status} ({case['elapsed_ms']}ms)", flush=True)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "verification_prompt_version": VERIFICATION_PROMPT_VERSION,
        "probe_count": len(cases),
        "ok_count": sum(1 for case in cases if case["ok"]),
        "cases": cases,
    }
    json_path = out_dir / f"pr4-free-fields-live-{stamp}.json"
    md_path = out_dir / f"pr4-free-fields-live-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(md_path, report)
    latest_json = out_dir / "pr4-free-fields-live-latest.json"
    latest_md = out_dir / "pr4-free-fields-live-latest.md"
    latest_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(f"ok {report['ok_count']}/{report['probe_count']}")
    return 0 if report["ok_count"] == report["probe_count"] else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(ROOT / "data" / "memory_eval" / "pr4-free-fields-live"),
        help="output directory for JSON/MD reports",
    )
    parser.add_argument(
        "--from-pr3-json",
        default=None,
        help="optional PR3 live JSON to reuse utterance texts",
    )
    parser.add_argument("--ids", default=None, help="comma-separated probe ids")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=180.0,
        help="per-probe extract+verify timeout",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
