from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiogram.types import InlineKeyboardMarkup

from tools.outbound_files import OutboundDelivery


@dataclass(frozen=True)
class ChatResponse:
    text: str
    reply_markup: InlineKeyboardMarkup | None = None
    outbound_files: tuple[OutboundDelivery, ...] = ()
