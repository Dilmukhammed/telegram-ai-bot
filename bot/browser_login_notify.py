from __future__ import annotations

from bot.telegram_notify import send_telegram_message


async def send_browser_login_link(
    user_id: int,
    *,
    public_url: str,
    expires_at: str,
) -> None:
    text = (
        "🔐 Browser login session ready.\n\n"
        "Open this one-time link to control the remote browser and sign in "
        "(e.g. Google). Do not forward it — anyone with the link can control the session.\n\n"
        f"{public_url}\n\n"
        f"Link expires: {expires_at}\n"
        "Session stays open after this message — take your time to log in.\n"
        "When finished, reply that you're done so the bot can close the session and save the profile."
    )
    await send_telegram_message(user_id, text)


async def send_browser_captcha_link(
    user_id: int,
    *,
    public_url: str,
    expires_at: str,
) -> None:
    text = (
        "🧩 Captcha needs a human.\n\n"
        "Open this one-time link, solve the captcha in the remote browser, "
        "then reply here that you're done so automation can continue.\n\n"
        f"{public_url}\n\n"
        f"Link expires: {expires_at}\n"
        "Do not forward the link."
    )
    await send_telegram_message(user_id, text)
