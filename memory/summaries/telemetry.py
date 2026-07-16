from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def log_summary_generated(
    *,
    user_id: int,
    summary_type: str,
    target_id: str,
    status: str,
    summary_id: str,
) -> None:
    logger.info(
        "memory_summary_generated user_id=%s type=%s target=%s status=%s id=%s",
        user_id,
        summary_type,
        target_id,
        status,
        summary_id,
    )


def log_summary_rejected(
    *,
    user_id: int,
    summary_type: str,
    target_id: str,
    reason: str | None,
) -> None:
    logger.warning(
        "memory_summary_rejected user_id=%s type=%s target=%s reason=%s",
        user_id,
        summary_type,
        target_id,
        reason,
    )
