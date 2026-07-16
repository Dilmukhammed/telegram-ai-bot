from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def log_attachment_attempt(
    *,
    user_id: int,
    belief_id: str,
    accepted: bool,
    abstain_reason: str | None,
    llm_calls: int,
) -> None:
    logger.info(
        "memory_attachment_attempt",
        extra={
            "event": "memory_attachment_attempt",
            "user_id": user_id,
            "belief_id": belief_id,
            "accepted": accepted,
            "abstain_reason": abstain_reason,
            "llm_calls": llm_calls,
        },
    )
