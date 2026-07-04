from __future__ import annotations


def format_location_user_message(
    *,
    lat: float,
    lng: float,
    label: str | None = None,
    caption: str | None = None,
) -> str:
    lines = [
        "Пользователь отправил геолокацию в Telegram.",
        f"Координаты: {float(lat)}, {float(lng)}.",
    ]
    place = (label or "").strip()
    if place:
        lines.append(f"Метка места: {place}.")
    text = (caption or "").strip()
    if text:
        lines.append(text)
    return "\n".join(lines)
