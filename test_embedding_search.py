import asyncio
import json

from dotenv import load_dotenv

load_dotenv()

from tools.bootstrap import create_tool_runtime


async def main() -> None:
    runtime = await create_tool_runtime()
    result = await runtime.search_tools("find current news on the internet", top_k=3)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
