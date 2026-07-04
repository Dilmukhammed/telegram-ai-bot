import argparse
import asyncio
import logging

from agent.loop import Agent
from config import get_settings
from tools.bootstrap import create_tool_runtime


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run Hermes agent locally")
    parser.add_argument("message", help="User message")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    runtime = await create_tool_runtime()
    agent = Agent(settings, runtime)
    reply = await agent.run(args.message)
    print(reply.reply)


if __name__ == "__main__":
    asyncio.run(main())
