from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from tools.builtins.google.auth import get_sheets_service

T = TypeVar("T")


async def run_sheets_call(user_id: int, fn: Callable[[Any], T]) -> T:
    service = await get_sheets_service(user_id)
    return await asyncio.to_thread(fn, service)
