"""Fail if tool search benchmark regresses below configured thresholds."""
from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from eval_tool_search import _eval_runtime, _runtime_for_provider, _summarize


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Gate tool search benchmark quality")
    parser.add_argument("--providers", default="api")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-hit-at-1", type=float, default=97.0)
    parser.add_argument("--min-hit-at-5", type=float, default=100.0)
    parser.add_argument("--max-misses", type=int, default=0)
    args = parser.parse_args()

    providers = tuple(part.strip() for part in args.providers.split(",") if part.strip())
    failed = False

    for provider in providers:
        runtime = await _runtime_for_provider(provider)
        results = await _eval_runtime(runtime, top_k=args.top_k)
        summary = _summarize(results)
        hit1 = float(summary["hit_at_1_pct"])
        hit5 = float(summary["hit_at_5_pct"])
        misses = int(summary["misses"])

        print(
            f"[{provider}] cases={summary['total']} hit@1={hit1:.1f}% "
            f"hit@5={hit5:.1f}% mrr={summary['mrr']:.3f} misses={misses}"
        )

        if hit1 + 1e-9 < args.min_hit_at_1:
            print(f"FAIL [{provider}]: hit@1 {hit1:.1f}% < {args.min_hit_at_1}%")
            failed = True
        if hit5 < args.min_hit_at_5:
            print(f"FAIL [{provider}]: hit@5 {hit5:.1f}% < {args.min_hit_at_5}%")
            failed = True
        if misses > args.max_misses:
            print(f"FAIL [{provider}]: misses {misses} > {args.max_misses}")
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
