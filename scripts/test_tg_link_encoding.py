"""One-off: compare how Telegram stores Maps URLs in rich messages."""
import asyncio
import json

import httpx
from dotenv import load_dotenv

load_dotenv()

from config import get_settings


def find_url(obj):
    if isinstance(obj, dict):
        if obj.get("type") == "url":
            return obj.get("url")
        for value in obj.values():
            found = find_url(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_url(item)
            if found:
                return found
    return None


async def main() -> None:
    settings = get_settings(require_telegram_token=True)
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    url = "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving"
    url_amp = url.replace("&", "&amp;")

    async with httpx.AsyncClient(timeout=30) as client:
        updates = (await client.post(f"{base}/getUpdates", json={"limit": 5, "offset": -5})).json()
        chat_id = None
        for item in updates.get("result", []):
            msg = item.get("message") or item.get("edited_message")
            if msg:
                chat_id = msg["chat"]["id"]
                break
        if chat_id is None:
            print("no chat_id in updates")
            return

        tests = {
            "html_amp": {"html": f'<a href="{url_amp}">html amp</a>'},
            "html_lit": {"html": f'<a href="{url}">html lit</a>'},
            "md_lit": {"markdown": f"[md lit]({url})"},
            "md_amp": {"markdown": f"[md amp]({url_amp})"},
            "plain": {"markdown": url},
            "details_html_lit": {
                "markdown": (
                    "<details><summary>Google Maps</summary>\n"
                    f'• <a href="{url}">Route</a>\n'
                    "</details>"
                )
            },
            "details_html_amp": {
                "markdown": (
                    "<details><summary>Google Maps</summary>\n"
                    f'• <a href="{url_amp}">Route</a>\n'
                    "</details>"
                )
            },
        }

        for name, rich in tests.items():
            payload = {"chat_id": chat_id, "rich_message": rich}
            data = (await client.post(f"{base}/sendRichMessage", json=payload)).json()
            stored = find_url(data.get("result", {}).get("rich_message", {})) if data.get("ok") else None
            print(f"{name}: ok={data.get('ok')} stored_url={stored!r}")
            if not data.get("ok"):
                print(" ", data.get("description"))


if __name__ == "__main__":
    asyncio.run(main())
