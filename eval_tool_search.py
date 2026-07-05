"""Run tool search quality eval and print accuracy metrics."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv()

from eval_tool_search_benchmark import TOOL_SEARCH_BENCHMARK, ToolSearchCase
from tools.bootstrap import create_tool_runtime
from tools.runtime import ToolRuntime


@dataclass(frozen=True)
class CaseResult:
    case: ToolSearchCase
    names: tuple[str, ...]
    rank: int | None
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool


def _first_expected_rank(names: list[str], expected: tuple[str, ...]) -> int | None:
    for index, name in enumerate(names, start=1):
        if name in expected:
            return index
    return None


def _summarize(results: list[CaseResult]) -> dict[str, float | int]:
    total = len(results)
    if total == 0:
        return {"total": 0}

    def rate(flag: str) -> float:
        return sum(1 for item in results if getattr(item, flag)) / total * 100

    mrr_values = [1 / item.rank for item in results if item.rank is not None]
    return {
        "total": total,
        "hit_at_1_pct": rate("hit_at_1"),
        "hit_at_3_pct": rate("hit_at_3"),
        "hit_at_5_pct": rate("hit_at_5"),
        "mrr": sum(mrr_values) / total if total else 0.0,
        "misses": sum(1 for item in results if item.rank is None),
    }


async def _runtime_for_provider(provider: str) -> ToolRuntime:
    with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": provider}, clear=False):
        return await create_tool_runtime()


async def _eval_runtime(runtime: ToolRuntime, *, top_k: int = 5) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in TOOL_SEARCH_BENCHMARK:
        tag_list = list(case.tags) if case.tags else None
        payload = await runtime.search_tools(
            case.query,
            top_k=top_k,
            tags=tag_list,
            mode="rank",
        )
        names = tuple(tool["name"] for tool in payload.get("tools", []))
        rank = _first_expected_rank(list(names), case.expected)
        results.append(
            CaseResult(
                case=case,
                names=names,
                rank=rank,
                hit_at_1=rank == 1,
                hit_at_3=rank is not None and rank <= 3,
                hit_at_5=rank is not None and rank <= 5,
            )
        )
    return results


def _format_report(label: str, results: list[CaseResult], summary: dict[str, float | int]) -> str:
    lines = [
        f"## {label}",
        "",
        f"- Cases: **{summary['total']}**",
        f"- Hit@1: **{summary['hit_at_1_pct']:.1f}%**",
        f"- Hit@3: **{summary['hit_at_3_pct']:.1f}%**",
        f"- Hit@5: **{summary['hit_at_5_pct']:.1f}%**",
        f"- MRR: **{summary['mrr']:.3f}**",
        f"- Misses: **{summary['misses']}**",
        "",
        "### Failures",
    ]
    failures = [item for item in results if item.rank is None]
    if not failures:
        lines.append("_none_")
    else:
        for item in failures:
            tags = f" tags={list(item.case.tags)}" if item.case.tags else ""
            lines.append(
                f"- `{item.case.query}`{tags} -> expected `{item.case.expected}`; "
                f"got `{item.names}`"
            )

    weak = [item for item in results if item.rank is not None and item.rank > 1]
    if weak:
        lines.extend(["", "### Found but not rank 1"])
        for item in sorted(weak, key=lambda x: x.rank or 99):
            lines.append(
                f"- #{item.rank} `{item.case.query}` -> `{item.names[0]}` "
                f"(want one of `{item.case.expected}`)"
            )
    return "\n".join(lines)


async def run_eval(*, providers: tuple[str, ...] = ("api", "keyword"), top_k: int = 5) -> str:
    sections: list[str] = []
    for provider in providers:
        runtime = await _runtime_for_provider(provider)
        results = await _eval_runtime(runtime, top_k=top_k)
        summary = _summarize(results)
        sections.append(_format_report(f"Provider: {provider}", results, summary))
    return "\n\n".join(sections)


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate hybrid tool search accuracy")
    parser.add_argument(
        "--providers",
        default="api,keyword",
        help="Comma-separated: api, local, keyword",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Print raw per-case JSON")
    args = parser.parse_args()
    providers = tuple(part.strip() for part in args.providers.split(",") if part.strip())

    all_results: dict[str, list[CaseResult]] = {}
    for provider in providers:
        runtime = await _runtime_for_provider(provider)
        all_results[provider] = await _eval_runtime(runtime, top_k=args.top_k)

    if args.json:
        payload = {
            provider: [
                {
                    "query": item.case.query,
                    "tags": list(item.case.tags),
                    "expected": list(item.case.expected),
                    "got": list(item.names),
                    "rank": item.rank,
                }
                for item in results
            ]
            for provider, results in all_results.items()
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    sections = [
        _format_report(f"Provider: {provider}", results, _summarize(results))
        for provider, results in all_results.items()
    ]
    print("\n\n".join(sections))


if __name__ == "__main__":
    asyncio.run(_main())
