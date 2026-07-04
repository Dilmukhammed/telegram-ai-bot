from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from tools.builtins.google.auth import get_drive_service

T = TypeVar("T")


async def run_drive_call(user_id: int, fn: Callable[[Any], T]) -> T:
    service = await get_drive_service(user_id)
    return await asyncio.to_thread(fn, service)


def drive_support_kwargs(*, supports_all_drives: bool = True) -> dict[str, bool]:
    return {"supportsAllDrives": supports_all_drives}


def drive_list_kwargs(*, supports_all_drives: bool = True) -> dict[str, bool]:
    return {
        "supportsAllDrives": supports_all_drives,
        "includeItemsFromAllDrives": supports_all_drives,
    }
