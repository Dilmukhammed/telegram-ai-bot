"""Collage/figcaption API probes."""

from __future__ import annotations

import asyncio

import httpx
from dotenv import load_dotenv

load_dotenv()

from config import get_settings
from tools.phase4_config import admin_user_ids


async def ok(client: httpx.AsyncClient, token: str, chat_id: int, md: str, label: str) -> None:
    response = await client.post(
        f"https://api.telegram.org/bot{token}/sendRichMessage",
        json={"chat_id": chat_id, "rich_message": {"markdown": md}},
    )
    data = response.json()
    print(label, "OK" if data.get("ok") else data.get("description"))


async def main() -> None:
    settings = get_settings(require_telegram_token=True)
    chat_id = list(admin_user_ids())[0]
    tests = {
        "fig+tg": (
            "<tg-collage>\n<figcaption>Cap <cite>A</cite></figcaption>\n"
            "![](https://telegram.org/example/photo.jpg)\n"
            "![](https://telegram.org/example/photo.jpg)\n</tg-collage>"
        ),
        "fig plain": (
            "<tg-collage>\n<figcaption>Cap</figcaption>\n"
            "![](https://telegram.org/example/photo.jpg)\n</tg-collage>"
        ),
        "html photo": (
            '<tg-collage>\n<figcaption>Cap</figcaption>\n'
            '<photo url="https://telegram.org/example/photo.jpg" />\n</tg-collage>'
        ),
        "slideshow no fig": (
            "<tg-slideshow>\n![](https://telegram.org/example/photo.jpg)\n"
            "![](https://telegram.org/example/photo.jpg)\n</tg-slideshow>"
        ),
        "slideshow fig": (
            "<tg-slideshow>\n<figcaption>Cap</figcaption>\n"
            "![](https://telegram.org/example/photo.jpg)\n</tg-slideshow>"
        ),
        "many photos no collage": (
            "![](https://telegram.org/example/photo.jpg)\n\n"
            "![](https://picsum.photos/seed/a/320/240)\n\n"
            "![](https://picsum.photos/seed/b/320/240)"
        ),
    }
    async with httpx.AsyncClient(timeout=60) as client:
        for label, md in tests.items():
            await ok(client, settings.telegram_bot_token, chat_id, md, label)


if __name__ == "__main__":
    asyncio.run(main())
