"""Live PR3 free-field extraction probe.

Runs a curated set of utterances through the real LLM extraction path
(text_candidates_v5) and writes JSON + markdown reports.
"""

from __future__ import annotations

import argparse
import asyncio
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

from config import get_settings
from llm import LLMClient
from memory.extraction.pipeline import (
    LLMExtractionModel,
    apply_segment_post_processors,
    extraction_result_to_mapping,
)
from memory.extraction.prompts import PROMPT_VERSION
from memory.extraction.strategies import generate_segment_extraction_with_trace


PROBES: list[dict[str, Any]] = [
    {
        "id": "ru_pref_tea",
        "language": "ru",
        "segment_text": "Я предпочитаю зелёный чай.",
        "authority_class": "user_direct_statement",
        "source_type": "chat",
        "note": "classic preference",
    },
    {
        "id": "en_negation_nuts",
        "language": "en",
        "segment_text": "I don't like nuts at all.",
        "authority_class": "user_direct_statement",
        "source_type": "chat",
        "note": "negation / polarity",
    },
    {
        "id": "ru_uncertain_move",
        "language": "ru",
        "segment_text": "Возможно, я перееду в Берлин.",
        "authority_class": "user_direct_statement",
        "source_type": "chat",
        "note": "uncertainty + place",
    },
    {
        "id": "ru_hearsay",
        "language": "ru",
        "segment_text": "Коллега думает, что Иван уволился из Acme.",
        "authority_class": "user_direct_statement",
        "source_type": "chat",
        "note": "reported / hearsay",
    },
    {
        "id": "en_quote",
        "language": "en",
        "segment_text": 'Jordan said, "I hate flying."',
        "authority_class": "user_direct_statement",
        "source_type": "chat",
        "note": "quoted speech",
    },
    {
        "id": "ru_tutor_group",
        "language": "ru",
        "segment_text": "Запиши, что Маша из группы B2 пропускает занятие в пятницу.",
        "authority_class": "user_direct_statement",
        "source_type": "chat",
        "note": "tutoring / free labels expected",
    },
    {
        "id": "en_tutor_pref",
        "language": "en",
        "segment_text": "My student Alex prefers short homework with answer keys.",
        "authority_class": "user_direct_statement",
        "source_type": "chat",
        "note": "tutoring preference",
    },
    {
        "id": "ru_game_quest",
        "language": "ru",
        "segment_text": "Вчера в игре я закрыл квест Драконье ущелье и взял меч Огня.",
        "authority_class": "user_direct_statement",
        "source_type": "chat",
        "note": "game session / free schema_name",
    },
    {
        "id": "en_game_build",
        "language": "en",
        "segment_text": "My Warlock is level 42 and uses a Chaos build with Soulrift staff.",
        "authority_class": "user_direct_statement",
        "source_type": "chat",
        "note": "game character attributes",
    },
    {
        "id": "ru_question_abstain",
        "language": "ru",
        "segment_text": "Я люблю кофе?",
        "authority_class": "user_direct_statement",
        "source_type": "chat",
        "note": "question should abstain",
    },
    {
        "id": "en_tool_task",
        "language": "en",
        "segment_text": '{"task_id":"task_1","title":"Buy bread","status":"needsAction"}',
        "authority_class": "tool_api_result",
        "source_type": "tool",
        "note": "exact tool payload",
    },
    {
        "id": "ru_correction",
        "language": "ru",
        "segment_text": "Исправление: теперь я продакт-менеджер, а не дизайнер.",
        "authority_class": "user_direct_statement",
        "source_type": "chat",
        "note": "correction",
        "prior_segments": [{"segment_text": "Я дизайнер."}],
    },
]


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


