#!/usr/bin/env python3
"""Offline hard-gate smoke for resolution_v1 (deterministic, no network)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.eval.resolution_expectations import (
    check_hard_gates,
    load_resolution_expectations,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack",
        default=None,
        help="Optional path to resolution expectation JSON (default: resolution_v1)",
    )
    args = parser.parse_args(argv)
    pack = (
        load_resolution_expectations(args.pack)
        if args.pack
        else load_resolution_expectations()
    )
    failures = check_hard_gates(
        eligible_assertion_recall=1.0,
        non_ready_consumed=0,
        false_person_merge=0,
        cross_user_leakage=0,
        critic_forbidden_merge=0,
        active_belief_without_support=0,
        graph_writes=0,
        gates=pack.hard_gates,
    )
    print(
        f"pack={pack.pack_id} reviewed={pack.reviewed} "
        f"cases={len(pack.cases)} hard_gate_failures={failures}"
    )
    if failures:
        return 1
    if pack.reviewed is False:
        print("note: pack is draft until human review sign-off")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
