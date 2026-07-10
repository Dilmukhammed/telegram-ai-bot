"""Fail if chat memory E2E eval regresses below configured thresholds."""
from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from eval_chat_memory import format_report, run_eval


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Gate chat memory E2E eval quality")
    parser.add_argument("--min-overall-pass", type=float, default=80.0)
    parser.add_argument("--min-answer-pass", type=float, default=70.0)
    parser.add_argument("--min-tools-pass", type=float, default=70.0)
    parser.add_argument("--min-judge-pass", type=float, default=70.0)
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument(
        "--source",
        choices=("pack", "legacy"),
        default="pack",
    )
    parser.add_argument("--tier", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    results, summary = await run_eval(
        with_judge=not args.no_judge,
        source=args.source,
        tier=args.tier,
        limit=args.limit,
    )
    print(format_report(results, summary))

    failed = False
    checks = [
        ("overall_pass_pct", args.min_overall_pass, "overall"),
        ("answer_pass_pct", args.min_answer_pass, "answer"),
        ("tools_pass_pct", args.min_tools_pass, "tools"),
    ]
    if not args.no_judge:
        checks.append(("judge_pass_pct", args.min_judge_pass, "judge"))

    for key, threshold, label in checks:
        value = float(summary[key])
        print(f"[gate] {label}={value:.1f}% (min {threshold:.1f}%)")
        if value + 1e-9 < threshold:
            print(f"FAIL: {label} {value:.1f}% < {threshold:.1f}%")
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
