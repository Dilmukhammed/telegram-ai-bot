import asyncio
import json

import httpx
from dotenv import load_dotenv

from config import get_settings

load_dotenv()


async def api(method: str, payload: dict | None = None) -> dict:
    settings = get_settings(require_telegram_token=True)
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload or {})
        data = response.json()
        print(f"\n=== {method} ===")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:6000])
        return data


async def main() -> None:
    updates = await api("getUpdates", {"limit": 5, "offset": -5})
    chat_id = None
    for item in updates.get("result", []):
        msg = item.get("message") or item.get("edited_message")
        if msg:
            chat_id = msg["chat"]["id"]
            break
    if chat_id is None:
        print("No chat_id in updates")
        return

    markdown = """| Feature | Status |
|:--------|:------:|
| Tables  | ok |
| Math    | ok |"""

    html = """<table>
<tr><th>Feature</th><th align="center">Status</th></tr>
<tr><td>Tables</td><td align="center">ok</td></tr>
<tr><td>Math</td><td align="center">ok</td></tr>
</table>"""

    for label, rich in [("markdown", {"markdown": markdown}), ("html", {"html": html})]:
        data = await api(
            "sendRichMessage",
            {"chat_id": chat_id, "rich_message": rich},
        )
        msg = data.get("result", {})
        blocks = msg.get("rich_message", {}).get("blocks", [])
        block_types = [b.get("type") for b in blocks]
        print(f"{label} block types:", block_types)

    draft = await api(
        "sendRichMessageDraft",
        {
            "chat_id": chat_id,
            "draft_id": 999001,
            "rich_message": {"html": "<tg-thinking></tg-thinking>"},
        },
    )
    print("draft ok:", draft.get("ok"))


if __name__ == "__main__":
    asyncio.run(main())
