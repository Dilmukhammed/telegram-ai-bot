from __future__ import annotations

from bot.user_location import format_location_user_message


def test_format_location_user_message() -> None:
    text = format_location_user_message(lat=41.2995, lng=69.2401)
    assert "геолокацию" in text
    assert "41.2995, 69.2401" in text


def test_format_location_with_label_and_caption() -> None:
    text = format_location_user_message(
        lat=41.1,
        lng=69.2,
        label="Южный вокзал",
        caption="Мне до метро Тинчлик",
    )
    assert "Южный вокзал" in text
    assert "Мне до метро Тинчлик" in text
