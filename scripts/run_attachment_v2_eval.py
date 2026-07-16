from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def run_eval(
    pack_path: Path,
    *,
    runs: int,
    output: Path,
    case_ids: set[str] | None = None,
) -> dict[str, Any]:
    from config import get_settings
    from llm import LLMClient
    from memory.attachment.critics import (
        LLMAttachmentCommitteeModel,
        accepted_hypotheses_from_critics,
        run_hypothesis_layer,
        run_set_critic,
    )
    from memory.attachment.hypotheses import (
        filter_policy_compatible_hypotheses,
        merge_hypothesis_sources,
        seed_hypotheses_from_shortlist,
        select_compatible_hypotheses,
    )
    from memory.attachment.schemas import ShortlistCandidate

    payload = json.loads(pack_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1" or not isinstance(payload.get("cases"), list):
        raise ValueError("invalid attachment v2 eval pack")
    settings = get_settings()
    max_tokens = max(4096, settings.memory_attachment_max_tokens)
    generator = LLMAttachmentCommitteeModel(
        LLMClient(settings, profile=settings.memory_attachment_model_profile),
        model_profile=settings.memory_attachment_model_profile,
        max_tokens=max_tokens,
    )
    support_model = LLMAttachmentCommitteeModel(
        LLMClient(settings, profile=settings.memory_attachment_support_model_profile),
        model_profile=settings.memory_attachment_support_model_profile,
        max_tokens=max_tokens,
    )
    adversarial_model = LLMAttachmentCommitteeModel(
        LLMClient(settings, profile=settings.memory_attachment_adversarial_model_profile),
        model_profile=settings.memory_attachment_adversarial_model_profile,
        max_tokens=max_tokens,
    )

    records: list[dict[str, Any]] = []
    for run_index in range(1, runs + 1):
        for case in payload["cases"]:
            if case_ids and str(case.get("case_id")) not in case_ids:
                continue
            shortlist = tuple(ShortlistCandidate(**item) for item in case["shortlist"])
            hypotheses, generation_layer, calls = await run_hypothesis_layer(
                generator,
                context_statement=str(case["statement"]),
                shortlist=shortlist,
                attach_domains=tuple(str(value) for value in case["domains"]),
                context_pack=dict(case.get("context") or {}),
            )
            hypotheses = filter_policy_compatible_hypotheses(
                hypotheses,
                shortlist=shortlist,
                attach_domains=tuple(str(value) for value in case["domains"]),
            )
            combined = merge_hypothesis_sources(
                seed_hypotheses_from_shortlist(shortlist), hypotheses
            )
            combined = filter_policy_compatible_hypotheses(
                combined,
                shortlist=shortlist,
                attach_domains=tuple(str(value) for value in case["domains"]),
            )
            proposed = select_compatible_hypotheses(combined, max_items=3)
            support, support_calls = await run_set_critic(
                support_model,
                layer="L5",
                hypotheses=proposed,
                context_statement=str(case["statement"]),
                context_pack=dict(case.get("context") or {}),
                adversarial=False,
            )
            adversarial, adversarial_calls = await run_set_critic(
                adversarial_model,
                layer="L6",
                hypotheses=proposed,
                context_statement=str(case["statement"]),
                context_pack=dict(case.get("context") or {}),
                adversarial=True,
            )
            accepted = accepted_hypotheses_from_critics(
                proposed, support=support, adversarial=adversarial, shortlist=shortlist
            )
            constrained_targets = {
                str(item.get("target"))
                for item in (case.get("context") or {}).get("constraints", [])
                if isinstance(item, dict) and item.get("type") == "negative_preference"
            }
            accepted = tuple(
                item for item in accepted
                if not (item.op == "inferred_preference" and item.target_id in constrained_targets)
            )
            actual = {(item.op, item.target_id) for item in accepted}
            required = {tuple(item) for item in case.get("required", [])}
            forbidden = {tuple(item) for item in case.get("forbidden", [])}
            missing = sorted(required - actual)
            forbidden_present = sorted(forbidden & actual)
            passed = not missing and not forbidden_present
            records.append(
                {
                    "run": run_index,
                    "case_id": case["case_id"],
                    "passed": passed,
                    "missing": missing,
                    "forbidden_present": forbidden_present,
                    "proposed": [asdict(item) for item in proposed],
                    "accepted": [asdict(item) for item in accepted],
                    "generation_layer": asdict(generation_layer),
                    "support": {f"{op}:{target}": asdict(value) for (op, target), value in support.items()},
                    "adversarial": {f"{op}:{target}": asdict(value) for (op, target), value in adversarial.items()},
                    "llm_calls": calls + support_calls + adversarial_calls,
                }
            )
    passed = sum(1 for record in records if record["passed"])
    total = len(records)
    per_case: dict[str, list[bool]] = {}
    for record in records:
        per_case.setdefault(str(record["case_id"]), []).append(bool(record["passed"]))
    stable_cases = sum(1 for values in per_case.values() if all(values))
    report = {
        "schema_version": "1",
        "pack_id": payload.get("pack_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runs": runs,
        "passed": passed,
        "total": total,
        "quality": passed / total if total else 0.0,
        "stable_cases": stable_cases,
        "case_count": len(per_case),
        "records": records,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def rescore_report(pack_path: Path, captured_path: Path, *, output: Path) -> dict[str, Any]:
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    captured = json.loads(captured_path.read_text(encoding="utf-8"))
    expected = {str(case["case_id"]): case for case in pack["cases"]}
    records = list(captured.get("records") or [])
    for record in records:
        case = expected[str(record["case_id"])]
        actual = {
            (str(item["op"]), str(item["target_id"]))
            for item in record.get("accepted") or []
        }
        required = {tuple(item) for item in case.get("required", [])}
        forbidden = {tuple(item) for item in case.get("forbidden", [])}
        record["missing"] = [list(item) for item in sorted(required - actual)]
        record["forbidden_present"] = [list(item) for item in sorted(forbidden & actual)]
        record["passed"] = not record["missing"] and not record["forbidden_present"]
    passed = sum(1 for record in records if record["passed"])
    per_case: dict[str, list[bool]] = {}
    for record in records:
        per_case.setdefault(str(record["case_id"]), []).append(bool(record["passed"]))
    rescored = {
        **captured,
        "rescored_at": datetime.now(timezone.utc).isoformat(),
        "rescored_from": str(captured_path),
        "passed": passed,
        "total": len(records),
        "quality": passed / len(records) if records else 0.0,
        "stable_cases": sum(1 for values in per_case.values() if all(values)),
        "case_count": len(per_case),
        "records": records,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(rescored, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rescored


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PR14 v2 live semantic committee eval")
    parser.add_argument("--pack", type=Path, default=ROOT / "data/memory_corpus/attachment_v2_live_eval.json")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--case", action="append", default=[], dest="case_ids")
    parser.add_argument("--captured-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.captured_report:
        report = rescore_report(args.pack, args.captured_report, output=args.output)
        status = "PASS" if report["passed"] == report["total"] else "FAIL"
        print(f"{status} ({report['passed']}/{report['total']}); reports: {args.output}")
        return
    if not args.allow_network:
        raise SystemExit("live attachment eval requires --allow-network")
    report = asyncio.run(
        run_eval(
            args.pack,
            runs=max(1, args.runs),
            output=args.output,
            case_ids=set(args.case_ids) or None,
        )
    )
    status = "PASS" if report["passed"] == report["total"] else "FAIL"
    print(f"{status} ({report['passed']}/{report['total']}); reports: {args.output}")


if __name__ == "__main__":
    main()
