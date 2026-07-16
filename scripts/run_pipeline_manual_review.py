#!/usr/bin/env python3
"""Прогон пайплайна ingest→extract→verify→resolve и понятный отчёт для ручной проверки."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory.eval.runner import (
    _load_pack,
    _make_eval_context,
    _pack_fixtures,
    derive_case_seed,
    fixture_id,
    select_fixtures,
)
from memory.eval.subjects import create_subject


ROUTE_RU = {
    "ready_for_resolution": "готово — можно класть в память",
    "needs_confirmation": "нужно уточнение у пользователя",
    "insufficient": "мало данных / неуверенно",
    "contradicted": "противоречит тексту",
    "rejected": "отклонено",
    "proposed": "только извлечено, ещё не проверено",
    "superseded": "заменено более новой версией",
    "invalidated": "забыто / снято",
}

STATUS_RU = {
    "active": "активно",
    "provisional": "временно (не сливаем с другими)",
    "invalidated": "снято",
    "historical": "историческое",
    "unsupported": "без поддержки",
    "uncertain": "неопределённо",
    "durable": "можно считать устойчивым фактом",
    "deferred": "пока не уверен / отложено",
}

POLARITY_RU = {
    "positive": "да / утверждение",
    "negative": "нет / отрицание",
    "unknown": "неизвестно",
}


def _plain(value: Any) -> Any:
    if hasattr(value, "to_mapping"):
        return value.to_mapping()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _user_messages(case: Any) -> list[str]:
    rows: list[str] = []
    for event in getattr(case, "events", ()) or ():
        kind = str(getattr(event, "kind", "") or "")
        if kind != "chat_message":
            if kind == "tool_result":
                payload = getattr(event, "payload_json", None) or getattr(
                    event, "content", None
                )
                rows.append(f"[результат инструмента] {payload}")
            continue
        role = str(getattr(event, "role", "user") or "user")
        content = str(getattr(event, "content", "") or "").strip()
        if not content:
            continue
        prefix = "Пользователь" if role == "user" else role
        rows.append(f"{prefix}: {content}")
    return rows


def _arg_text(
    arguments: list[dict[str, Any]] | None,
    *,
    entity_labels: dict[str, str] | None = None,
) -> str:
    labels = entity_labels or {}
    parts: list[str] = []
    for item in arguments or []:
        role = str(item.get("role") or "?")
        if item.get("mention_ref"):
            value = f"@{item.get('mention_ref')}"
        elif item.get("entity_id"):
            eid = str(item.get("entity_id"))
            value = labels.get(eid, eid)
        elif item.get("entity_label"):
            value = str(item.get("entity_label"))
        elif item.get("has_literal") or item.get("literal") is not None:
            value = repr(item.get("literal"))
        else:
            value = json.dumps(item, ensure_ascii=False)
        parts.append(f"{role}={value}")
    return ", ".join(parts) if parts else "—"


def _mention_map(mentions: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for mention in mentions:
        mid = str(mention.get("mention_id") or "")
        surface = str(mention.get("surface_text") or mention.get("normalized_hint") or mid)
        mtype = str(mention.get("mention_type") or "")
        if mtype:
            out[mid] = f"«{surface}» ({mtype})"
        else:
            out[mid] = f"«{surface}»"
    return out


def _format_candidate(
    candidate: dict[str, Any],
    *,
    scores: dict[str, str],
    mentions: dict[str, str],
) -> list[str]:
    cid = str(candidate.get("candidate_ref") or candidate.get("candidate_id") or "")
    kind = str(candidate.get("kind") or "")
    schema = str(candidate.get("schema_name") or "")
    route = scores.get(cid) or str(candidate.get("verification_status") or "")
    route_ru = ROUTE_RU.get(route, route or "—")
    polarity = POLARITY_RU.get(str(candidate.get("polarity") or ""), str(candidate.get("polarity") or ""))
    args = candidate.get("arguments") or []
    pretty_args: list[str] = []
    for item in args:
        role = str(item.get("role") or "?")
        if item.get("mention_ref"):
            ref = str(item["mention_ref"])
            pretty_args.append(f"{role}: {mentions.get(ref, ref)}")
        else:
            pretty_args.append(f"{role}: {item.get('literal')!r}")
    lines = [
        f"- Тип: {kind}/{schema}",
        f"- Смысл аргументов: {'; '.join(pretty_args) if pretty_args else '—'}",
        f"- Полярность: {polarity}",
        f"- Решение проверки (PR4): **{route_ru}**",
    ]
    return lines


def _format_resolution(resolution: dict[str, Any] | None) -> list[str]:
    if not resolution:
        return ["- (PR5 не создал сущностей/утверждений — обычно кандидат не был ready)"]
    lines: list[str] = []
    entities = resolution.get("entities") or []
    assertions = resolution.get("assertions") or []
    beliefs = resolution.get("beliefs") or []
    entity_labels = {
        str(ent.get("entity_id")): str(
            ent.get("canonical_label") or ent.get("identity_key") or ent.get("entity_id")
        )
        for ent in entities
    }
    if entities:
        lines.append("Сущности:")
        for ent in entities:
            label = ent.get("canonical_label") or ent.get("identity_key")
            etype = ent.get("entity_type")
            status = STATUS_RU.get(str(ent.get("status") or ""), str(ent.get("status") or ""))
            lines.append(f"- {label} ({etype}) — {status}")
    else:
        lines.append("Сущности: нет")
    if assertions:
        lines.append("Утверждения в памяти:")
        for item in assertions:
            status = STATUS_RU.get(str(item.get("status") or ""), str(item.get("status") or ""))
            polarity = POLARITY_RU.get(
                str(item.get("polarity") or ""), str(item.get("polarity") or "")
            )
            lines.append(
                f"- {item.get('kind')}/{item.get('schema_name')}: "
                f"{_arg_text(item.get('resolved_arguments'), entity_labels=entity_labels)} "
                f"[{polarity}; {status}]"
            )
    else:
        lines.append("Утверждения в памяти: нет")
    if beliefs:
        lines.append("Belief (итог):")
        for item in beliefs:
            bstatus = STATUS_RU.get(
                str(item.get("belief_status") or ""), str(item.get("belief_status") or "")
            )
            utility = STATUS_RU.get(
                str(item.get("utility_class") or ""), str(item.get("utility_class") or "")
            )
            schema = ""
            raw_key = str(item.get("proposition_key") or "")
            start = raw_key.find("{")
            if start >= 0:
                try:
                    payload = json.loads(raw_key[start:])
                    schema = f"{payload.get('kind')}/{payload.get('schema_name')}"
                except Exception:  # noqa: BLE001
                    schema = ""
            label = schema or "факт"
            args = _arg_text(item.get("resolved_arguments"), entity_labels=entity_labels)
            lines.append(f"- {label}: {args} — статус={bstatus}, полезность={utility}")
    else:
        lines.append("Belief: нет")
    return lines


def _case_markdown(
    *,
    index: int,
    total: int,
    case: Any,
    output: dict[str, Any] | None,
    error: str | None,
    elapsed: float,
) -> str:
    title = str(getattr(case, "title", "") or fixture_id(case))
    fid = fixture_id(case)
    language = str(getattr(case, "language", "") or "")
    tags = ", ".join(getattr(case, "slice_tags", ()) or ())
    lines = [
        f"## {index}/{total}. {title}",
        "",
        f"- id: `{fid}`",
        f"- язык: {language or '—'}",
        f"- теги: {tags or '—'}",
        f"- время прогона: {elapsed:.1f}с",
        "",
        "### Что было в диалоге",
    ]
    messages = _user_messages(case)
    if messages:
        for msg in messages:
            lines.append(f"- {msg}")
    else:
        lines.append("- (нет chat-сообщений)")
    lines.append("")
    if error:
        lines.extend(
            [
                "### Результат",
                f"**Ошибка прогона:** {error}",
                "",
                "### Твоя оценка",
                "- [ ] перепрогнать",
                "- [ ] баг пайплайна",
                "",
            ]
        )
        return "\n".join(lines)

    assert output is not None
    mentions = list(output.get("mentions") or [])
    candidates = list(output.get("candidates") or [])
    scores = {
        str(row.get("candidate_id")): str(row.get("route_status") or "")
        for row in (output.get("candidate_scores") or [])
        if str(row.get("status") or "") == "active" or True
    }
    # Prefer active scores.
    active_scores = {
        str(row.get("candidate_id")): str(row.get("route_status") or "")
        for row in (output.get("candidate_scores") or [])
        if str(row.get("status") or "") == "active"
    }
    if active_scores:
        scores = active_scores
    mention_labels = _mention_map(mentions)
    resolution = (output.get("metadata") or {}).get("resolution")

    lines.append("### Кого/что нашли (упоминания)")
    if mentions:
        for mention in mentions:
            surface = mention.get("surface_text") or mention.get("normalized_hint")
            lines.append(
                f"- «{surface}» — тип `{mention.get('mention_type')}`"
            )
    else:
        lines.append("- нет")
    lines.append("")
    lines.append("### Что извлекли и как проверили")
    if candidates:
        for cand in candidates:
            lines.extend(_format_candidate(cand, scores=scores, mentions=mention_labels))
            lines.append("")
    else:
        lines.append("- кандидатов нет (абстенция / нечего извлекать)")
        lines.append("")
    lines.append("### Что положили в память (PR5)")
    lines.extend(_format_resolution(resolution if isinstance(resolution, dict) else None))
    lines.extend(
        [
            "",
            "### Твоя оценка",
            "- [ ] всё ок",
            "- [ ] ошибка извлечения",
            "- [ ] ошибка проверки",
            "- [ ] ошибка сущностей/памяти",
            "- комментарий:",
            "",
            "---",
            "",
        ]
    )
    return "\n".join(lines)


async def _run_case(
    subject: Any,
    case: Any,
    *,
    pack_hash: str,
    timeout: float,
) -> tuple[dict[str, Any] | None, str | None, float]:
    started = time.monotonic()
    context = _make_eval_context(
        case,
        seed=derive_case_seed(pack_hash, fixture_id(case)),
        allow_network=True,
        timeout_seconds=timeout,
        pack_hash=pack_hash,
        actual_dir=None,
    )
    try:
        output = await asyncio.wait_for(subject.run(case, context), timeout=timeout)
        return _plain(output), None, time.monotonic() - started
    except Exception as exc:  # noqa: BLE001 - report to human file
        return None, f"{type(exc).__name__}: {exc}", time.monotonic() - started


async def main_async(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", default="verification_v3")
    parser.add_argument("--tier", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Папка отчёта (по умолчанию data/memory_eval/pipeline_review_<ts>)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Ограничить число кейсов (0=все)")
    args = parser.parse_args(argv)

    if not args.output:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output = ROOT / "data" / "memory_eval" / f"pipeline_review_{stamp}"
    out_dir: Path = args.output
    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "MANUAL_REVIEW.md"
    raw_path = out_dir / "raw_cases.jsonl"

    pack = _load_pack(args.pack)
    fixtures = select_fixtures(
        _pack_fixtures(pack),
        tier=args.tier,
        case_ids=tuple(args.case),
        slice_tags=(),
        language=None,
        shard=None,
    )
    if args.limit and args.limit > 0:
        fixtures = fixtures[: args.limit]
    pack_hash = str(getattr(pack, "pack_hash", "") or args.pack)
    subject = create_subject("resolution", allow_network=True)

    header = [
        "# Ручная проверка памяти: сообщение → извлечение → проверка → сущности",
        "",
        f"- когда: {datetime.now(timezone.utc).isoformat()}",
        f"- пачка: `{args.pack}` / tier=`{args.tier}`",
        f"- кейсов: {len(fixtures)}",
        "- пайплайн: ingest → PR3 extract → PR4 verify → PR5 resolve (shadow)",
        "- это черновик для глаз: отметь галочки в каждом кейсе",
        "",
        "Легенда решений проверки:",
        "- **готово — можно класть в память** = ready_for_resolution",
        "- **нужно уточнение** = needs_confirmation",
        "- **мало данных** = insufficient",
        "- **противоречит / отклонено** = contradicted / rejected",
        "",
        "---",
        "",
    ]
    review_path.write_text("\n".join(header), encoding="utf-8")
    raw_path.write_text("", encoding="utf-8")

    ok = 0
    failed = 0
    for index, case in enumerate(fixtures, start=1):
        fid = fixture_id(case)
        print(f"[{index}/{len(fixtures)}] {fid} ...", flush=True)
        output, error, elapsed = await _run_case(
            subject,
            case,
            pack_hash=pack_hash,
            timeout=args.timeout_seconds,
        )
        if error:
            failed += 1
            print(f"  FAIL {error}", flush=True)
        else:
            ok += 1
            print(f"  ok ({elapsed:.1f}s)", flush=True)
        block = _case_markdown(
            index=index,
            total=len(fixtures),
            case=case,
            output=output,
            error=error,
            elapsed=elapsed,
        )
        with review_path.open("a", encoding="utf-8") as handle:
            handle.write(block)
        with raw_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "fixture_id": fid,
                        "error": error,
                        "elapsed_seconds": elapsed,
                        "output": output,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    summary = [
        "",
        "## Итог прогона",
        "",
        f"- успешно: {ok}",
        f"- с ошибкой: {failed}",
        f"- отчёт: `{review_path}`",
        f"- сырьё: `{raw_path}`",
        "",
    ]
    with review_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(summary))
    (out_dir / "summary.json").write_text(
        json.dumps(
            {
                "pack": args.pack,
                "tier": args.tier,
                "ok": ok,
                "failed": failed,
                "review_path": str(review_path),
                "raw_path": str(raw_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"DONE ok={ok} failed={failed} review={review_path}", flush=True)
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(main_async(argv))
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
