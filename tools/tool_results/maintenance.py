from __future__ import annotations

import asyncio
import logging

from config import get_settings
from tools.tool_results.store import get_tool_result_store

logger = logging.getLogger(__name__)


def run_tool_result_maintenance() -> int:
    """Purge expired rows and enforce optional per-user row caps. Returns rows deleted."""
    settings = get_settings()
    if not settings.tool_result_archive_enabled:
        return 0

    store = get_tool_result_store()
    deleted = store.purge_expired()
    if settings.tool_result_max_rows_per_user > 0:
        deleted += store.enforce_user_row_caps(settings.tool_result_max_rows_per_user)
    if deleted:
        logger.info("tool_result_archive maintenance deleted=%s", deleted)
    return deleted


async def tool_result_cleanup_loop() -> None:
    settings = get_settings()
    interval = max(settings.tool_result_cleanup_interval_seconds, 60)
    logger.info("tool_result_archive cleanup loop interval=%ss", interval)
    while True:
        try:
            run_tool_result_maintenance()
        except Exception:
            logger.exception("tool_result_archive cleanup failed")
        await asyncio.sleep(interval)
