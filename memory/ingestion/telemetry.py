from __future__ import annotations

import logging
from typing import Any


def log_ingestion_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit a structured log entry with `event` as the top-level key.

    All extra fields are content-safe (no raw message bodies).
    """
    logger.log(level, event, extra={"event": event, **fields})


def log_ingestion_registered(
    logger: logging.Logger,
    *,
    stream: str,
    user_id: int,
    source_id: str,
    source_version_id: str,
    created: bool,
) -> None:
    log_ingestion_event(
        logger,
        "ingestion_source_registered",
        stream=stream,
        user_id=user_id,
        source_id=source_id,
        source_version_id=source_version_id,
        version_created=created,
    )


def log_ingestion_skipped(
    logger: logging.Logger,
    *,
    stream: str,
    item_key: str,
    reason: str,
) -> None:
    log_ingestion_event(
        logger,
        "ingestion_item_skipped",
        level=logging.DEBUG,
        stream=stream,
        item_key=item_key,
        reason=reason,
    )


def log_ingestion_failed(
    logger: logging.Logger,
    *,
    stream: str,
    item_key: str,
    error_class: str,
) -> None:
    log_ingestion_event(
        logger,
        "ingestion_item_failed",
        level=logging.WARNING,
        stream=stream,
        item_key=item_key,
        error_class=error_class,
    )


def log_cursor_advanced(
    logger: logging.Logger,
    *,
    stream: str,
    cursor: dict,
    registered: int,
    duplicate: int,
    failed: int,
) -> None:
    log_ingestion_event(
        logger,
        "ingestion_cursor_advanced",
        stream=stream,
        cursor=cursor,
        registered=registered,
        duplicate=duplicate,
        failed=failed,
    )
