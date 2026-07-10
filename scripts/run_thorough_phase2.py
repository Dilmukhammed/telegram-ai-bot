"""Run Thorough system Phase 2: merge three PhasePlans -> MasterPhasePlan YAML."""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from config import get_settings
from thorough.bundle import parse_phase1_bundle
from thorough.llm_call import complete_plan_yaml
from thorough.output import extract_plan_yaml
from thorough.prompts import planner_system_prompt

COLLAPSE_BRIEF = """\
Worker context collapse (execution must respect this):
- Tool results >~150 chars archive; full JSON hot ~10 worker turns then stub+summary.
- Persist facts to sheet/doc before raw search/fetch goes cold.
- Hot window: ~8-10 worker turns per heavy batch without external persist is risky.
"""


def _merge_user_message(user_request: str, plans: dict[str, tuple[str, str]]) -> str:
    blocks = ["# User request\n", user_request, "\n\n# Collapse brief\n", COLLAPSE_BRIEF]
    for label in ("P1_unit", "P2_surface", "P3_hot"):
        model, body = plans[label]
        yaml_body = extract_plan_yaml(body, root="phase_plan") or body.strip()
        blocks.extend([f"\n\n# PhasePlan — {label} (`{model}`)\n\n", yaml_body])
    return "".join(blocks)


async def run_phase2(phase1_bundle: Path, *, out_dir: Path) -> Path:
    user_request, plans = parse_phase1_bundle(phase1_bundle)
    missing = [label for label in ("P1_unit", "P2_surface", "P3_hot") if label not in plans]
    if missing:
        raise RuntimeError(f"Phase 1 bundle missing sections: {', '.join(missing)}")

    settings = get_settings()

    async def on_retry(attempt: int, next_timeout: float) -> None:
        print(
            f"[phase2] merger slow (>{settings.llm_request_timeouts[attempt - 1]:.0f}s), "
            f"retry {attempt + 1} with {next_timeout:.0f}s timeout",
            flush=True,
        )

    model, _raw, yaml_body = await complete_plan_yaml(
        settings,
        profile="thorough_merger",
        label="M_merger",
        messages=[
            {"role": "system", "content": planner_system_prompt("thorough_merger")},
            {"role": "user", "content": _merge_user_message(user_request, plans)},
        ],
        max_tokens=settings.thorough_merger_max_output_tokens,
        root="master_phase_plan",
        operation="phase2",
        on_retry=on_retry,
    )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / f"phase2_{stamp}.md"
    yaml_path = out_dir / f"phase2_{stamp}_master.yaml"

    parts = [
        f"# Thorough Phase 2 — {stamp}\n",
        f"Source phase1: `{phase1_bundle}`\n\n",
        "## User request\n",
        user_request,
        "\n\n---\n\n",
        f"## MasterPhasePlan (`{model}`)\n\n",
        yaml_body,
        "\n",
    ]
    bundle.write_text("".join(parts), encoding="utf-8")
    yaml_path.write_text(yaml_body, encoding="utf-8")
    print(f"[phase2] -> {bundle}", flush=True)
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Thorough Phase 2 merger")
    parser.add_argument(
        "phase1_bundle",
        type=Path,
        help="Path to phase1_*.md bundle from run_thorough_phase1.py",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/thorough_runs"),
        help="Output directory (default data/thorough_runs)",
    )
    args = parser.parse_args()

    if not args.phase1_bundle.is_file():
        parser.error(f"phase1 bundle not found: {args.phase1_bundle}")

    bundle = asyncio.run(run_phase2(args.phase1_bundle, out_dir=args.out_dir))
    print(bundle)


if __name__ == "__main__":
    main()
