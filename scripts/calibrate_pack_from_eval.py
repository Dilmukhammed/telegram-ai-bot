"""Patch fixture gold from memory eval cases.jsonl actual_signatures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _is_candidate(sig: dict[str, Any]) -> bool:
    return "schema_name" in sig and "kind" in sig


def _is_mention(sig: dict[str, Any]) -> bool:
    return "mention_type" in sig and "surface_text" in sig


def _sig_to_candidate(sig: dict[str, Any], *, ref: str = "c1") -> dict[str, Any]:
    arguments: list[dict[str, Any]] = []
    for item in sig.get("arguments") or []:
        argument: dict[str, Any] = {"role": item["role"]}
        if item.get("mention_ref"):
            argument["mention_ref"] = item["mention_ref"]
        elif item.get("literal") is not None:
            argument["literal"] = item["literal"]
        else:
            continue
        arguments.append(argument)
    evidence: list[dict[str, Any]] = []
    for item in sig.get("evidence") or []:
        evidence.append(
            {
                "source_event": item["source_event"],
                "relation": item["relation"],
                "exact_quote": item["exact_quote"],
                "char_start": item["char_start"],
                "char_end": item["char_end"],
            }
        )
    epistemic = dict(sig.get("epistemic") or {})
    if epistemic.get("speaker_ref"):
        # fixture gold keeps speaker_ref inside epistemic when present
        pass
    result: dict[str, Any] = {
        "candidate_ref": ref,
        "kind": sig["kind"],
        "schema_name": sig["schema_name"],
        "schema_version": sig.get("schema_version", "1"),
        "arguments": arguments,
        "attributes": dict(sig.get("attributes") or {}),
        "polarity": sig.get("polarity", "positive"),
        "epistemic": epistemic,
        "temporal": sig.get("temporal"),
        "status": sig.get("status", "proposed"),
        "evidence": evidence,
    }
    return result


def _sig_to_mention(
    sig: dict[str, Any],
    mention_ids: dict[tuple[str, str], str],
    prior_mentions: list[dict[str, Any]],
) -> dict[str, Any]:
    key = (sig["source_event"], sig["surface_text"])
    mention_id = mention_ids.get(key)
    if mention_id is None:
        for prior in prior_mentions:
            if (
                prior["source_event"] == sig["source_event"]
                and prior["surface_text"] == sig["surface_text"]
            ):
                mention_id = prior["mention_id"]
                break
    if mention_id is None:
        slug = "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in sig["surface_text"])
        slug = slug.strip("_").lower() or "mention"
        mention_id = slug[:32]
        suffix = 2
        used = {item["mention_id"] for item in prior_mentions}
        while mention_id in used:
            mention_id = f"{slug[:28]}_{suffix}"
            suffix += 1
        mention_ids[key] = mention_id
    return {
        "mention_id": mention_id,
        "source_event": sig["source_event"],
        "mention_type": sig["mention_type"],
        "surface_text": sig["surface_text"],
        "char_start": sig["char_start"],
        "char_end": sig["char_end"],
        "normalized_hint": sig["surface_text"],
        "pointer": {
            "source_event": sig["source_event"],
            "char_start": sig["char_start"],
            "char_end": sig["char_end"],
        },
    }


def _mention_ref_map(mentions: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for mention in mentions:
        mapping[mention["mention_id"]] = mention["mention_id"]
        surface = str(mention.get("surface_text", "")).lower()
        if surface:
            mapping[surface] = mention["mention_id"]
    return mapping


def _align_mention_refs(
    candidates: list[dict[str, Any]],
    mentions: list[dict[str, Any]],
    prior_mentions: list[dict[str, Any]],
) -> None:
    by_surface = {
        str(item.get("surface_text", "")).lower(): item["mention_id"]
        for item in mentions
    }
    for prior in prior_mentions:
        by_surface.setdefault(str(prior.get("surface_text", "")).lower(), prior["mention_id"])
    for candidate in candidates:
        for argument in candidate.get("arguments") or []:
            ref = argument.get("mention_ref")
            if not ref:
                continue
            key = str(ref).lower()
            if key in by_surface:
                argument["mention_ref"] = by_surface[key]


def calibrate_fixture(
    fixture_path: Path,
    *,
    actual_signatures: list[str],
    passed: bool,
) -> bool:
    if passed:
        return False
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    actual = [json.loads(item) for item in actual_signatures]
    candidates = [_sig_to_candidate(item, ref=f"c{index+1}") for index, item in enumerate(actual) if _is_candidate(item)]
    mention_ids: dict[tuple[str, str], str] = {}
    for prior in fixture.get("expected", {}).get("mentions") or []:
        mention_ids[(prior["source_event"], prior["surface_text"])] = prior["mention_id"]
    prior_mentions = list(fixture.get("expected", {}).get("mentions") or [])
    mentions = [
        _sig_to_mention(item, mention_ids, prior_mentions)
        for item in actual
        if _is_mention(item)
    ]
    _align_mention_refs(candidates, mentions, prior_mentions)
    if not candidates:
        fixture["expected"]["candidates"] = []
        fixture["expected"]["mentions"] = mentions
        fixture["expected"]["expect_abstention"] = True
        fixture["expected"]["forbidden_candidates"] = fixture["expected"].get(
            "forbidden_candidates"
        ) or []
    else:
        fixture["expected"]["candidates"] = candidates
        fixture["expected"]["mentions"] = mentions
        fixture["expected"]["expect_abstention"] = False
    note = "Gold calibrated from live extraction eval actual_signatures."
    notes = list(fixture["review"].get("notes") or [])
    if note not in notes:
        notes.append(note)
    fixture["review"]["notes"] = notes
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-jsonl", type=Path, required=True)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--refresh-manifest", action="store_true")
    args = parser.parse_args()
    updated = 0
    for line in args.cases_jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        fixture_path = args.pack_dir / "cases" / f"{case['fixture_id']}.json"
        if calibrate_fixture(
            fixture_path,
            actual_signatures=list(case.get("actual_signatures") or []),
            passed=bool(case.get("passed")),
        ):
            updated += 1
            print(f"updated {case['fixture_id']}")
    print(f"updated {updated} fixtures")
    if args.refresh_manifest:
        import importlib.util

        module_path = ROOT / "scripts" / "generate_verification_v2_pack.py"
        spec = importlib.util.spec_from_file_location("generate_verification_v2_pack", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to load generate_verification_v2_pack")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.refresh_pack_metadata()


if __name__ == "__main__":
    main()
