from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def layout_url_button_rows(
    buttons: tuple[tuple[str, str], ...],
    *,
    pair_when_more_than: int = 2,
) -> list[list[InlineKeyboardButton]]:
    """One button per row by default; 2 per row when count exceeds pair_when_more_than."""
    items = [InlineKeyboardButton(text=label, url=url) for label, url in buttons]
    if not items:
        return []
    if len(items) <= pair_when_more_than:
        return [[button] for button in items]
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(items), 2):
        rows.append(items[index : index + 2])
    return rows


def build_url_button_markup(
    buttons: tuple[tuple[str, str], ...],
    *,
    pair_when_more_than: int = 2,
) -> InlineKeyboardMarkup | None:
    rows = layout_url_button_rows(buttons, pair_when_more_than=pair_when_more_than)
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)
