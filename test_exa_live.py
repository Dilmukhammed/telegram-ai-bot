import asyncio
import json

from dotenv import load_dotenv

load_dotenv()

from tools.bootstrap import create_tool_runtime


async def main() -> None:
    runtime = await create_tool_runtime()

    print("=== exa.web_search ===")
    search = await runtime.use_tool(
        "exa.web_search",
        {"query": "latest AI news", "num_results": 3, "type": "instant"},
    )
    print(json.dumps(search, ensure_ascii=False, indent=2)[:3000])

    first_url = search["result"]["results"][0]["url"]
    print("\n=== exa.web_fetch ===")
    fetch = await runtime.use_tool("exa.web_fetch", {"urls": [first_url]})
    page = fetch["result"]["pages"][0]
    print(f"url: {page.get('url')}")
    print(f"title: {page.get('title')}")
    print(f"text preview: {(page.get('text') or '')[:400]}")


if __name__ == "__main__":
    asyncio.run(main())
