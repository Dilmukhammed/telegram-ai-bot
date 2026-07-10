"""CLI wrapper for the graph-memory evaluation runner."""

from __future__ import annotations

from pathlib import Path
import sys


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.eval.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
