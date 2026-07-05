"""Bisect sendRichMessage failures — run: python scripts/test_rich_blocks_api.py"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

from config import get_settings
from tools.phase4_config import admin_user_ids
from rich_demo import build_rich_blocks_demo_markdown
from rich_format import prepare_telegram_rich_markdown


async def try_md(client: httpx.AsyncClient, token: str, chat_id: int, md: str, label: str) -> dict:
    response = await client.post(
        f"https://api.telegram.org/bot{token}/sendRichMessage",
        json={"chat_id": chat_id, "rich_message": {"markdown": md}},
    )
    data = response.json()
    blocks: list[str] = []
    if data.get("ok"):
        blocks = [
            block.get("type", "?")
            for block in data.get("result", {}).get("rich_message", {}).get("blocks", [])
        ]
    return {
        "label": label,
        "ok": data.get("ok"),
        "error": data.get("description"),
        "blocks": blocks,
        "md_len": len(md),
    }


async def main() -> None:
    settings = get_settings(require_telegram_token=True)
    admins = list(admin_user_ids())
    if not admins:
        raise SystemExit("Set ADMIN_USER_IDS to your Telegram user id")
    chat_id = admins[0]

    full = prepare_telegram_rich_markdown(build_rich_blocks_demo_markdown())
    cases: list[tuple[str, str]] = [
        ("A text only", "# Hello\n\nParagraph **bold**"),
        ("B one photo", "# Hi\n\n![](https://telegram.org/example/photo.jpg)\n\nAfter"),
        ("C photo+caption", '![](https://telegram.org/example/photo.jpg "caption")'),
        (
            "D table+photo",
            prepare_telegram_rich_markdown(
                "# T\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
                "![](https://telegram.org/example/photo.jpg)"
            ),
        ),
        (
            "E collage md",
            "<tg-collage>\n"
            "![](https://telegram.org/example/photo.jpg)\n"
            "![](https://telegram.org/example/photo.jpg)\n"
            "</tg-collage>",
        ),
        ("F footnotes", "Text[^1]\n\n[^1]: note"),
        ("G blockquote", '<blockquote cite="X">quote</blockquote>'),
        ("H full demo", full),
    ]

    results: list[dict] = []
    async with httpx.AsyncClient(timeout=60) as client:
        for label, md in cases:
            results.append(await try_md(client, settings.telegram_bot_token, chat_id, md, label))

    out = Path("_api_test_results.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in results:
        status = "OK" if row["ok"] else "FAIL"
        print(f"{status} {row['label']}: {row.get('error') or row['blocks'][:8]}")


if __name__ == "__main__":
    asyncio.run(main())
