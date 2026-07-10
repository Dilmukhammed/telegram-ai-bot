"""Run Thorough system Phase 1: three parallel planners -> PhasePlan YAML."""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from config import get_settings
from thorough.llm_call import complete_plan_yaml
from thorough.prompts import PLANNER_LABELS, planner_system_prompt

PHASE1_PROFILES = (
    "thorough_planner_unit",
    "thorough_planner_surface",
    "thorough_planner_hot",
)


async def _complete_planner(profile: str, user_request: str) -> tuple[str, str, str]:
    settings = get_settings()
    label = PLANNER_LABELS[profile]

    async def on_retry(attempt: int, next_timeout: float) -> None:
        print(
            f"[phase1] {label} slow (>{settings.llm_request_timeouts[attempt - 1]:.0f}s), "
            f"retry {attempt + 1} with {next_timeout:.0f}s timeout",
            flush=True,
        )

    model, _raw, yaml_body = await complete_plan_yaml(
        settings,
        profile=profile,
        label=label,
        messages=[
            {"role": "system", "content": planner_system_prompt(profile)},
            {"role": "user", "content": user_request},
        ],
        max_tokens=settings.thorough_planner_max_output_tokens,
        root="phase_plan",
        operation="phase1",
        on_retry=on_retry,
    )
    return label, model, yaml_body


async def run_phase1(user_request: str, *, out_dir: Path) -> Path:
    import time

    started = time.perf_counter()
    print("[phase1] launching 3 planners in parallel...", flush=True)
    raw_results = await asyncio.gather(
        *[_complete_planner(profile, user_request) for profile in PHASE1_PROFILES],
        return_exceptions=True,
    )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / f"phase1_{stamp}.md"

    parts = [f"# Thorough Phase 1 — {stamp}\n", "## User request\n", user_request, "\n"]
    errors: list[str] = []
    for item in raw_results:
        if isinstance(item, BaseException):
            errors.append(f"{type(item).__name__}: {item}")
            parts.extend(["\n---\n\n## ERROR\n\n", str(item), "\n"])
            continue
        label, model, yaml_body = item
        parts.extend([f"\n---\n\n## {label} (`{model}`)\n\n", yaml_body, "\n"])
        single = out_dir / f"phase1_{stamp}_{label}.yaml"
        single.write_text(yaml_body, encoding="utf-8")

    bundle.write_text("".join(parts), encoding="utf-8")
    print(
        f"[phase1] finished in {time.perf_counter() - started:.1f}s -> {bundle}",
        flush=True,
    )
    if errors:
        raise RuntimeError("Some planners failed:\n" + "\n".join(errors))
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Thorough Phase 1 planners in parallel")
    parser.add_argument("request", nargs="?", help="User task (or use --request-file / stdin)")
    parser.add_argument(
        "--request-file",
        type=Path,
        help="Read user task from UTF-8 file (preferred on Windows)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/thorough_runs"),
        help="Output directory (default data/thorough_runs)",
    )
    args = parser.parse_args()

    if args.request_file:
        user_request = args.request_file.read_text(encoding="utf-8").strip()
    elif args.request:
        user_request = args.request
    elif not sys.stdin.isatty():
        user_request = sys.stdin.read().strip()
    else:
        parser.error("provide request as argument, --request-file, or via stdin")

    bundle = asyncio.run(run_phase1(user_request, out_dir=args.out_dir))
    print(bundle)


if __name__ == "__main__":
    main()
