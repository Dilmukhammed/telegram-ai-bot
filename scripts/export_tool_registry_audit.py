"""Export tool registry audit JSON for search ranking work."""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from tools.bootstrap import create_tool_runtime
from tools.search_index import TOOL_ALIASES, tool_method_name

DEFAULT_OUTPUT = Path("data/tool_registry_audit.json")


async def export_audit(output_path: Path) -> dict[str, list[dict[str, object]]]:
    runtime = await create_tool_runtime()
    tools = sorted(runtime._registry.all(), key=lambda tool: tool.name)

    families: dict[str, list[dict[str, object]]] = defaultdict(list)
    for tool in tools:
        segments = tool.name.split(".")
        family = ".".join(segments[:2]) if len(segments) >= 2 else segments[0]
        families[family].append(
            {
                "name": tool.name,
                "method": tool_method_name(tool.name),
                "tags": list(tool.tags),
                "has_alias": tool.name in TOOL_ALIASES,
            }
        )

    payload = {family: entries for family, entries in sorted(families.items())}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


async def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    payload = await export_audit(output)
    total = sum(len(entries) for entries in payload.values())
    print(f"exported {total} tools in {len(payload)} families -> {output}")


if __name__ == "__main__":
    asyncio.run(main())