def _candidate_summary(result_mapping: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in result_mapping.get("candidates") or []:
        rows.append(
            {
                "kind": candidate.get("kind"),
                "schema_name": candidate.get("schema_name"),
                "polarity": candidate.get("polarity"),
                "roles": [arg.get("role") for arg in candidate.get("arguments") or []],
                "epistemic_mode": (candidate.get("epistemic") or {}).get("mode"),
                "commitment": (candidate.get("epistemic") or {}).get("speaker_commitment"),
                "status": candidate.get("status"),
            }
        )
    return rows


async def _run_probe(model: LLMExtractionModel, probe: dict[str, Any], *, timezone: str) -> dict[str, Any]:
    segment_text = str(probe["segment_text"])
    occurred_at = datetime.now(UTC).isoformat()
    started = datetime.now(UTC)
    try:
        generated = await generate_segment_extraction_with_trace(
            model,
            segment_text=segment_text,
            source_type=str(probe.get("source_type") or "chat"),
            authority_class=str(probe.get("authority_class") or "user_direct_statement"),
            occurred_at=occurred_at,
            timezone=timezone,
            prior_segments=list(probe.get("prior_segments") or []),
        )
        processed = apply_segment_post_processors(
            generated.result,
            segment_text=segment_text,
            authority_class=str(probe.get("authority_class") or "user_direct_statement"),
            occurred_at=occurred_at,
            timezone=timezone,
            prior_segments=(),
        )
        parsed_mapping = extraction_result_to_mapping(generated.result)
        processed_mapping = extraction_result_to_mapping(processed)
        return {
            "id": probe["id"],
            "ok": True,
            "note": probe.get("note"),
            "language": probe.get("language"),
            "segment_text": segment_text,
            "authority_class": probe.get("authority_class"),
            "elapsed_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
            "parsed": parsed_mapping,
            "processed": processed_mapping,
            "summary": {
                "abstain": processed_mapping.get("abstain"),
                "mention_types": [
                    item.get("mention_type") for item in processed_mapping.get("mentions") or []
                ],
                "candidates": _candidate_summary(processed_mapping),
            },
            "trace": _to_json(generated.trace),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - probe should keep going
        return {
            "id": probe["id"],
            "ok": False,
            "note": probe.get("note"),
            "language": probe.get("language"),
            "segment_text": segment_text,
            "authority_class": probe.get("authority_class"),
            "elapsed_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
            "parsed": None,
            "processed": None,
            "summary": None,
            "trace": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines: list[str] = [
        f"# PR3 free-field live probe",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- prompt_version: `{report['prompt_version']}`",
        f"- model_profile: `{report['model_profile']}`",
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
        lines.append(f"- abstain: `{summary.get('abstain')}`")
        lines.append(f"- mention_types: `{summary.get('mention_types')}`")
        lines.append("- candidates:")
        for item in summary.get("candidates") or []:
            lines.append(
                "  - "
                f"kind=`{item.get('kind')}` "
                f"schema=`{item.get('schema_name')}` "
                f"polarity=`{item.get('polarity')}` "
                f"roles=`{item.get('roles')}` "
                f"mode=`{item.get('epistemic_mode')}`/"
                f"`{item.get('commitment')}`"
            )
        lines.append("")
        lines.append("<details><summary>processed JSON</summary>")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(case.get("processed"), ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
        lines.append("</details>")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    profile = args.profile or settings.memory_extraction_model_profile
    client = LLMClient(settings, profile=profile)
    model = LLMExtractionModel(
        client,
        model_profile=profile,
        max_tokens=settings.memory_extraction_max_tokens,
    )

    selected = PROBES
    if args.ids:
        wanted = {item.strip() for item in args.ids.split(",") if item.strip()}
        selected = [probe for probe in PROBES if probe["id"] in wanted]
        missing = sorted(wanted - {probe["id"] for probe in selected})
        if missing:
            raise SystemExit(f"unknown probe ids: {missing}")

    cases: list[dict[str, Any]] = []
    for probe in selected:
        print(f"running {probe['id']}...", flush=True)
        case = await _run_probe(model, probe, timezone=settings.bot_timezone)
        cases.append(case)
        status = "ok" if case["ok"] else f"FAIL {case['error']}"
        print(f"  -> {status} ({case['elapsed_ms']}ms)", flush=True)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "prompt_version": PROMPT_VERSION,
        "model_profile": profile,
        "probe_count": len(cases),
        "ok_count": sum(1 for case in cases if case["ok"]),
        "cases": cases,
    }
    json_path = out_dir / f"pr3-free-fields-live-{stamp}.json"
    md_path = out_dir / f"pr3-free-fields-live-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(md_path, report)
    latest_json = out_dir / "pr3-free-fields-live-latest.json"
    latest_md = out_dir / "pr3-free-fields-live-latest.md"
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
        default=str(ROOT / "data" / "memory_eval" / "pr3-free-fields-live"),
        help="output directory for JSON/MD reports",
    )
    parser.add_argument("--profile", default=None, help="override LLM profile")
    parser.add_argument("--ids", default=None, help="comma-separated probe ids")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
