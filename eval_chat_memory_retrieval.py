"""Deterministic retrieval-only benchmark for chat memory search."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import dataclass
from unittest.mock import patch

from bot.chat_index.search import (
    reset_chat_search_embedding_provider,
    search_chat_chunks,
)
from eval_chat_memory_benchmark import CHAT_MEMORY_BENCHMARK, MemoryEvalScenario
from eval_chat_memory_fixture import FAKE_USER, fresh_fixture
from eval_memory_corpus.adapter import load_default_pack, scenarios_from_pack
from eval_memory_corpus.schema import DEFAULT_PACK_PATH


# Legacy hand-written suite (kept for --source legacy).
RETRIEVAL_BENCHMARK = tuple(
    scenario
    for scenario in CHAT_MEMORY_BENCHMARK
    if scenario.case.id != "archived_session_overview"
)

_SKIP_DIFFICULTIES = frozenset({"overview", "world"})


@dataclass(frozen=True)
class RetrievalCaseResult:
    case_id: str
    rank: int | None
    expected_session_id: str | None
    session_match: bool
    expected_tool_ref: int | None
    tool_ref_match: bool
    hit_session_ids: tuple[str, ...]

    @property
    def hit_at_1(self) -> bool:
        return self.rank is not None and self.rank <= 1

    @property
    def hit_at_3(self) -> bool:
        return self.rank is not None and self.rank <= 3

    @property
    def hit_at_5(self) -> bool:
        return self.rank is not None and self.rank <= 5


def _normalized(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())


def _term_matches(term: str, text: str) -> bool:
    term_norm = _normalized(term)
    text_norm = _normalized(text)
    if term_norm and term_norm in text_norm:
        return True
    if "_" in term:
        suffix = _normalized(term.rsplit("_", 1)[-1])
        return bool(suffix and suffix in text_norm)
    return False


def _hit_text(hit: dict) -> str:
    return "\n".join(
        part
        for part in (
            str(hit.get("text") or ""),
            str(hit.get("turn_context") or ""),
            str(hit.get("session_summary") or ""),
        )
        if part
    )


def _case_rank(
    scenario: MemoryEvalScenario,
    hits: list[dict],
    *,
    expected_session_id: str | None,
    expected_tool_ref: int | None,
) -> int | None:
    required_terms = scenario.case.must_include
    term_ranks: list[int] = []
    for term in required_terms:
        rank = next(
            (
                index
                for index, hit in enumerate(hits, start=1)
                if (not expected_session_id or hit.get("session_id") == expected_session_id)
                and _term_matches(term, _hit_text(hit))
            ),
            None,
        )
        if rank is None:
            return None
        term_ranks.append(rank)

    if expected_tool_ref is not None:
        ref_rank = next(
            (
                index
                for index, hit in enumerate(hits, start=1)
                if hit.get("tool_ref") == expected_tool_ref
            ),
            None,
        )
        if ref_rank is None:
            return None
        term_ranks.append(ref_rank)
    return max(term_ranks, default=None)


def _parse_shard(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    left, right = raw.split("/", 1)
    index = int(left)
    total = int(right)
    if total < 1 or index < 0 or index >= total:
        raise ValueError("--shard must look like 0/8")
    return index, total


def _select_scenarios(
    *,
    source: str,
    tier: str,
    limit: int | None,
    shard: tuple[int, int] | None,
) -> list[MemoryEvalScenario]:
    if source == "legacy":
        scenarios = list(RETRIEVAL_BENCHMARK)
        if shard is not None:
            index, total = shard
            scenarios = [item for i, item in enumerate(scenarios) if i % total == index]
        if limit is not None:
            scenarios = scenarios[:limit]
        return scenarios

    pack = load_default_pack()
    # Exclude overview/world — not retrieval-oracle friendly / too expensive to seed.
    pack_cases = [
        case
        for case in pack.cases_for_tier(tier)  # type: ignore[arg-type]
        if case.difficulty not in _SKIP_DIFFICULTIES and not case.world_seed
    ]
    if shard is not None:
        index, total = shard
        pack_cases = [case for i, case in enumerate(pack_cases) if i % total == index]
    if limit is not None:
        pack_cases = pack_cases[: max(0, limit)]
    # Rebuild a tiny pack-like filter via scenarios_from_pack by id order:
    # scenarios_from_pack already filters tier; we map selected case ids.
    selected_ids = {case.id for case in pack_cases}
    scenarios = scenarios_from_pack(pack, tier=tier, limit=None, shard=None)
    scenarios = [item for item in scenarios if item.case.id in selected_ids]
    # Preserve pack_cases order
    by_id = {item.case.id: item for item in scenarios}
    return [by_id[case.id] for case in pack_cases if case.id in by_id]


async def evaluate_provider(
    provider: str,
    *,
    top_k: int = 5,
    source: str = "pack",
    tier: str = "full",
    limit: int | None = None,
    shard: tuple[int, int] | None = None,
) -> list[RetrievalCaseResult]:
    env = {
        "CHAT_DB_PATH": ":memory:",
        "TOOL_RESULT_DB_PATH": ":memory:",
        "TOOL_EMBEDDING_PROVIDER": provider,
        "CHAT_INDEX_ON_STARTUP": "0",
    }
    scenarios = _select_scenarios(source=source, tier=tier, limit=limit, shard=shard)
    results: list[RetrievalCaseResult] = []
    with patch.dict(os.environ, env, clear=False):
        reset_chat_search_embedding_provider()
        for scenario in scenarios:
            fixture = fresh_fixture()
            seed_info = await scenario.seed(fixture)
            expected_session_id = seed_info.get("archived_session_id")
            expected_tool_ref = seed_info.get("tool_ref")
            hits = await search_chat_chunks(
                FAKE_USER,
                scenario.case.question,
                top_k=top_k,
            )
            rank = _case_rank(
                scenario,
                hits,
                expected_session_id=expected_session_id,
                expected_tool_ref=expected_tool_ref,
            )
            relevant = [
                hit
                for hit in hits
                if any(_term_matches(term, _hit_text(hit)) for term in scenario.case.must_include)
            ]
            session_match = bool(
                expected_session_id
                and any(hit.get("session_id") == expected_session_id for hit in relevant)
            )
            tool_ref_match = (
                expected_tool_ref is None
                or any(hit.get("tool_ref") == expected_tool_ref for hit in hits)
            )
            results.append(
                RetrievalCaseResult(
                    case_id=scenario.case.id,
                    rank=rank,
                    expected_session_id=expected_session_id,
                    session_match=session_match,
                    expected_tool_ref=expected_tool_ref,
                    tool_ref_match=tool_ref_match,
                    hit_session_ids=tuple(str(hit.get("session_id") or "") for hit in hits),
                )
            )
        reset_chat_search_embedding_provider()
    return results


def summarize(results: list[RetrievalCaseResult]) -> dict[str, float | int]:
    total = len(results)
    if not total:
        return {"total": 0}

    def pct(predicate) -> float:
        return sum(1 for item in results if predicate(item)) / total * 100

    ref_cases = [item for item in results if item.expected_tool_ref is not None]

    return {
        "total": total,
        "recall_at_1_pct": pct(lambda item: item.hit_at_1),
        "recall_at_3_pct": pct(lambda item: item.hit_at_3),
        "recall_at_5_pct": pct(lambda item: item.hit_at_5),
        "mrr": sum(1.0 / item.rank for item in results if item.rank) / total,
        "session_recall_pct": pct(lambda item: item.session_match),
        "tool_ref_recall_pct": (
            sum(1 for item in ref_cases if item.tool_ref_match) / len(ref_cases) * 100
            if ref_cases
            else 100.0
        ),
        "misses": sum(1 for item in results if item.rank is None),
    }


def format_report(provider: str, results: list[RetrievalCaseResult]) -> str:
    metrics = summarize(results)
    lines = [
        f"## Chat memory retrieval: {provider}",
        "",
        f"- Cases: **{metrics['total']}**",
        f"- Recall@1: **{metrics['recall_at_1_pct']:.1f}%**",
        f"- Recall@3: **{metrics['recall_at_3_pct']:.1f}%**",
        f"- Recall@5: **{metrics['recall_at_5_pct']:.1f}%**",
        f"- MRR: **{metrics['mrr']:.3f}**",
        f"- Session recall: **{metrics['session_recall_pct']:.1f}%**",
        f"- Tool-ref recall: **{metrics['tool_ref_recall_pct']:.1f}%**",
        f"- Misses: **{metrics['misses']}**",
        "",
        "### Misses",
    ]
    misses = [item for item in results if item.rank is None]
    if not misses:
        lines.append("_none_")
    else:
        for item in misses[:40]:
            lines.append(
                f"- `{item.case_id}` expected_session={item.expected_session_id} "
                f"expected_ref={item.expected_tool_ref}"
            )
        if len(misses) > 40:
            lines.append(f"- … and {len(misses) - 40} more")
    return "\n".join(lines)


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate chat-memory retrieval only")
    parser.add_argument("--providers", default="keyword")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--source",
        choices=("pack", "legacy"),
        default="pack",
        help="Case source: generated pack (default) or legacy benchmark",
    )
    parser.add_argument(
        "--tier",
        choices=("smoke", "full"),
        default="full",
        help="Pack tier (ignored for --source legacy)",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--shard", type=str, default=None, help="Shard like 0/8")
    args = parser.parse_args()
    providers = tuple(part.strip() for part in args.providers.split(",") if part.strip())
    shard = _parse_shard(args.shard)

    all_results = {
        provider: await evaluate_provider(
            provider,
            top_k=args.top_k,
            source=args.source,
            tier=args.tier,
            limit=args.limit,
            shard=shard,
        )
        for provider in providers
    }
    if args.json:
        print(
            json.dumps(
                {
                    "pack": str(DEFAULT_PACK_PATH),
                    "results": {
                        provider: {
                            "summary": summarize(results),
                            "cases": [
                                {
                                    "id": item.case_id,
                                    "rank": item.rank,
                                    "session_match": item.session_match,
                                    "tool_ref_match": item.tool_ref_match,
                                }
                                for item in results
                            ],
                        }
                        for provider, results in all_results.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(
        "\n\n".join(
            format_report(provider, results)
            for provider, results in all_results.items()
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
