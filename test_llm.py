import asyncio

from config import get_settings
from llm import LLMClient


async def main() -> None:
    client = LLMClient(get_settings())
    reply = await client.chat([{"role": "user", "content": "Say hi in one word"}])
    print(reply)


if __name__ == "__main__":
    asyncio.run(main())
