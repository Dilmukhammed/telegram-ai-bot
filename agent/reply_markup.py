from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from agent.drive_button_urls import DRIVE_MAX_BUTTONS, DRIVE_PAIR_WHEN_MORE_THAN
from agent.gmail_button_urls import MAX_COMBINED_INLINE_BUTTONS
from agent.inline_button_layout import build_url_button_markup, layout_url_button_rows


def build_reply_markup(
    *,
    maps_buttons: tuple[tuple[str, str], ...] = (),
    gmail_buttons: tuple[tuple[str, str], ...] = (),
    calendar_buttons: tuple[tuple[str, str], ...] = (),
    tasks_buttons: tuple[tuple[str, str], ...] = (),
    drive_buttons: tuple[tuple[str, str], ...] = (),
) -> InlineKeyboardMarkup | None:
    primary: list[tuple[str, str]] = []
    primary.extend(maps_buttons)
    primary.extend(gmail_buttons)
    primary.extend(calendar_buttons)
    primary.extend(tasks_buttons)
    primary = primary[:MAX_COMBINED_INLINE_BUTTONS]

    primary_rows = layout_url_button_rows(tuple(primary), pair_when_more_than=2)
    drive_rows = layout_url_button_rows(
        tuple(drive_buttons[:DRIVE_MAX_BUTTONS]),
        pair_when_more_than=DRIVE_PAIR_WHEN_MORE_THAN,
    )
    rows = primary_rows + drive_rows
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_maps_only_reply_markup(maps_buttons: tuple[tuple[str, str], ...]) -> InlineKeyboardMarkup | None:
    return build_url_button_markup(maps_buttons[:5])
