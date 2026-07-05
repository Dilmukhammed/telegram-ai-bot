"""Validate fixed rich demo against Telegram API."""

from __future__ import annotations

import asyncio
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

from config import get_settings
from rich_demo import build_rich_blocks_demo_markdown
from rich_format import prepare_telegram_rich_markdown
from tools.phase4_config import admin_user_ids


async def send(md: str) -> tuple[bool, str]:
    settings = get_settings(require_telegram_token=True)
    chat_id = list(admin_user_ids())[0]
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendRichMessage",
            json={"chat_id": chat_id, "rich_message": {"markdown": md}},
        )
        data = response.json()
        if data.get("ok"):
            blocks = [b.get("type") for b in data["result"]["rich_message"]["blocks"]]
            return True, str(blocks)
        return False, str(data.get("description"))


async def main() -> None:
    md = prepare_telegram_rich_markdown(build_rich_blocks_demo_markdown())
    ok, detail = await send(md)
    print("full demo", ok, detail)
    if not ok:
        chunks = re.split(r"\n---\n\n", build_rich_blocks_demo_markdown())
        for index, chunk in enumerate(chunks):
            part = prepare_telegram_rich_markdown(chunk)
            ok, detail = await send(part)
            print(f"chunk {index}", ok, detail[:80] if not ok else detail[:120])


if __name__ == "__main__":
    asyncio.run(main())
