"""Probe search_tools using data/probe_queries.json or CLI args."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from tools.bootstrap import create_tool_runtime

DEFAULT_QUERIES_PATH = Path("data/probe_queries.json")


async def main() -> None:
    if len(sys.argv) > 1:
        probes = [{"query": query, "tags": None} for query in sys.argv[1:]]
    else:
        probes = json.loads(DEFAULT_QUERIES_PATH.read_text(encoding="utf-8"))

    runtime = await create_tool_runtime()
    for probe in probes:
        query = str(probe["query"])
        raw_tags = probe.get("tags")
        tags = list(raw_tags) if raw_tags else None
        note = probe.get("note")
        payload = await runtime.search_tools(query, top_k=5, tags=tags, mode="rank")
        print("=" * 80)
        if note:
            print("NOTE:", note)
        print("QUERY:", query, "tags=", tags)
        print("count:", payload.get("count"))
        for index, tool in enumerate(payload.get("tools", []), start=1):
            name = tool["name"]
            desc = (tool.get("description") or "")[:140]
            print(f"  {index}. {name}")
            print(f"     {desc}")
        tag_hints = payload.get("tag_hints")
        if tag_hints:
            print("tag_hints:", json.dumps(tag_hints, ensure_ascii=False)[:400])


if __name__ == "__main__":
    asyncio.run(main())
