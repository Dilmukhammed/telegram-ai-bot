"""Generate data/memory_corpus/pack_v1.json."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval_memory_corpus.generate import generate_pack
from eval_memory_corpus.schema import DEFAULT_PACK_PATH, save_pack


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate chat memory corpus pack")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=DEFAULT_PACK_PATH)
    args = parser.parse_args()

    pack = generate_pack(seed=args.seed)
    path = save_pack(pack, args.out)
    print(
        f"Wrote {path} sessions={len(pack.sessions)} cases={len(pack.cases)} "
        f"smoke={pack.meta.get('smoke_count')} facts={pack.meta.get('fact_count')}"
    )
    if len(pack.sessions) < 200:
        print(f"ERROR: expected >=200 sessions, got {len(pack.sessions)}", file=sys.stderr)
        return 1
    if len(pack.cases) < 1000:
        print(f"ERROR: expected >=1000 cases, got {len(pack.cases)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
